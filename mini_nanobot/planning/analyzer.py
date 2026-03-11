from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from mini_nanobot.planning.dashboard import build_dashboard_html
from mini_nanobot.planning.gridmap_viz import extract_gridmap_view
from mini_nanobot.planning.parser import (
    ParsedPlanningLog,
    clip,
    parse_planning_log_files,
    parse_planning_log_file,
    safe_message,
    severity_rank,
    stats,
    to_bool,
    to_int,
)
from mini_nanobot.planning.process_viz import extract_process_replay_files
from mini_nanobot.planning.profiles import PlanningThresholdProfile, resolve_profile


def build_error_payload(message: str, parse_warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "summary": "Planning log analysis failed.",
        "risk_level": "unknown",
        "score_0_to_100": 0.0,
        "key_metrics": {},
        "top_anomalies": [],
        "report_path": None,
        "dashboard_path": None,
        "parse_warnings": parse_warnings or [],
        "error": message,
    }


def _normalize_focus(focus: Any) -> str:
    value = str(focus or "comprehensive").strip().lower()
    if value not in {"comprehensive", "safety", "stability"}:
        return "comprehensive"
    return value


def _resolve_report_dir(
    workspace: Path,
    report_dir: str | Path | None,
    *,
    default_base_dir: Path | None = None,
) -> Path:
    if report_dir:
        path = Path(report_dir).expanduser()
        if not path.is_absolute():
            path = workspace / path
        return path
    if default_base_dir is not None:
        return default_base_dir / "reports"
    return workspace / "reports"


def _resolve_optional_data_path(log_path: Path, raw_path: str | Path | None) -> Path | None:
    if raw_path is None:
        candidate = log_path.parent / "planner_inputs.csv"
        return candidate if candidate.exists() and candidate.is_file() else None

    path = Path(raw_path).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates = [(Path.cwd() / path).resolve(), (log_path.parent / path).resolve()]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return candidates[0] if candidates else None


def _normalize_viz_backend(value: Any) -> str:
    return "matplotlib-svg"


def _resolve_log_paths(log_path: str | Path | None, log_paths: list[str | Path] | None) -> list[Path]:
    raw_values: list[str | Path] = []
    if log_paths:
        raw_values.extend(log_paths)
    if log_path not in (None, ""):
        raw_values.insert(0, log_path)

    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in raw_values:
        candidate = Path(str(raw)).expanduser()
        if not candidate.is_absolute():
            raise ValueError(f"log_path must be an absolute path: {candidate}")
        key = str(candidate)
        if key in seen:
            continue
        resolved.append(candidate)
        seen.add(key)
    return resolved


def _report_stem(log_paths: list[Path]) -> str:
    first = log_paths[0]
    if len(log_paths) == 1:
        return first.name
    return f"{first.name}__merged_{len(log_paths)}logs"


def _display_log_name(log_paths: list[Path]) -> str:
    first = log_paths[0]
    if len(log_paths) == 1:
        return first.name
    return f"{first.name} +{len(log_paths) - 1} logs"


def _display_log_path(log_paths: list[Path]) -> str:
    if len(log_paths) == 1:
        return str(log_paths[0])
    return " | ".join(str(path) for path in log_paths)


def _evidence(entries: list[dict[str, Any]], evidence_limit: int) -> list[dict[str, Any]]:
    out = []
    for entry in entries[:evidence_limit]:
        out.append(
            {
                "source_log": entry.get("source_log_name"),
                "line_no": entry.get("line_no"),
                "timestamp": entry.get("timestamp_raw"),
                "module": entry.get("module"),
                "message": safe_message(entry.get("message", "")),
            }
        )
    return out


def _downsample_points(points: list[dict[str, Any]], max_points: int = 220) -> list[list[float]]:
    if not points:
        return []
    if len(points) <= max_points:
        return [[round(point["x_mm"] / 1000.0, 3), round(point["y_mm"] / 1000.0, 3)] for point in points]
    result = []
    for idx in range(max_points):
        pos = round(idx * (len(points) - 1) / (max_points - 1))
        point = points[int(pos)]
        result.append([round(point["x_mm"] / 1000.0, 3), round(point["y_mm"] / 1000.0, 3)])
    return result


