from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<level>[A-Z]+)\]\s+\[(?P<module>[^\]]+)\](?P<rest>.*)$")
_REPLAN_RE = re.compile(r"Replan:(\d+)")
_FORK_TIME_RE = re.compile(r"FORK STAR USED TIME:([0-9]+)\s*ms", re.IGNORECASE)
_PATH_SIZE_RE = re.compile(r"OUTPUT PATH SIZE:([0-9]+)", re.IGNORECASE)
_TRAJ_SEG_RE = re.compile(r"trajectory[^\n]*?([0-9]+)\s*segments", re.IGNORECASE)
_POINT_RE = re.compile(
    r"No\[(?P<idx>\d+)\]\s*x\[(?P<x>-?\d+(?:\.\d+)?)mm\]\s*y\[(?P<y>-?\d+(?:\.\d+)?)mm\]"
    r"\s*yaw\[(?P<yaw>-?\d+(?:\.\d+)?)degree\]\s*curv\[(?P<curv>-?\d+(?:\.\d+)?)mm\]"
)


@dataclass
class ParsedPlanningLog:
    log_path: Path
    source_log_paths: list[Path]
    lines: list[str]
    total_lines: int
    null_byte_count: int
    parse_warnings: list[str]
    parsed_lines: int
    unparsed_lines: int
    level_counts: Counter[str]
    module_counts: Counter[str]
    cycles: list[dict[str, Any]]


def clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def to_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def to_bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in {"true", "1", "yes", "y"}:
            return True
        if low in {"false", "0", "no", "n"}:
            return False
    return default


