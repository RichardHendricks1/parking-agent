from __future__ import annotations

import fnmatch
import json
import os
import re
from collections import Counter
from difflib import SequenceMatcher
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


_DEFAULT_LOG_GLOB = "planning.log*"
_SEARCH_DEPTH_LIMIT = 6
_SEARCH_RESULT_LIMIT = 64
_GENERIC_PATH_TOKENS = {"users", "home", "downloads", "desktop", "documents", "tmp", "private", "var"}
_MODULE_NAMES = ("planning", "localization", "perception")
_SEVERITY_WEIGHTS = {"high": 3, "medium": 2, "low": 1}
_GEOMETRY_FIELDS = ("parking_space", "slot_corners", "fused_p0_p5", "realtime_parkingspace")
_ALERT_STOP_REASONS = {
    "FRONT_ALERT",
    "REAR_ALERT",
    "LEFTSIDE_ALERT",
    "RIGHTSIDE_ALERT",
    "TARGET_CLOSING",
    "LEFTRVW_ALERT",
    "RIGHTRVW_ALERT",
}


def build_error_payload(message: str, parse_warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "summary": "Planning log analysis failed.",
        "risk_level": "unknown",
        "score_0_to_100": 0.0,
        "key_metrics": {},
        "top_anomalies": [],
        "report_path": None,
        "dashboard_path": None,
        "module_signals": [],
        "module_diagnosis": {
            "primary_module": "unknown",
            "confidence_0_to_1": 0.0,
            "reason": "Evidence is insufficient to assign a primary module.",
            "module_scores": {module: 0 for module in _MODULE_NAMES},
            "evidence": [],
            "limitations": ["Based on planning.log heuristics only."],
        },
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


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        deduped.append(path)
        seen.add(key)
    return deduped


def _nearest_existing_dir(path: Path) -> Path | None:
    current = path.expanduser()
    while True:
        if current.exists():
            return current if current.is_dir() else current.parent
        if current == current.parent:
            return None
        current = current.parent


def _build_log_search_roots(candidate: Path) -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    common_home_roots = [home / "Downloads", home / "Desktop", home / "Documents", home]

    if candidate.is_absolute():
        nearest = _nearest_existing_dir(candidate)
        if nearest and nearest not in {Path("/"), home}:
            roots.append(nearest.resolve())
        else:
            roots.extend(root for root in common_home_roots if root.exists())
    else:
        roots.append(Path.cwd().resolve())
        roots.extend(root for root in common_home_roots if root.exists())

    return _dedupe_paths([root for root in roots if root.exists() and root.is_dir()])


def _looks_like_glob(pattern: str) -> bool:
    return any(char in pattern for char in "*?[]")


def _looks_like_log_file_hint(candidate: Path) -> bool:
    name = candidate.name.casefold()
    return name.startswith("planning.log") or _looks_like_glob(candidate.name) or "." in candidate.name


def _log_merge_sort_key(path: Path) -> tuple[str, float, str]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (path.name.casefold(), mtime, str(path))


def _search_logs_in_directory(directory: Path) -> list[Path]:
    matches = [
        path.resolve()
        for path in directory.resolve().glob(_DEFAULT_LOG_GLOB)
        if path.is_file()
    ]
    return sorted(_dedupe_paths(matches), key=_log_merge_sort_key)


def _build_log_search_patterns(candidate: Path) -> list[str]:
    name = candidate.name.strip()
    if not name:
        return [_DEFAULT_LOG_GLOB]

    patterns: list[str] = []
    lowered = name.casefold()
    if _looks_like_glob(name):
        patterns.append(name)
    elif lowered.startswith("planning.log"):
        patterns.append(name)
        patterns.append(f"{name}*")
    elif "." in name:
        patterns.append(name)
        patterns.append(f"{name}*")
    patterns.append(_DEFAULT_LOG_GLOB)

    deduped: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        if pattern in seen:
            continue
        deduped.append(pattern)
        seen.add(pattern)
    return deduped


def _iter_log_matches(root: Path, patterns: list[str], *, max_depth: int, limit: int) -> list[Path]:
    matches: list[Path] = []
    root = root.resolve()
    root_depth = len(root.parts)
    skip_dirs = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv"}

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.parts) - root_depth
        dirs[:] = [name for name in dirs if name not in skip_dirs and not name.startswith(".")]
        if depth >= max_depth:
            dirs[:] = []
        for file_name in files:
            if not any(fnmatch.fnmatch(file_name, pattern) for pattern in patterns):
                continue
            path = (current_path / file_name).resolve()
            if path.is_file():
                matches.append(path)
            if len(matches) >= limit:
                return matches
    return matches