def _cycle_alert_score(cycle: dict[str, Any], profile: PlanningThresholdProfile) -> int:
    score = 0
    if cycle["yaw_jump_max_deg"] > profile.yaw_jump_max_deg:
        score += 2
    if cycle["curv_abs_max"] > profile.curv_abs_max or cycle["curv_delta_max"] > profile.curv_delta_max:
        score += 2
    if cycle.get("replan") == 1:
        score += 1
    if cycle["path_length_m"] < profile.short_path_length_m:
        score += 1
    return score


def _build_visualizations(
    *,
    log_paths: list[Path],
    planner_inputs_csv_path: str | Path | None,
    generate_process_replay: bool,
    generate_gridmap_view: bool,
    viz_backend: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    primary_log_path = log_paths[0]
    resolved_csv = _resolve_optional_data_path(primary_log_path, planner_inputs_csv_path)
    resolved_backend = viz_backend

    process_replay = {
        "enabled": False,
        "frame_count": 0,
        "fields_present": [],
        "file_boundaries": [],
        "frames": [],
        "warnings": [],
    }
    if generate_process_replay:
        process_replay = extract_process_replay_files(log_paths)
        warnings.extend(process_replay.get("warnings", []))

    gridmap_view = {
        "enabled": False,
        "frame_count": 0,
        "grid_size": 512,
        "resolution_mm_per_cell": 100.0,
        "fields_present": [],
        "frames": [],
        "warnings": [],
    }
    if generate_gridmap_view:
        if resolved_csv and resolved_csv.exists() and resolved_csv.is_file():
            gridmap_view = extract_gridmap_view(resolved_csv)
            warnings.extend(gridmap_view.get("warnings", []))
        else:
            warning = "planner_inputs.csv not found; gridmap visualization disabled."
            warnings.append(warning)
            gridmap_view["warnings"] = [warning]

    svg_visualizations = {
        "processReplayFrames": [],
        "gridMapFrames": [],
        "backend": "matplotlib-svg",
    }
    try:
        from mini_nanobot.planning.mpl_svg import render_svg_visualizations

        svg_visualizations = render_svg_visualizations(
            process_replay=process_replay,
            gridmap_view=gridmap_view,
        )
        resolved_backend = "matplotlib-svg"
    except ModuleNotFoundError as exc:
        resolved_backend = "unavailable"
        svg_visualizations["backend"] = "unavailable"
        warnings.append(f"matplotlib-svg backend unavailable: {exc}. Replay and gridmap views were not rendered.")
    except Exception as exc:
        resolved_backend = "unavailable"
        svg_visualizations["backend"] = "unavailable"
        warnings.append(f"matplotlib-svg rendering failed: {exc}. Replay and gridmap views were not rendered.")

    visualizations = {
        "process_replay": {
            "enabled": bool(process_replay.get("enabled")),
            "frame_count": int(process_replay.get("frame_count") or 0),
            "fields_present": process_replay.get("fields_present", []),
        },
        "gridmap_view": {
            "enabled": bool(gridmap_view.get("enabled")),
            "frame_count": int(gridmap_view.get("frame_count") or 0),
            "grid_size": int(gridmap_view.get("grid_size") or 0),
            "resolution_mm_per_cell": float(gridmap_view.get("resolution_mm_per_cell") or 0.0),
            "fields_present": gridmap_view.get("fields_present", []),
        },
        "planner_inputs_csv_resolved": str(resolved_csv) if resolved_csv and resolved_csv.exists() else None,
        "source_log_paths": [str(path) for path in log_paths],
        "viz_backend_requested": viz_backend,
        "viz_backend_resolved": resolved_backend,
        "visualization_warnings": warnings,
    }

    visualization_data = {
        "processReplayData": process_replay,
        "gridMapData": gridmap_view,
        "vizBackend": resolved_backend,
        "svgVisualizations": svg_visualizations,
        "visualizations": visualizations,
        "visualizationWarnings": warnings,
    }
    return visualizations, visualization_data, warnings


def _analyze_parsed_log(
    *,
    parsed: ParsedPlanningLog,
    log_paths: list[Path],
    workspace: Path,
    focus: str,
    save_report: bool,
    generate_dashboard: bool,
    report_dir: Path,
    evidence_limit: int,
    profile: PlanningThresholdProfile,
    planner_inputs_csv_path: str | Path | None,
    generate_process_replay: bool,
    generate_gridmap_view: bool,
    viz_backend: str,
) -> dict[str, Any]:
    parse_warnings = list(parsed.parse_warnings)
    if parsed.parsed_lines == 0:
        return build_error_payload("Log format mismatch: no parseable lines found.", parse_warnings)
    if not parsed.cycles:
        return build_error_payload("Log format mismatch: no planning cycles found.", parse_warnings)

    cycles = parsed.cycles
    cycle_with_points = [cycle for cycle in cycles if cycle["point_count"] > 0]
    if not cycle_with_points:
        return build_error_payload("No valid DecPlan trajectory points parsed from log.", parse_warnings)

    timer_intervals_ms: list[float] = []
    timer_jitter_evidence: list[dict[str, Any]] = []
    for idx in range(1, len(cycles)):
        if cycles[idx - 1].get("source_log_path") != cycles[idx].get("source_log_path"):
            continue
        prev_ts = cycles[idx - 1]["start_ts"]
        curr_ts = cycles[idx]["start_ts"]
        if not prev_ts or not curr_ts:
            continue
        delta_ms = (curr_ts - prev_ts).total_seconds() * 1000.0
        timer_intervals_ms.append(delta_ms)
        if delta_ms < profile.timer_interval_low_ms or delta_ms > profile.timer_interval_high_ms:
            timer_jitter_evidence.append(cycles[idx]["start_entry"])

    fork_times = [value for cycle in cycles for value in cycle["fork_times"]]
    path_sizes = [value for cycle in cycles for value in cycle["path_sizes"]]
    traj_segments = [value for cycle in cycles for value in cycle["trajectory_segments"]]
    point_counts = [cycle["point_count"] for cycle in cycle_with_points]
    path_lengths = [cycle["path_length_m"] for cycle in cycle_with_points]
    yaw_jumps = [cycle["yaw_jump_max_deg"] for cycle in cycle_with_points]
    curv_abs = [cycle["curv_abs_max"] for cycle in cycle_with_points]
    curv_delta = [cycle["curv_delta_max"] for cycle in cycle_with_points]

    anomalies: list[dict[str, Any]] = []
    jitter_count = len(timer_jitter_evidence)
    if jitter_count > 0:
        ratio = jitter_count / max(1, len(timer_intervals_ms))
        anomalies.append(
            {
                "rule": "timer_interval_range",
                "severity": "high" if ratio >= 0.2 else "medium",
                "category": "stability",
                "count": jitter_count,
                "detail": (
                    f"{jitter_count} timer intervals outside [{profile.timer_interval_low_ms},{profile.timer_interval_high_ms}]ms "
                    f"(ratio={round(ratio, 3)})."
                ),
                "evidence": _evidence(timer_jitter_evidence, evidence_limit),
            }
        )

    fork_high: list[dict[str, Any]] = []
    fork_medium: list[dict[str, Any]] = []
    for cycle in cycles:
        if not cycle["fork_evidence"]:
            continue
        for idx, value in enumerate(cycle["fork_times"]):
            evidence_entry = cycle["fork_evidence"][min(idx, len(cycle["fork_evidence"]) - 1)]
            if value > profile.fork_star_time_high_ms:
                fork_high.append(evidence_entry)
            elif value > profile.fork_star_time_medium_ms:
                fork_medium.append(evidence_entry)
    if fork_high:
        anomalies.append(
            {
                "rule": "fork_star_time",
                "severity": "high",
                "category": "stability",
                "count": len(fork_high),
                "detail": f"{len(fork_high)} cycles with FORK STAR USED TIME > {profile.fork_star_time_high_ms}ms.",
                "evidence": _evidence(fork_high, evidence_limit),
            }
        )
    elif fork_medium:
        anomalies.append(
            {
                "rule": "fork_star_time",
                "severity": "medium",
                "category": "stability",
                "count": len(fork_medium),
                "detail": f"{len(fork_medium)} cycles with FORK STAR USED TIME > {profile.fork_star_time_medium_ms}ms.",
                "evidence": _evidence(fork_medium, evidence_limit),
            }
        )

    low_path_evidence: list[dict[str, Any]] = []
    for cycle in cycles:
        if not cycle["path_size_evidence"]:
            continue
        for idx, size in enumerate(cycle["path_sizes"]):
            if size < profile.path_size_min:
                low_path_evidence.append(cycle["path_size_evidence"][min(idx, len(cycle["path_size_evidence"]) - 1)])
    if low_path_evidence:
        anomalies.append(
            {
                "rule": "output_path_size",
                "severity": "medium",
                "category": "safety",
                "count": len(low_path_evidence),
                "detail": f"{len(low_path_evidence)} path outputs with size < {profile.path_size_min}.",
                "evidence": _evidence(low_path_evidence, evidence_limit),
            }
        )

    yaw_evidence = [cycle["start_entry"] for cycle in cycle_with_points if cycle["yaw_jump_max_deg"] > profile.yaw_jump_max_deg]
    if yaw_evidence:
        anomalies.append(
            {
                "rule": "yaw_jump_max_deg",
                "severity": "high",
                "category": "safety",
                "count": len(yaw_evidence),
                "detail": f"{len(yaw_evidence)} cycles with yaw_jump_max_deg > {profile.yaw_jump_max_deg}.",
                "evidence": _evidence(yaw_evidence, evidence_limit),
            }
        )

    curv_evidence = [
        cycle["start_entry"]
        for cycle in cycle_with_points
        if cycle["curv_abs_max"] > profile.curv_abs_max or cycle["curv_delta_max"] > profile.curv_delta_max
    ]
    if curv_evidence:
        anomalies.append(
            {
                "rule": "curvature_limits",
                "severity": "high",
                "category": "safety",
                "count": len(curv_evidence),
                "detail": (
                    f"{len(curv_evidence)} cycles violate curvature limit "
                    f"(|curv|>{profile.curv_abs_max} or delta>{profile.curv_delta_max})."
                ),
                "evidence": _evidence(curv_evidence, evidence_limit),
            }
        )

    longest_replan_streak = 0
    streak = 0
    streak_end = -1
    for idx, cycle in enumerate(cycles):
        if cycle["replan"] == 1:
            streak += 1
            if streak > longest_replan_streak:
                longest_replan_streak = streak
                streak_end = idx
        else:
            streak = 0
    if longest_replan_streak >= profile.replan_streak_high:
        start = streak_end - longest_replan_streak + 1
        streak_evidence = [cycles[i]["start_entry"] for i in range(start, streak_end + 1)]
        anomalies.append(
            {
                "rule": "replan_streak",
                "severity": "high",
                "category": "stability",
                "count": longest_replan_streak,
                "detail": f"Consecutive Replan=1 streak detected: {longest_replan_streak} cycles.",
                "evidence": _evidence(streak_evidence, evidence_limit),
            }
        )

    collision_fail_entries = [
        entry
        for cycle in cycles
        for entry in cycle["collision_evidence"]
        if "fail" in entry["message"].lower()
    ]
    if collision_fail_entries:
        anomalies.append(
            {
                "rule": "collision_check_fail",
                "severity": "high",
                "category": "safety",
                "count": len(collision_fail_entries),
                "detail": f"{len(collision_fail_entries)} collision check failure logs found.",
                "evidence": _evidence(collision_fail_entries, evidence_limit),
            }
        )

    safety_risk = 0.0
    stability_risk = 0.0
    if yaw_evidence:
        safety_risk += 30.0
    if curv_evidence:
        safety_risk += 30.0
    if low_path_evidence:
        safety_risk += min(20.0, len(low_path_evidence) * 5.0)
    if collision_fail_entries:
        safety_risk += min(40.0, len(collision_fail_entries) * 10.0)
    if jitter_count > 0:
        stability_risk += (jitter_count / max(1, len(timer_intervals_ms))) * 35.0
    if fork_high:
        stability_risk += min(35.0, len(fork_high) * 8.0)
    elif fork_medium:
        stability_risk += min(20.0, len(fork_medium) * 4.0)
    if longest_replan_streak >= profile.replan_streak_high:
        stability_risk += 25.0
        safety_risk += 10.0
    if not timer_intervals_ms:
        stability_risk += 10.0

    safety_risk = clip(safety_risk, 0.0, 100.0)
    stability_risk = clip(stability_risk, 0.0, 100.0)
    if focus == "safety":
        score = safety_risk
    elif focus == "stability":
        score = stability_risk
    else:
        score = (0.6 * safety_risk) + (0.4 * stability_risk)
    score = round(clip(score, 0.0, 100.0), 1)

    anomalies_sorted = sorted(anomalies, key=lambda item: (severity_rank(item["severity"]), item.get("count", 0)), reverse=True)
    high_count = sum(1 for anomaly in anomalies_sorted if anomaly["severity"] == "high")
    if high_count >= 3:
        score = max(score, 75.0)
    elif high_count >= 1:
        score = max(score, 45.0)
    if score >= 70:
        risk_level = "high"
    elif score >= 40:
        risk_level = "medium"
    else:
        risk_level = "low"

    cycle_replan_flags = [cycle["replan"] for cycle in cycles if cycle["replan"] is not None]
    replan_ratio = round(sum(cycle_replan_flags) / len(cycle_replan_flags), 3) if cycle_replan_flags else 0.0
    summary = (
        f"Analyzed {len(parsed.lines)} lines in {len(cycles)} planning cycles across {len(log_paths)} log(s). "
        f"Profile={profile.name}, Risk={risk_level} ({score}/100), high anomalies={high_count}."
    )

    ranked_cycles = sorted(
        cycle_with_points,
        key=lambda cycle: (
            _cycle_alert_score(cycle, profile),
            cycle["curv_abs_max"],
            cycle["yaw_jump_max_deg"],
            cycle["path_length_m"],
        ),
        reverse=True,
    )
    selected_cycles: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    for cycle in ranked_cycles[:10]:
        cycle_id = int(cycle["index"])
        selected_cycles.append(cycle)
        selected_ids.add(cycle_id)
    for cycle in cycle_with_points[:5]:
        cycle_id = int(cycle["index"])
        if cycle_id in selected_ids:
            continue
        selected_cycles.append(cycle)
        selected_ids.add(cycle_id)
        if len(selected_cycles) >= 14:
            break

    trajectory_preview = []
    for cycle in selected_cycles[:14]:
        points_sorted = [cycle["points"][idx] for idx in sorted(cycle["points"])]
        alert_score = _cycle_alert_score(cycle, profile)
        if alert_score >= 3:
            risk_tag = "high"
        elif alert_score >= 1:
            risk_tag = "medium"
        else:
            risk_tag = "normal"
        trajectory_preview.append(
            {
                "cycle_index": cycle["index"],
                "timestamp": cycle["start_entry"]["timestamp_raw"],
                "point_count": cycle["point_count"],
                "path_length_m": round(cycle["path_length_m"], 3),
                "yaw_jump_max_deg": round(cycle["yaw_jump_max_deg"], 3),
                "curv_abs_max": round(cycle["curv_abs_max"], 5),
                "risk_tag": risk_tag,
                "alert_score": alert_score,
                "points_xy_m": _downsample_points(points_sorted),
            }
        )

    key_metrics = {
        "line_count": len(parsed.lines),
        "parsed_line_count": parsed.parsed_lines,
        "cycle_count": len(cycles),
        "cycle_with_points_count": len(cycle_with_points),
        "trajectory_preview_count": len(trajectory_preview),
        "level_counts": dict(parsed.level_counts),
        "top_modules": [{"module": name, "count": count} for name, count in parsed.module_counts.most_common(12)],
        "timer_interval_ms": stats(timer_intervals_ms, ndigits=2),
        "timer_jitter_count": jitter_count,
        "fork_star_time_ms": stats([float(value) for value in fork_times], ndigits=2),
        "replan_ratio": replan_ratio,
        "longest_replan_streak": longest_replan_streak,
        "path_size": stats([float(value) for value in path_sizes], ndigits=2),
        "trajectory_segments": stats([float(value) for value in traj_segments], ndigits=2),
        "geometry": {
            "point_count": stats([float(value) for value in point_counts], ndigits=2),
            "path_length_m": stats(path_lengths, ndigits=3),
            "yaw_jump_max_deg": stats(yaw_jumps, ndigits=3),
            "curv_abs_max": stats(curv_abs, ndigits=5),
            "curv_delta_max": stats(curv_delta, ndigits=5),
        },
        "risk_breakdown": {
            "focus": focus,
            "safety_risk_0_to_100": round(safety_risk, 1),
            "stability_risk_0_to_100": round(stability_risk, 1),
        },
        "threshold_profile": profile.to_dict(),
    }

    cycle_metrics_preview = [
        {
            "cycle_index": cycle["index"],
            "timestamp": cycle["start_entry"]["timestamp_raw"],
            "point_count": cycle["point_count"],
            "path_length_m": round(cycle["path_length_m"], 3),
            "yaw_jump_max_deg": round(cycle["yaw_jump_max_deg"], 3),
            "curv_abs_max": round(cycle["curv_abs_max"], 5),
            "curv_delta_max": round(cycle["curv_delta_max"], 5),
            "replan": cycle["replan"],
            "fork_star_time_ms": cycle["fork_times"][0] if cycle["fork_times"] else None,
            "path_size": cycle["path_sizes"][0] if cycle["path_sizes"] else None,
        }
        for cycle in cycles[:120]
    ]

    visualizations, visualization_data, visualization_warnings = _build_visualizations(
        log_paths=log_paths,
        planner_inputs_csv_path=planner_inputs_csv_path,
        generate_process_replay=generate_process_replay,
        generate_gridmap_view=generate_gridmap_view,
        viz_backend=viz_backend,
    )
    parse_warnings.extend(w for w in visualization_warnings if w not in parse_warnings)

    dashboard_data = {
        "timerIntervals": [round(value, 3) for value in timer_intervals_ms[:300]],
        "forkTimes": [int(value) for value in fork_times[:300]],
        "cycleIndex": [int(cycle["cycle_index"]) for cycle in cycle_metrics_preview[:200]],
        "yawJump": [float(cycle["yaw_jump_max_deg"]) for cycle in cycle_metrics_preview[:200]],
        "pathLength": [float(cycle["path_length_m"]) for cycle in cycle_metrics_preview[:200]],
        "curvAbs": [float(cycle["curv_abs_max"]) for cycle in cycle_metrics_preview[:200]],
        "trajectoryPreview": trajectory_preview[:24],
        "anomalies": [
            {
                "rule": anomaly.get("rule"),
                "severity": anomaly.get("severity"),
                "count": anomaly.get("count"),
                "detail": anomaly.get("detail"),
            }
            for anomaly in anomalies_sorted[:30]
        ],
        "thresholds": {
            "timer_interval_low_ms": profile.timer_interval_low_ms,
            "timer_interval_high_ms": profile.timer_interval_high_ms,
            "yaw_jump_max_deg": profile.yaw_jump_max_deg,
        },
        **visualization_data,
    }

    report_stem = _report_stem(log_paths)
    report_path: str | None = None
    dashboard_path: str | None = None
    full_report = {
        "summary": summary,
        "risk_level": risk_level,
        "score_0_to_100": score,
        "focus": focus,
        "profile": profile.name,
        "input": {
            "log_path": str(log_paths[0]),
            "log_paths": [str(path) for path in log_paths],
            "analyzed_lines": len(parsed.lines),
            "total_lines": parsed.total_lines,
            "null_bytes_removed": parsed.null_byte_count,
        },
        "key_metrics": key_metrics,
        "top_anomalies": anomalies_sorted,
        "parse_warnings": parse_warnings,
        "trajectory_preview": trajectory_preview,
        "cycle_metrics_preview": cycle_metrics_preview,
        "visualizations": visualizations,
        "dashboard_data_preview": dashboard_data,
    }

    if save_report:
        try:
            report_dir.mkdir(parents=True, exist_ok=True)
            report_file = report_dir / f"{report_stem}.analysis.json"
            report_file.write_text(json.dumps(full_report, ensure_ascii=False, indent=2), encoding="utf-8")
            report_path = str(report_file)
            if generate_dashboard:
                dashboard_html = build_dashboard_html(
                    log_path=log_paths[0],
                    log_name_display=_display_log_name(log_paths),
                    log_path_display=_display_log_path(log_paths),
                    summary=summary,
                    risk_level=risk_level,
                    score=score,
                    key_metrics=key_metrics,
                    anomalies=anomalies_sorted,
                    dashboard_data=dashboard_data,
                    profile=profile,
                )
                dashboard_file = report_dir / f"{report_stem}.analysis.html"
                dashboard_file.write_text(dashboard_html, encoding="utf-8")
                dashboard_path = str(dashboard_file)
        except Exception as exc:
            parse_warnings.append(f"Failed to write report file: {exc}")

    return {
        "summary": summary,
        "risk_level": risk_level,
        "score_0_to_100": score,
        "key_metrics": key_metrics,
        "top_anomalies": anomalies_sorted,
        "report_path": report_path,
        "dashboard_path": dashboard_path,
        "parse_warnings": parse_warnings,
        "profile": profile.name,
        "visualizations": visualizations,
    }


def analyze_planning_log(
    *,
    workspace: Path,
    log_path: str | Path | None = None,
    log_paths: list[str | Path] | None = None,
    focus: str = "comprehensive",
    save_report: Any = True,
    generate_dashboard: Any = True,
    report_dir: str | Path | None = None,
    max_lines: Any = 200000,
    evidence_limit: Any = 8,
    profile: str | None = "j6b_default",
    profile_path: str | Path | None = None,
    planner_inputs_csv_path: str | Path | None = None,
    generate_process_replay: Any = True,
    generate_gridmap_view: Any = True,
    viz_backend: Any = "matplotlib-svg",
) -> dict[str, Any]:
    try:
        resolved_log_paths = _resolve_log_paths(log_path, log_paths)
    except ValueError as exc:
        return build_error_payload(str(exc))
    if not resolved_log_paths:
        return build_error_payload("Missing required argument: log_path or log_paths")
    for resolved_log_path in resolved_log_paths:
        if not resolved_log_path.exists() or not resolved_log_path.is_file():
            return build_error_payload(f"log file not found: {resolved_log_path}")

    focus_value = _normalize_focus(focus)
    save_report_value = to_bool(save_report, True)
    generate_dashboard_value = to_bool(generate_dashboard, True)
    max_lines_value = max(1000, to_int(max_lines, 200000))
    evidence_limit_value = int(clip(float(to_int(evidence_limit, 8)), 1.0, 20.0))
    report_dir_value = _resolve_report_dir(
        workspace,
        report_dir,
        default_base_dir=resolved_log_paths[0].parent,
    )
    generate_process_replay_value = to_bool(generate_process_replay, True)
    generate_gridmap_view_value = to_bool(generate_gridmap_view, True)
    viz_backend_value = _normalize_viz_backend(viz_backend)
    try:
        threshold_profile = resolve_profile(profile, profile_path)
    except ValueError as exc:
        return build_error_payload(str(exc))

    try:
        if len(resolved_log_paths) == 1:
            parsed = parse_planning_log_file(resolved_log_paths[0], max_lines_value)
        else:
            parsed = parse_planning_log_files(resolved_log_paths, max_lines_value)
    except Exception as exc:
        return build_error_payload(f"failed to read log file: {exc}")

    return _analyze_parsed_log(
        parsed=parsed,
        log_paths=resolved_log_paths,
        workspace=workspace,
        focus=focus_value,
        save_report=save_report_value,
        generate_dashboard=generate_dashboard_value,
        report_dir=report_dir_value,
        evidence_limit=evidence_limit_value,
        profile=threshold_profile,
        planner_inputs_csv_path=planner_inputs_csv_path,
        generate_process_replay=generate_process_replay_value,
        generate_gridmap_view=generate_gridmap_view_value,
        viz_backend=viz_backend_value,
    )


def analyze_planning_log_to_json(*, workspace: Path, **kwargs: Any) -> str:
    try:
        payload = analyze_planning_log(workspace=workspace, **kwargs)
    except Exception as exc:
        payload = build_error_payload(f"Unexpected analyzer error: {exc}")
    return json.dumps(payload, ensure_ascii=False, indent=2)


def batch_analyze_logs(
    *,
    workspace: Path,
    log_dir: str | Path,
    pattern: str = "planning.log*",
    recursive: bool = False,
    max_files: int = 200,
    focus: str = "comprehensive",
    save_report: Any = True,
    generate_dashboard: Any = True,
    report_dir: str | Path | None = None,
    max_lines: Any = 200000,
    evidence_limit: Any = 8,
    profile: str | None = "j6b_default",
    profile_path: str | Path | None = None,
    planner_inputs_csv_path: str | Path | None = None,
    generate_process_replay: Any = True,
    generate_gridmap_view: Any = True,
    viz_backend: Any = "matplotlib-svg",
) -> dict[str, Any]:
    base_dir = Path(log_dir).expanduser()
    if not base_dir.is_absolute():
        base_dir = (Path.cwd() / base_dir).resolve()
    if not base_dir.exists() or not base_dir.is_dir():
        return {"summary": "Batch planning log analysis failed.", "error": f"log_dir not found: {base_dir}", "items": []}

    matcher = base_dir.rglob if recursive else base_dir.glob
    files = sorted(path for path in matcher(pattern) if path.is_file())
    if max_files > 0:
        files = files[:max_files]
    report_dir_value = _resolve_report_dir(
        workspace,
        report_dir,
        default_base_dir=base_dir,
    )

    items: list[dict[str, Any]] = []
    for path in files:
        result = analyze_planning_log(
            workspace=workspace,
            log_path=str(path.resolve()),
            focus=focus,
            save_report=save_report,
            generate_dashboard=generate_dashboard,
            report_dir=report_dir_value,
            max_lines=max_lines,
            evidence_limit=evidence_limit,
            profile=profile,
            profile_path=profile_path,
            planner_inputs_csv_path=planner_inputs_csv_path,
            generate_process_replay=generate_process_replay,
            generate_gridmap_view=generate_gridmap_view,
            viz_backend=viz_backend,
        )
        items.append(
            {
                "log_path": str(path.resolve()),
                "summary": result.get("summary"),
                "risk_level": result.get("risk_level"),
                "score_0_to_100": result.get("score_0_to_100"),
                "report_path": result.get("report_path"),
                "dashboard_path": result.get("dashboard_path"),
                "top_rules": [anomaly.get("rule") for anomaly in result.get("top_anomalies", [])[:6]],
                "visualizations": result.get("visualizations"),
                "error": result.get("error"),
            }
        )

    ranked_items = sorted(items, key=lambda item: float(item.get("score_0_to_100") or 0.0), reverse=True)
    risk_counts = dict(Counter(str(item.get("risk_level") or "unknown") for item in ranked_items))
    summary = {
        "summary": f"Analyzed {len(ranked_items)} planning logs from {base_dir}.",
        "log_dir": str(base_dir),
        "pattern": pattern,
        "recursive": recursive,
        "profile": profile,
        "file_count": len(ranked_items),
        "risk_counts": risk_counts,
        "items": ranked_items,
        "summary_path": None,
    }

    if to_bool(save_report, True):
        try:
            report_dir_value.mkdir(parents=True, exist_ok=True)
            summary_path = report_dir_value / "batch_analysis.summary.json"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            summary["summary_path"] = str(summary_path)
        except Exception as exc:
            summary["write_warning"] = f"Failed to write batch summary: {exc}"
    return summary