def severity_rank(severity: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(severity, 0)


def safe_message(message: str, max_len: int = 220) -> str:
    clean = message.replace("\n", " ").replace("\r", " ")
    return clean if len(clean) <= max_len else clean[:max_len] + "..."


def stats(values: list[float], ndigits: int = 3) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    vals = sorted(float(v) for v in values)
    n = len(vals)
    p95_idx = min(n - 1, math.ceil(0.95 * n) - 1)
    return {
        "count": n,
        "min": round(vals[0], ndigits),
        "max": round(vals[-1], ndigits),
        "avg": round(sum(vals) / n, ndigits),
        "p95": round(vals[p95_idx], ndigits),
    }


def _parse_ts(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _angle_delta(a: float, b: float) -> float:
    diff = b - a
    while diff > 180.0:
        diff -= 360.0
    while diff < -180.0:
        diff += 360.0
    return abs(diff)


def _parse_line(line: str, line_no: int) -> dict[str, Any] | None:
    match = _LINE_RE.match(line.strip())
    if not match:
        return None
    rest = match.group("rest").strip()
    while rest.startswith("["):
        end = rest.find("]")
        if end <= 0:
            break
        rest = rest[end + 1 :].strip()
    ts_raw = match.group("ts")
    return {
        "line_no": line_no,
        "timestamp_raw": ts_raw,
        "timestamp": _parse_ts(ts_raw),
        "level": match.group("level"),
        "module": match.group("module"),
        "message": rest,
        "raw": line,
    }


def _finalize_cycle(cycle: dict[str, Any]) -> dict[str, Any]:
    points = [cycle["points"][i] for i in sorted(cycle["points"])]
    point_count = len(points)
    path_length_m = 0.0
    yaw_jump_max_deg = 0.0
    curv_abs_max = 0.0
    curv_delta_max = 0.0
    if point_count >= 1:
        curv_abs_max = max(abs(point["curv"]) for point in points)
    if point_count >= 2:
        for idx in range(1, point_count):
            prev = points[idx - 1]
            curr = points[idx]
            dx = curr["x_mm"] - prev["x_mm"]
            dy = curr["y_mm"] - prev["y_mm"]
            path_length_m += math.sqrt(dx * dx + dy * dy) / 1000.0
            yaw_jump_max_deg = max(yaw_jump_max_deg, _angle_delta(prev["yaw_deg"], curr["yaw_deg"]))
            curv_delta_max = max(curv_delta_max, abs(curr["curv"] - prev["curv"]))

    cycle["point_count"] = point_count
    cycle["path_length_m"] = path_length_m
    cycle["yaw_jump_max_deg"] = yaw_jump_max_deg
    cycle["curv_abs_max"] = curv_abs_max
    cycle["curv_delta_max"] = curv_delta_max
    if cycle["replan_values"]:
        cycle["replan"] = 1 if any(val == 1 for val in cycle["replan_values"]) else 0
    else:
        cycle["replan"] = None
    return cycle


def _parse_single_planning_log_file(log_path: Path, max_lines: int) -> ParsedPlanningLog:
    data = log_path.read_bytes()
    parse_warnings: list[str] = []
    null_byte_count = data.count(b"\x00")
    if null_byte_count:
        parse_warnings.append(f"Removed {null_byte_count} null bytes from log before parsing.")
        data = data.replace(b"\x00", b"")

    text = data.decode("utf-8", errors="ignore")
    all_lines = text.splitlines()
    total_lines = len(all_lines)
    if total_lines > max_lines:
        parse_warnings.append(f"Log has {total_lines} lines; only first {max_lines} lines were analyzed.")
        lines = all_lines[:max_lines]
    else:
        lines = all_lines

    level_counts: Counter[str] = Counter()
    module_counts: Counter[str] = Counter()
    parsed_lines = 0
    unparsed_lines = 0
    cycles: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line_no, line in enumerate(lines, 1):
        entry = _parse_line(line, line_no)
        if not entry:
            unparsed_lines += 1
            continue
        entry["source_log_path"] = str(log_path)
        entry["source_log_name"] = log_path.name
        parsed_lines += 1
        level_counts[entry["level"]] += 1
        module_counts[entry["module"]] += 1

        message = entry["message"]
        message_low = message.lower()
        module = entry["module"]
        is_timer = module == "planningComponent.cpp:44" and "executing timer task (100ms)" in message_low
        if is_timer:
            if current:
                cycles.append(_finalize_cycle(current))
            current = {
                "index": len(cycles) + 1,
                "start_entry": entry,
                "start_ts": entry["timestamp"],
                "replan_values": [],
                "replan_evidence": [],
                "fork_times": [],
                "fork_evidence": [],
                "path_sizes": [],
                "path_size_evidence": [],
                "trajectory_segments": [],
                "trajectory_evidence": [],
                "plan_finished_count": 0,
                "plan_finished_evidence": [],
                "collision_pass_count": 0,
                "collision_fail_count": 0,
                "collision_evidence": [],
                "points": {},
                "point_evidence": [],
                "source_log_path": str(log_path),
                "source_log_name": log_path.name,
            }
            continue

        if current is None:
            continue

        if match := _REPLAN_RE.search(message):
            current["replan_values"].append(int(match.group(1)))
            current["replan_evidence"].append(entry)
        if match := _FORK_TIME_RE.search(message):
            current["fork_times"].append(int(match.group(1)))
            current["fork_evidence"].append(entry)
        if match := _PATH_SIZE_RE.search(message):
            current["path_sizes"].append(int(match.group(1)))
            current["path_size_evidence"].append(entry)
        if match := _TRAJ_SEG_RE.search(message):
            current["trajectory_segments"].append(int(match.group(1)))
            current["trajectory_evidence"].append(entry)

        if "plan finished" in message_low:
            current["plan_finished_count"] += 1
            current["plan_finished_evidence"].append(entry)
        if "collision check pass" in message_low:
            current["collision_pass_count"] += 1
            current["collision_evidence"].append(entry)
        if "collision check fail" in message_low or ("collision" in message_low and "fail" in message_low):
            current["collision_fail_count"] += 1
            current["collision_evidence"].append(entry)

        if module == "planningComponent.cpp:330" and "decplan output" in message_low:
            for point in _POINT_RE.finditer(message):
                idx = int(point.group("idx"))
                current["points"][idx] = {
                    "idx": idx,
                    "x_mm": float(point.group("x")),
                    "y_mm": float(point.group("y")),
                    "yaw_deg": float(point.group("yaw")),
                    "curv": float(point.group("curv")),
                }
            if current["points"]:
                current["point_evidence"].append(entry)

    if current:
        cycles.append(_finalize_cycle(current))

    if unparsed_lines > 0:
        parse_warnings.append(f"Skipped {unparsed_lines} lines that did not match expected log format.")

    return ParsedPlanningLog(
        log_path=log_path,
        source_log_paths=[log_path],
        lines=lines,
        total_lines=total_lines,
        null_byte_count=null_byte_count,
        parse_warnings=parse_warnings,
        parsed_lines=parsed_lines,
        unparsed_lines=unparsed_lines,
        level_counts=level_counts,
        module_counts=module_counts,
        cycles=cycles,
    )


def parse_planning_log_file(log_path: Path, max_lines: int) -> ParsedPlanningLog:
    return _parse_single_planning_log_file(log_path, max_lines)


def parse_planning_log_files(log_paths: list[Path], max_lines: int) -> ParsedPlanningLog:
    if not log_paths:
        raise ValueError("log_paths must not be empty")

    merged_lines: list[str] = []
    parse_warnings: list[str] = []
    level_counts: Counter[str] = Counter()
    module_counts: Counter[str] = Counter()
    cycles: list[dict[str, Any]] = []
    total_lines = 0
    null_byte_count = 0
    parsed_lines = 0
    unparsed_lines = 0
    consumed_lines = 0

    for idx, log_path in enumerate(log_paths):
        remaining_lines = max_lines - consumed_lines
        if remaining_lines <= 0:
            parse_warnings.append(
                f"Merged log set reached max_lines={max_lines}; skipped remaining {len(log_paths) - idx} file(s)."
            )
            break
        parsed = _parse_single_planning_log_file(log_path, remaining_lines)
        total_lines += parsed.total_lines
        null_byte_count += parsed.null_byte_count
        parsed_lines += parsed.parsed_lines
        unparsed_lines += parsed.unparsed_lines
        consumed_lines += len(parsed.lines)
        merged_lines.extend(parsed.lines)
        level_counts.update(parsed.level_counts)
        module_counts.update(parsed.module_counts)
        for warning in parsed.parse_warnings:
            parse_warnings.append(f"{log_path.name}: {warning}")
        for cycle in parsed.cycles:
            cycle["index"] = len(cycles) + 1
            cycle["source_log_path"] = cycle.get("source_log_path") or str(log_path)
            cycle["source_log_name"] = cycle.get("source_log_name") or log_path.name
            cycles.append(cycle)

    return ParsedPlanningLog(
        log_path=log_paths[0],
        source_log_paths=log_paths,
        lines=merged_lines,
        total_lines=total_lines,
        null_byte_count=null_byte_count,
        parse_warnings=parse_warnings,
        parsed_lines=parsed_lines,
        unparsed_lines=unparsed_lines,
        level_counts=level_counts,
        module_counts=module_counts,
        cycles=cycles,
    )