def _normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _path_hint_tokens(candidate: Path) -> list[str]:
    tokens: list[str] = []
    for part in candidate.parts:
        token = _normalize_token(part)
        if len(token) < 3 or token in _GENERIC_PATH_TOKENS:
            continue
        tokens.append(token)
    return tokens[-4:]


def _score_log_candidate(requested: Path, found: Path) -> tuple[int, float]:
    requested_name = requested.name.casefold()
    found_name = found.name.casefold()
    requested_text = str(requested).casefold()
    found_text = str(found).casefold()
    normalized_found = _normalize_token(found_text)

    score = 0
    if requested_name and found_name == requested_name:
        score += 400
    elif requested_name and found_name.startswith(requested_name):
        score += 260
    elif requested_name and requested_name in found_name:
        score += 180
    if found_name.startswith("planning.log"):
        score += 80
    if requested_text and found_text.endswith(requested_text):
        score += 160
    for token in _path_hint_tokens(requested):
        if token in normalized_found:
            score += 35
    score += int(SequenceMatcher(None, requested_text[-160:], found_text[-160:]).ratio() * 100.0)
    try:
        mtime = found.stat().st_mtime
    except OSError:
        mtime = 0.0
    return score, mtime


def _search_for_log_candidates(candidate: Path) -> tuple[list[Path], str]:
    roots = _build_log_search_roots(candidate)
    patterns = _build_log_search_patterns(candidate)
    matches: list[Path] = []

    for root in roots:
        remaining = max(1, _SEARCH_RESULT_LIMIT - len(matches))
        matches.extend(
            _iter_log_matches(
                root,
                patterns,
                max_depth=_SEARCH_DEPTH_LIMIT,
                limit=remaining,
            )
        )
        if len(matches) >= _SEARCH_RESULT_LIMIT:
            break

    ranked = sorted(
        _dedupe_paths(matches),
        key=lambda path: _score_log_candidate(candidate, path),
        reverse=True,
    )
    roots_text = ", ".join(str(root) for root in roots) if roots else "(none)"
    patterns_text = ", ".join(patterns)
    return ranked, f"Searched under {roots_text} with patterns {patterns_text}."


def _resolve_single_log_path(raw: str | Path) -> tuple[list[Path], list[str]]:
    raw_text = str(raw or "").strip()
    if not raw_text:
        raise ValueError("Empty log_path value")

    candidate = Path(raw_text).expanduser()
    if candidate.exists():
        if candidate.is_file():
            return [candidate.resolve()], []
        if candidate.is_dir():
            matches = _search_logs_in_directory(candidate)
            if matches:
                if len(matches) == 1:
                    warning = f"log_path pointed to directory {candidate}; resolved to {matches[0]}."
                else:
                    warning = f"log_path pointed to directory {candidate}; merged {len(matches)} candidate log(s)."
                return matches, [warning]
            matches, search_note = _search_for_log_candidates(candidate)
            if matches:
                chosen = matches[0]
                warning = (
                    f"log_path pointed to directory {candidate}; auto-selected {chosen} "
                    f"from {len(matches)} candidate log(s)."
                )
                return [chosen], [warning]
            raise ValueError(f"log directory contains no planning.log* files: {candidate}. {search_note}")

    matches, search_note = _search_for_log_candidates(candidate)
    if matches:
        if not _looks_like_log_file_hint(candidate):
            merged = _search_logs_in_directory(matches[0].parent)
            if merged:
                warning = (
                    f"log_path {candidate} was not found; auto-resolved to directory {matches[0].parent} "
                    f"and merged {len(merged)} candidate log(s)."
                )
                return merged, [warning]
        chosen = matches[0]
        warning = (
            f"log_path {candidate} was not found; auto-resolved to {chosen} "
            f"from {len(matches)} candidate log(s)."
        )
        return [chosen], [warning]

    if candidate.is_absolute():
        raise ValueError(f"log file not found: {candidate}. {search_note}")
    raise ValueError(f"log_path not found from hint: {candidate}. {search_note}")


def _resolve_log_paths(
    log_path: str | Path | None,
    log_paths: list[str | Path] | None,
) -> tuple[list[Path], list[str]]:
    raw_values: list[str | Path] = []
    if log_paths:
        raw_values.extend(log_paths)
    if log_path not in (None, ""):
        raw_values.insert(0, log_path)

    resolved: list[Path] = []
    warnings: list[str] = []
    seen: set[str] = set()
    seen_raw: set[str] = set()
    for raw in raw_values:
        raw_key = str(raw).strip()
        if raw_key in seen_raw:
            continue
        seen_raw.add(raw_key)
        candidates, candidate_warnings = _resolve_single_log_path(raw)
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            resolved.append(candidate)
            seen.add(key)
        warnings.extend(candidate_warnings)
    return resolved, warnings


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


def _cycle_risk_tag(alert_score: int) -> str:
    if alert_score >= 3:
        return "high"
    if alert_score >= 1:
        return "medium"
    return "normal"


def _severity_weight(severity: str) -> int:
    return int(_SEVERITY_WEIGHTS.get(str(severity or "").lower(), 0))


def _frame_value_label(frame: dict[str, Any], key: str) -> str | None:
    value = frame.get(key)
    if isinstance(value, dict):
        label = value.get("label")
        if label not in (None, ""):
            return str(label)
        raw = value.get("value")
        if raw not in (None, ""):
            return str(raw)
    return None


def _frame_has_geometry(frame: dict[str, Any]) -> bool:
    return any(frame.get(field) for field in _GEOMETRY_FIELDS)


def _frame_evidence(frame: dict[str, Any], detail: str) -> dict[str, Any]:
    evidence = {
        "source_log": frame.get("log_name") or Path(str(frame.get("source_log_path") or "")).name or None,
        "frame_index": frame.get("frame_index"),
        "plan_frame_id": frame.get("plan_frame_id"),
        "detail": safe_message(detail),
    }
    if frame.get("vehicle_location_timestamp"):
        evidence["vehicle_location_timestamp"] = frame["vehicle_location_timestamp"].get("value")
    if frame.get("perception_fusion_timestamp"):
        evidence["perception_fusion_timestamp"] = frame["perception_fusion_timestamp"].get("value")
    stop_reason = _frame_value_label(frame, "vehicle_stop_reason")
    if stop_reason:
        evidence["vehicle_stop_reason"] = stop_reason
    return evidence


def _dedupe_evidence_rows(rows: list[dict[str, Any]], evidence_limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (
            row.get("source_log"),
            row.get("frame_index"),
            row.get("plan_frame_id"),
            row.get("detail"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= evidence_limit:
            break
    return out


def _points_by_key(points: list[dict[str, Any]] | None) -> dict[str, tuple[float, float]]:
    if not points:
        return {}
    keyed: dict[str, tuple[float, float]] = {}
    for idx, point in enumerate(points):
        if not isinstance(point, dict):
            continue
        key = str(point.get("label") or idx)
        if "x_mm" not in point or "y_mm" not in point:
            continue
        keyed[key] = (float(point["x_mm"]), float(point["y_mm"]))
    return keyed


def _points_max_delta_mm(
    prev_points: list[dict[str, Any]] | None,
    curr_points: list[dict[str, Any]] | None,
) -> float | None:
    prev_map = _points_by_key(prev_points)
    curr_map = _points_by_key(curr_points)
    common = sorted(set(prev_map) & set(curr_map))
    if not common:
        return None
    max_delta = 0.0
    for key in common:
        prev_x, prev_y = prev_map[key]
        curr_x, curr_y = curr_map[key]
        dx = curr_x - prev_x
        dy = curr_y - prev_y
        max_delta = max(max_delta, (dx * dx + dy * dy) ** 0.5)
    return round(max_delta, 3)


def _geometry_field_deltas(prev_frame: dict[str, Any], curr_frame: dict[str, Any]) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for field in _GEOMETRY_FIELDS:
        delta = _points_max_delta_mm(prev_frame.get(field), curr_frame.get(field))
        if delta is not None:
            deltas[field] = delta
    return deltas


def _pose_distance_mm(prev_pose: dict[str, Any] | None, curr_pose: dict[str, Any] | None) -> float | None:
    if not prev_pose or not curr_pose:
        return None
    dx = float(curr_pose["x_mm"]) - float(prev_pose["x_mm"])
    dy = float(curr_pose["y_mm"]) - float(prev_pose["y_mm"])
    return round((dx * dx + dy * dy) ** 0.5, 3)


def _yaw_delta_deg(prev_yaw: float, curr_yaw: float) -> float:
    diff = float(curr_yaw) - float(prev_yaw)
    while diff > 180.0:
        diff -= 360.0
    while diff < -180.0:
        diff += 360.0
    return round(abs(diff), 3)


def _stable_ego_pose(prev_frame: dict[str, Any], curr_frame: dict[str, Any], profile: PlanningThresholdProfile) -> bool:
    prev_pose = prev_frame.get("vehicle_location")
    curr_pose = curr_frame.get("vehicle_location")
    if not prev_pose or not curr_pose:
        return False
    distance_mm = _pose_distance_mm(prev_pose, curr_pose)
    yaw_delta = _yaw_delta_deg(prev_pose["yaw_deg"], curr_pose["yaw_deg"])
    if distance_mm is None:
        return False
    return (
        distance_mm <= profile.localization_pose_jump_max_mm
        and yaw_delta <= profile.localization_yaw_jump_max_deg
    )


def _build_module_signal(
    *,
    signal: str,
    module: str,
    severity: str,
    detail: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "signal": signal,
        "module": module,
        "severity": severity,
        "detail": detail,
        "evidence": evidence,
    }


def _signal_sort_key(signal: dict[str, Any]) -> tuple[int, int, int]:
    module = str(signal.get("module") or "")
    return (
        _severity_weight(str(signal.get("severity") or "")),
        len(signal.get("evidence") or []),
        -_MODULE_NAMES.index(module) if module in _MODULE_NAMES else -len(_MODULE_NAMES),
    )


def _planning_module_signals(anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _build_module_signal(
            signal=str(anomaly.get("rule") or "planning_anomaly"),
            module="planning",
            severity=str(anomaly.get("severity") or "low"),
            detail=str(anomaly.get("detail") or ""),
            evidence=list(anomaly.get("evidence") or []),
        )
        for anomaly in anomalies
    ]


def _heuristic_module_signals(
    frames: list[dict[str, Any]],
    *,
    profile: PlanningThresholdProfile,
    evidence_limit: int,
) -> list[dict[str, Any]]:
    if not frames:
        return []

    total_frames = len(frames)
    signals: list[dict[str, Any]] = []
    high_missing_ratio = min(0.9, profile.signal_missing_ratio_high + 0.25)

    vehicle_location_missing = [
        frame
        for frame in frames
        if not frame.get("vehicle_location") or not frame.get("vehicle_location_timestamp")
    ]
    vehicle_location_missing_ratio = len(vehicle_location_missing) / max(1, total_frames)
    if vehicle_location_missing_ratio >= profile.signal_missing_ratio_high:
        severity = "high" if vehicle_location_missing_ratio >= high_missing_ratio else "medium"
        evidence = _dedupe_evidence_rows(
            [
                _frame_evidence(frame, "Vehicle location or its timestamp was missing in the replay frame.")
                for frame in vehicle_location_missing
            ],
            evidence_limit,
        )
        signals.append(
            _build_module_signal(
                signal="vehicle_location_missing_ratio",
                module="localization",
                severity=severity,
                detail=(
                    f"{len(vehicle_location_missing)} / {total_frames} replay frames were missing vehicle "
                    f"location or vehicle_location_timestamp (ratio={round(vehicle_location_missing_ratio, 3)})."
                ),
                evidence=evidence,
            )
        )

    localization_pose_jump_rows: list[dict[str, Any]] = []
    for prev_frame, curr_frame in zip(frames, frames[1:]):
        prev_pose = prev_frame.get("vehicle_location")
        curr_pose = curr_frame.get("vehicle_location")
        if not prev_pose or not curr_pose:
            continue
        pose_distance_mm = _pose_distance_mm(prev_pose, curr_pose)
        yaw_delta = _yaw_delta_deg(prev_pose["yaw_deg"], curr_pose["yaw_deg"])
        if pose_distance_mm is None:
            continue
        if (
            pose_distance_mm <= profile.localization_pose_jump_max_mm
            and yaw_delta <= profile.localization_yaw_jump_max_deg
        ):
            continue
        geometry_deltas = _geometry_field_deltas(prev_frame, curr_frame)
        if not geometry_deltas:
            continue
        if any(delta > profile.perception_geometry_jump_max_mm for delta in geometry_deltas.values()):
            continue
        stable_fields = ", ".join(
            f"{field}={fmt_num}"
            for field, fmt_num in (
                (field, f"{round(delta, 1)}mm") for field, delta in sorted(geometry_deltas.items())
            )
        )
        localization_pose_jump_rows.append(
            _frame_evidence(
                curr_frame,
                (
                    f"Vehicle pose jumped {round(pose_distance_mm, 1)}mm / {round(yaw_delta, 1)}deg "
                    f"while geometry stayed stable ({stable_fields})."
                ),
            )
        )
    if localization_pose_jump_rows:
        signals.append(
            _build_module_signal(
                signal="vehicle_location_pose_jump",
                module="localization",
                severity="high",
                detail=(
                    f"{len(localization_pose_jump_rows)} adjacent replay frame pairs showed vehicle pose jumps "
                    f"> {profile.localization_pose_jump_max_mm}mm or > {profile.localization_yaw_jump_max_deg}deg "
                    f"while parking-space geometry remained stable."
                ),
                evidence=_dedupe_evidence_rows(localization_pose_jump_rows, evidence_limit),
            )
        )

    track_loss_frames = [
        frame
        for frame in frames
        if _frame_value_label(frame, "vehicle_stop_reason") == "TRACK_LOSS"
    ]
    if track_loss_frames:
        signals.append(
            _build_module_signal(
                signal="vehicle_stop_reason_track_loss",
                module="localization",
                severity="high",
                detail=f"{len(track_loss_frames)} replay frame(s) reported vehicle_stop_reason=TRACK_LOSS.",
                evidence=_dedupe_evidence_rows(
                    [_frame_evidence(frame, "vehicle_stop_reason=TRACK_LOSS") for frame in track_loss_frames],
                    evidence_limit,
                ),
            )
        )

    perception_missing = [
        frame
        for frame in frames
        if not frame.get("perception_fusion_timestamp") or not _frame_has_geometry(frame)
    ]
    perception_missing_ratio = len(perception_missing) / max(1, total_frames)
    if perception_missing_ratio >= profile.signal_missing_ratio_high:
        severity = "high" if perception_missing_ratio >= high_missing_ratio else "medium"
        evidence = _dedupe_evidence_rows(
            [
                _frame_evidence(frame, "Perception fusion timestamp or parking-space geometry was missing.")
                for frame in perception_missing
            ],
            evidence_limit,
        )
        signals.append(
            _build_module_signal(
                signal="perception_fusion_missing_ratio",
                module="perception",
                severity=severity,
                detail=(
                    f"{len(perception_missing)} / {total_frames} replay frames were missing perception_fusion_timestamp "
                    f"or parking-space geometry (ratio={round(perception_missing_ratio, 3)})."
                ),
                evidence=evidence,
            )
        )

    geometry_jump_rows: list[dict[str, Any]] = []
    for prev_frame, curr_frame in zip(frames, frames[1:]):
        if not _stable_ego_pose(prev_frame, curr_frame, profile):
            continue
        geometry_deltas = _geometry_field_deltas(prev_frame, curr_frame)
        jumped = {
            field: delta
            for field, delta in geometry_deltas.items()
            if delta > profile.perception_geometry_jump_max_mm
        }
        if not jumped:
            continue
        jumped_fields = ", ".join(f"{field}={round(delta, 1)}mm" for field, delta in sorted(jumped.items()))
        geometry_jump_rows.append(
            _frame_evidence(
                curr_frame,
                (
                    f"Parking-space geometry jumped beyond {profile.perception_geometry_jump_max_mm}mm "
                    f"while ego pose stayed stable ({jumped_fields})."
                ),
            )
        )
    if geometry_jump_rows:
        signals.append(
            _build_module_signal(
                signal="parking_space_geometry_jump",
                module="perception",
                severity="high",
                detail=(
                    f"{len(geometry_jump_rows)} adjacent replay frame pairs showed parking-space geometry jumps "
                    f"> {profile.perception_geometry_jump_max_mm}mm while ego pose remained stable."
                ),
                evidence=_dedupe_evidence_rows(geometry_jump_rows, evidence_limit),
            )
        )

    stopper_jump_rows: list[dict[str, Any]] = []
    longest_alert_streak = 0
    current_alert_streak: list[dict[str, Any]] = []
    alert_streak_rows: list[dict[str, Any]] = []
    for prev_frame, curr_frame in zip(frames, frames[1:]):
        prev_distance = prev_frame.get("stopper_distance_mm")
        curr_distance = curr_frame.get("stopper_distance_mm")
        if prev_distance is not None and curr_distance is not None:
            delta = abs(float(curr_distance) - float(prev_distance))
            if delta > profile.stopper_distance_jump_max_mm:
                stopper_jump_rows.append(
                    _frame_evidence(
                        curr_frame,
                        (
                            f"stopper_distance_mm changed by {round(delta, 1)}mm "
                            f"(threshold={profile.stopper_distance_jump_max_mm}mm)."
                        ),
                    )
                )
        stop_reason = _frame_value_label(curr_frame, "vehicle_stop_reason")
        if stop_reason in _ALERT_STOP_REASONS:
            current_alert_streak.append(curr_frame)
            if len(current_alert_streak) > longest_alert_streak:
                longest_alert_streak = len(current_alert_streak)
                alert_streak_rows = [
                    _frame_evidence(frame, f"vehicle_stop_reason={_frame_value_label(frame, 'vehicle_stop_reason')}")
                    for frame in current_alert_streak
                ]
        else:
            current_alert_streak = []
    if stopper_jump_rows or longest_alert_streak >= 2:
        severity = "high" if len(stopper_jump_rows) >= 2 or longest_alert_streak >= 3 else "medium"
        clauses: list[str] = []
        if stopper_jump_rows:
            clauses.append(
                f"{len(stopper_jump_rows)} stopper distance jump(s) exceeded {profile.stopper_distance_jump_max_mm}mm"
            )
        if longest_alert_streak >= 2:
            clauses.append(f"alert stop reasons repeated for {longest_alert_streak} frame(s)")
        signals.append(
            _build_module_signal(
                signal="stopper_alert_oscillation",
                module="perception",
                severity=severity,
                detail="; ".join(clauses) + ".",
                evidence=_dedupe_evidence_rows(stopper_jump_rows + alert_streak_rows, evidence_limit),
            )
        )

    return sorted(signals, key=_signal_sort_key, reverse=True)


def _build_module_diagnosis(
    module_signals: list[dict[str, Any]],
    *,
    profile: PlanningThresholdProfile,
    process_frame_count: int,
) -> dict[str, Any]:
    module_scores = {module: 0 for module in _MODULE_NAMES}
    for signal in module_signals:
        module = str(signal.get("module") or "")
        if module in module_scores:
            module_scores[module] += _severity_weight(str(signal.get("severity") or ""))

    ranked_modules = sorted(
        module_scores.items(),
        key=lambda item: (-item[1], _MODULE_NAMES.index(item[0])),
    )
    top_module, top_score = ranked_modules[0]
    second_score = ranked_modules[1][1] if len(ranked_modules) > 1 else 0
    total_score = sum(module_scores.values())
    confidence = round(top_score / max(total_score, 1), 2)
    limitations = ["Based on planning.log heuristics only."]
    if process_frame_count <= 0:
        limitations.append(
            "Process replay fields were unavailable; localization and perception attribution remained conservative."
        )

    primary_module = top_module
    if (
        top_score < profile.module_min_evidence_score
        or (top_score - second_score) < profile.module_primary_margin_score
    ):
        primary_module = "unknown"

    ranked_signals = sorted(module_signals, key=_signal_sort_key, reverse=True)
    primary_signals = [
        signal for signal in ranked_signals if signal.get("module") == primary_module
    ] if primary_module != "unknown" else ranked_signals
    evidence = [
        {
            "signal": signal.get("signal"),
            "module": signal.get("module"),
            "severity": signal.get("severity"),
            "detail": signal.get("detail"),
            "evidence_count": len(signal.get("evidence") or []),
            "sample": (signal.get("evidence") or [None])[0],
        }
        for signal in primary_signals[:3]
    ]

    if primary_module == "unknown":
        if total_score <= 0:
            reason = "Evidence is insufficient to assign a primary module."
        elif top_score < profile.module_min_evidence_score:
            reason = "Evidence is insufficient to assign a primary module with confidence."
        else:
            reason = "Evidence is split across modules and does not meet the primary margin threshold."
    else:
        details = "; ".join(safe_message(str(signal.get("detail") or ""), 160) for signal in primary_signals[:3])
        reason = f"Primary suspect is {primary_module}: {details}"

    return {
        "primary_module": primary_module,
        "confidence_0_to_1": confidence,
        "reason": reason,
        "module_scores": module_scores,
        "evidence": evidence,
        "limitations": limitations,
    }


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
    parse_warnings_prefix: list[str] | None = None,
) -> dict[str, Any]:
    parse_warnings = list(parse_warnings_prefix or []) + list(parsed.parse_warnings)
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

    cycle_timer_interval_ms: dict[int, float | None] = {}
    cycle_timer_jitter_ids: set[int] = set()
    for idx, cycle in enumerate(cycles):
        cycle_id = int(cycle["index"])
        cycle_timer_interval_ms[cycle_id] = None
        if idx == 0:
            continue
        if cycles[idx - 1].get("source_log_path") != cycle.get("source_log_path"):
            continue
        prev_ts = cycles[idx - 1]["start_ts"]
        curr_ts = cycle["start_ts"]
        if not prev_ts or not curr_ts:
            continue
        delta_ms = (curr_ts - prev_ts).total_seconds() * 1000.0
        cycle_timer_interval_ms[cycle_id] = round(delta_ms, 3)
        if delta_ms < profile.timer_interval_low_ms or delta_ms > profile.timer_interval_high_ms:
            cycle_timer_jitter_ids.add(cycle_id)

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
    analysis_start_ts = next((cycle.get("start_ts") for cycle in cycles if cycle.get("start_ts")), None)
    analysis_end_ts = next((cycle.get("start_ts") for cycle in reversed(cycles) if cycle.get("start_ts")), None)
    analysis_duration_s = 0.0
    if analysis_start_ts and analysis_end_ts and analysis_end_ts >= analysis_start_ts:
        analysis_duration_s = round((analysis_end_ts - analysis_start_ts).total_seconds(), 3)
    summary = (
        f"Analyzed {len(parsed.lines)} lines in {len(cycles)} planning cycles across {len(log_paths)} log(s). "
        f"Profile={profile.name}, Risk={risk_level} ({score}/100), high anomalies={high_count}."
    )

    severity_counts = {
        "high": sum(1 for anomaly in anomalies_sorted if anomaly.get("severity") == "high"),
        "medium": sum(1 for anomaly in anomalies_sorted if anomaly.get("severity") == "medium"),
        "low": sum(1 for anomaly in anomalies_sorted if anomaly.get("severity") == "low"),
    }

    source_coverage_map: dict[str, dict[str, Any]] = {}
    for cycle in cycles:
        source_path = str(cycle.get("source_log_path") or "")
        if not source_path:
            continue
        record = source_coverage_map.setdefault(
            source_path,
            {
                "path": source_path,
                "name": str(cycle.get("source_log_name") or Path(source_path).name),
                "cycle_count": 0,
                "trajectory_cycle_count": 0,
                "first_cycle_index": int(cycle["index"]),
                "last_cycle_index": int(cycle["index"]),
                "first_timestamp": cycle["start_entry"]["timestamp_raw"],
                "last_timestamp": cycle["start_entry"]["timestamp_raw"],
            },
        )
        record["cycle_count"] += 1
        if cycle["point_count"] > 0:
            record["trajectory_cycle_count"] += 1
        record["first_cycle_index"] = min(record["first_cycle_index"], int(cycle["index"]))
        record["last_cycle_index"] = max(record["last_cycle_index"], int(cycle["index"]))
        if not record.get("first_timestamp"):
            record["first_timestamp"] = cycle["start_entry"]["timestamp_raw"]
        record["last_timestamp"] = cycle["start_entry"]["timestamp_raw"]
    source_coverage = list(source_coverage_map.values())

    risk_drivers = [
        {
            "rule": anomaly.get("rule"),
            "severity": anomaly.get("severity"),
            "category": anomaly.get("category"),
            "count": anomaly.get("count"),
            "detail": anomaly.get("detail"),
            "evidence_count": len(anomaly.get("evidence") or []),
            "sample": (anomaly.get("evidence") or [{}])[0],
        }
        for anomaly in anomalies_sorted[:6]
    ]

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
        risk_tag = _cycle_risk_tag(alert_score)
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

    cycle_diagnostics = []
    for cycle in selected_cycles[:24]:
        cycle_id = int(cycle["index"])
        alert_score = _cycle_alert_score(cycle, profile)
        risk_tag = _cycle_risk_tag(alert_score)
        issues: list[str] = []
        if cycle_id in cycle_timer_jitter_ids:
            issues.append("timer jitter")
        if cycle["yaw_jump_max_deg"] > profile.yaw_jump_max_deg:
            issues.append("yaw jump")
        if cycle["curv_abs_max"] > profile.curv_abs_max or cycle["curv_delta_max"] > profile.curv_delta_max:
            issues.append("curvature")
        if cycle.get("replan") == 1:
            issues.append("replan")
        if cycle["path_length_m"] < profile.short_path_length_m:
            issues.append("short path")
        if any(value > profile.fork_star_time_high_ms for value in cycle["fork_times"]):
            issues.append("fork high")
        elif any(value > profile.fork_star_time_medium_ms for value in cycle["fork_times"]):
            issues.append("fork medium")
        if any(value < profile.path_size_min for value in cycle["path_sizes"]):
            issues.append("path small")
        cycle_diagnostics.append(
            {
                "cycle_index": cycle_id,
                "timestamp": cycle["start_entry"]["timestamp_raw"],
                "source_log_name": str(cycle.get("source_log_name") or ""),
                "source_log_path": str(cycle.get("source_log_path") or ""),
                "line_no": cycle["start_entry"].get("line_no"),
                "alert_score": alert_score,
                "risk_tag": risk_tag,
                "timer_interval_ms": cycle_timer_interval_ms.get(cycle_id),
                "timer_jitter": cycle_id in cycle_timer_jitter_ids,
                "replan": cycle["replan"],
                "fork_star_time_ms": max(cycle["fork_times"]) if cycle["fork_times"] else None,
                "path_size": min(cycle["path_sizes"]) if cycle["path_sizes"] else None,
                "point_count": cycle["point_count"],
                "path_length_m": round(cycle["path_length_m"], 3),
                "yaw_jump_max_deg": round(cycle["yaw_jump_max_deg"], 3),
                "curv_abs_max": round(cycle["curv_abs_max"], 5),
                "curv_delta_max": round(cycle["curv_delta_max"], 5),
                "issues": issues,
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
    process_replay_data = visualization_data.get("processReplayData") or {}
    process_replay_frames = list(process_replay_data.get("frames") or [])
    process_replay_frame_count = int(process_replay_data.get("frame_count") or len(process_replay_frames))
    module_signals = _planning_module_signals(anomalies_sorted)
    module_signals.extend(
        _heuristic_module_signals(
            process_replay_frames,
            profile=profile,
            evidence_limit=evidence_limit,
        )
    )
    module_signals = sorted(module_signals, key=_signal_sort_key, reverse=True)
    module_diagnosis = _build_module_diagnosis(
        module_signals,
        profile=profile,
        process_frame_count=process_replay_frame_count,
    )

    analysis_overview = {
        "focus": focus,
        "profile": profile.name,
        "log_count": len(log_paths),
        "warning_count": len(parse_warnings),
        "parsed_line_ratio": round(parsed.parsed_lines / max(1, parsed.total_lines), 3),
        "analysis_start": cycles[0]["start_entry"]["timestamp_raw"],
        "analysis_end": cycles[-1]["start_entry"]["timestamp_raw"],
        "analysis_duration_s": analysis_duration_s,
        "null_bytes_removed": parsed.null_byte_count,
        "severity_counts": severity_counts,
        "risk_breakdown": {
            "score_0_to_100": score,
            "focus": focus,
            "safety_risk_0_to_100": round(safety_risk, 1),
            "stability_risk_0_to_100": round(stability_risk, 1),
        },
        "visualization_summary": {
            "process_replay_frames": visualizations["process_replay"]["frame_count"],
            "gridmap_frames": visualizations["gridmap_view"]["frame_count"],
        },
    }

    dashboard_data = {
        "timerIntervals": [round(value, 3) for value in timer_intervals_ms[:300]],
        "forkTimes": [int(value) for value in fork_times[:300]],
        "cycleIndex": [int(cycle["cycle_index"]) for cycle in cycle_metrics_preview[:200]],
        "yawJump": [float(cycle["yaw_jump_max_deg"]) for cycle in cycle_metrics_preview[:200]],
        "pathLength": [float(cycle["path_length_m"]) for cycle in cycle_metrics_preview[:200]],
        "curvAbs": [float(cycle["curv_abs_max"]) for cycle in cycle_metrics_preview[:200]],
        "trajectoryPreview": trajectory_preview[:24],
        "cycleDiagnostics": cycle_diagnostics,
        "anomalies": [
            {
                "rule": anomaly.get("rule"),
                "category": anomaly.get("category"),
                "severity": anomaly.get("severity"),
                "count": anomaly.get("count"),
                "detail": anomaly.get("detail"),
                "evidence_count": len(anomaly.get("evidence") or []),
                "sample": (anomaly.get("evidence") or [{}])[0],
            }
            for anomaly in anomalies_sorted[:30]
        ],
        "analysisOverview": analysis_overview,
        "riskDrivers": risk_drivers,
        "sourceCoverage": source_coverage,
        "topModules": key_metrics["top_modules"][:6],
        "moduleDiagnosis": module_diagnosis,
        "moduleSignals": module_signals[:12],
        "parseWarnings": parse_warnings[:12],
        "thresholds": {
            "timer_interval_low_ms": profile.timer_interval_low_ms,
            "timer_interval_high_ms": profile.timer_interval_high_ms,
            "yaw_jump_max_deg": profile.yaw_jump_max_deg,
            "curv_abs_max": profile.curv_abs_max,
            "curv_delta_max": profile.curv_delta_max,
            "path_size_min": profile.path_size_min,
            "short_path_length_m": profile.short_path_length_m,
            "fork_star_time_medium_ms": profile.fork_star_time_medium_ms,
            "fork_star_time_high_ms": profile.fork_star_time_high_ms,
            "signal_missing_ratio_high": profile.signal_missing_ratio_high,
            "localization_pose_jump_max_mm": profile.localization_pose_jump_max_mm,
            "localization_yaw_jump_max_deg": profile.localization_yaw_jump_max_deg,
            "perception_geometry_jump_max_mm": profile.perception_geometry_jump_max_mm,
            "stopper_distance_jump_max_mm": profile.stopper_distance_jump_max_mm,
            "module_min_evidence_score": profile.module_min_evidence_score,
            "module_primary_margin_score": profile.module_primary_margin_score,
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
        "module_signals": module_signals,
        "module_diagnosis": module_diagnosis,
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
        "module_signals": module_signals,
        "module_diagnosis": module_diagnosis,
        "parse_warnings": parse_warnings,
        "resolved_log_paths": [str(path) for path in log_paths],
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
        resolved_log_paths, resolution_warnings = _resolve_log_paths(log_path, log_paths)
    except ValueError as exc:
        return build_error_payload(str(exc))
    if not resolved_log_paths:
        return build_error_payload("Missing required argument: log_path or log_paths")

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
        return build_error_payload(f"failed to read log file: {exc}", resolution_warnings)

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
        parse_warnings_prefix=resolution_warnings,
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
                "module_diagnosis": result.get("module_diagnosis"),
                "module_signals": result.get("module_signals", [])[:8],
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
