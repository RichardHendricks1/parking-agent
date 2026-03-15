from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

FUNC_STATUS = {
    0: "NULL",
    1: "RUN",
    2: "SUSPEND",
    3: "SLEEP",
}
FUNC_STAGE = {
    0: "NULL",
    1: "SEARCH",
    2: "PARK",
}
FUNC_MODE = {
    0: "NULL",
    1: "VIS_PERP_REAR_IN",
    2: "VIS_PERP_FRONT_IN",
    3: "VIS_PARA_IN",
    4: "VIS_OBLI_REAR_IN",
    5: "VIS_OBLI_FRONT_IN",
    6: "USS_PERP_REAR_IN",
    7: "USS_PERP_FRONT_IN",
    8: "USS_PARA_IN",
    9: "USS_OBLI_REAR_IN",
    10: "USS_OBLI_FRONT_IN",
    11: "PARA_LEFT_OUT",
    12: "PARA_RIGHT_OUT",
    13: "PERP_RIGHT_FRONT_OUT",
    14: "PERP_LEFT_FRONT_OUT",
    15: "PERP_RIGHT_REAR_OUT",
    16: "PERP_LEFT_REAR_OUT",
    17: "OBLI_RIGHT_FRONT_OUT",
    18: "OBLI_LEFT_FRONT_OUT",
    19: "OBLI_RIGHT_REAR_OUT",
    20: "OBLI_LEFT_REAR_OUT",
}
GEAR = {0: "null", 1: "P", 2: "R", 3: "N", 4: "D"}
CONTROL_WORK_MODE = {0: "NULL", 1: "GLOBAL", 2: "DYNAMIC", 3: "RESERVE"}
MOVING_STATUS = {0: "MOVING", 1: "FORWARD_FAIL", 2: "BACKWARD_FAIL", 3: "DEAD_LOCK"}
STOP_REASON = {
    0x00: "NULL",
    0x01: "FRONT_ALERT",
    0x02: "REAR_ALERT",
    0x03: "LEFTSIDE_ALERT",
    0x04: "RIGHTSIDE_ALERT",
    0x05: "TARGET_CLOSING",
    0x06: "UNKNOWN_REASON",
    0x07: "MANUAL_SUSPEND",
    0x08: "APA_SUSPEND",
    0x09: "PLAN4STOP",
    0x0A: "LEFTRVW_ALERT",
    0x0B: "RIGHTRVW_ALERT",
    0x0C: "TRACKING_FINISHED",
    0x0D: "TRACK_LOSS",
    0x0E: "SCANNING_FINISHED",
    0x0F: "STANDBY",
}

_NUMBER = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_PLAN_FRAME_RE = re.compile(r"Plan Frame ID \[\s*(\d+)\s*\]")
_VALUE_PATTERNS: dict[str, tuple[re.Pattern[str], dict[int, str] | None]] = {
    "parking_function_status": (re.compile(r"Parking Function Status:\s*\[?\s*(\d+)\s*\]?"), FUNC_STATUS),
    "parking_function_stage": (re.compile(r"Parking Function Stage:\s*\[?\s*(\d+)\s*\]?"), FUNC_STAGE),
    "parking_function_mode": (re.compile(r"Parking Function Mode:\s*\[?\s*(\d+)\s*\]?"), FUNC_MODE),
    "vehicle_stop_reason": (re.compile(r"Vehicle Stop Reason:\s*\[\s*(\d+)\s*\]"), STOP_REASON),
    "control_work_mode": (re.compile(r"Control Work Mode:\s*\[\s*(\d+)\s*\]"), CONTROL_WORK_MODE),
    "vehicle_moving_status": (re.compile(r"Vehicle Moving Status:\s*\[\s*(\d+)\s*\]"), MOVING_STATUS),
    "path_current_segment_id": (re.compile(r"Path Current Segment ID:\s*\[\s*(\d+)\s*\]"), None),
    "replan_type": (re.compile(r"Replan type:\s*(\d+)"), None),
    "path_segment_target_gear": (re.compile(r"Path Segment Target Gear:\s*\[\s*(\d+)\s*\]"), GEAR),
    "vehicle_location_timestamp": (re.compile(r"Vehicle Location Time Stamp:\s*\[\s*(\d+)\s*\]"), None),
    "perception_fusion_timestamp": (re.compile(r"Perception Fusion Time Stamp:\s*\[\s*(\d+)\s*\]"), None),
}
_POSE_PATTERNS: dict[str, re.Pattern[str]] = {
    "vehicle_location": re.compile(rf"Vehicle Realtime Location: X\[\s*({_NUMBER})\s*mm\]\s*Y\[\s*({_NUMBER})\s*mm\]\s*Yaw\[\s*({_NUMBER})\s*degree\]"),
    "plan_stage_target_pose": re.compile(rf"Plan Stage Target Pose: X\[\s*({_NUMBER})\s*mm\]\s*Y\[\s*({_NUMBER})\s*mm\]\s*Yaw\[\s*({_NUMBER})\s*degree\]"),
    "plan_final_target_pose": re.compile(rf"Plan Final Target Pose: X\[\s*({_NUMBER})\s*mm\]\s*Y\[\s*({_NUMBER})\s*mm\]\s*Yaw\[\s*({_NUMBER})\s*degree\]"),
}
_TRAJECTORY_POINT_RE = re.compile(rf"No\[(\d+)\]\s*x\[\s*({_NUMBER})\s*mm\]\s*y\[\s*({_NUMBER})\s*mm\]")
_STOPPER_RE = re.compile(rf"Stopper dis record:\s*({_NUMBER})")
_FUSED_RE = re.compile(rf"Parking Space P0 & P5 from Fused Points: P0\[\s*({_NUMBER})\s*mm\s*({_NUMBER})\s*mm\]\s*P5\[\s*({_NUMBER})\s*mm\s*({_NUMBER})\s*mm\]")


def _remove_log_prefix(line: str) -> str:
    pattern = r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[\w+\] \[[^\]]+:\d+\] \[PID:\d+ TID:\d+\]\s*"
    return re.sub(pattern, "", line).strip()


def _to_float(value: str) -> float:
    return round(float(value), 3)


def _pose(x: str, y: str, yaw: str) -> dict[str, float]:
    return {"x_mm": _to_float(x), "y_mm": _to_float(y), "yaw_deg": round(float(yaw), 3)}


def _parse_named_points(line: str, labels: list[str]) -> list[dict[str, Any]] | None:
    points: list[dict[str, Any]] = []
    for label in labels:
        pattern = re.compile(rf"{label}\[\s*({_NUMBER})\s*mm(?:\s*,\s*|\s*)({_NUMBER})\s*mm\]")
        match = pattern.search(line)
        if not match:
            return None
        points.append({"label": label, "x_mm": _to_float(match.group(1)), "y_mm": _to_float(match.group(2))})
    return points


def _parse_parking_space(line: str) -> list[dict[str, Any]] | None:
    matches = re.findall(rf"P(\d)\[\s*({_NUMBER})\s*mm\s*({_NUMBER})\s*mm\]", line)
    if len(matches) < 4:
        return None
    return [
        {"label": f"P{idx}", "x_mm": _to_float(x), "y_mm": _to_float(y)}
        for idx, x, y in matches
    ]


def _parse_realtime_points(line: str) -> list[dict[str, Any]]:
    matches = re.findall(rf"p(\d)\[\s*({_NUMBER})\s*mm,\s*({_NUMBER})\s*mm\]", line)
    return [
        {"label": f"p{idx}", "x_mm": _to_float(x), "y_mm": _to_float(y)}
        for idx, x, y in matches
    ]


def _frame_template(seq: int, log_name: str) -> dict[str, Any]:
    return {
        "frame_index": seq,
        "log_name": log_name,
        "plan_frame_id": None,
        "parking_function_status": None,
        "parking_function_stage": None,
        "parking_function_mode": None,
        "vehicle_stop_reason": None,
        "control_work_mode": None,
        "vehicle_moving_status": None,
        "path_current_segment_id": None,
        "replan_type": None,
        "path_segment_target_gear": None,
        "vehicle_location_timestamp": None,
        "perception_fusion_timestamp": None,
        "vehicle_location": None,
        "plan_stage_target_pose": None,
        "plan_final_target_pose": None,
        "parking_space": None,
        "slot_corners": None,
        "target_slot_corners": None,
        "fused_p0_p5": None,
        "realtime_parkingspace": None,
        "trajectory_xy_mm": [],
        "stopper_distance_mm": None,
        "fork_star_start": None,
        "source_lines": [],
    }


def _finalize_frame(frame: dict[str, Any]) -> dict[str, Any]:
    points = frame.get("trajectory_xy_mm") or []
    if points:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[float, float]] = set()
        for point in points:
            key = (point["x_mm"], point["y_mm"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(point)
        frame["trajectory_xy_mm"] = deduped[:240]
    else:
        frame["trajectory_xy_mm"] = []
    frame["source_line_count"] = len(frame.pop("source_lines", []))
    return frame


def _vehicle_outline_points(pose: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not pose:
        return []
    vehicle_length_mm = 5260.0
    vehicle_width_mm = 1980.0
    rear_to_center_mm = 970.0
    yaw_rad = math.radians(float(pose["yaw_deg"]))
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    front = vehicle_length_mm - rear_to_center_mm
    rear = rear_to_center_mm
    half_width = vehicle_width_mm / 2.0
    profile_local = [
        (-rear, half_width),
        (front, half_width),
        (front, -half_width),
        (-rear, -half_width),
    ]
    points: list[tuple[float, float]] = []
    for local_x, local_y in profile_local:
        world_x = float(pose["x_mm"]) + local_x * cos_yaw - local_y * sin_yaw
        world_y = float(pose["y_mm"]) + local_x * sin_yaw + local_y * cos_yaw
        points.append((world_x, world_y))
    return points


def _compute_fixed_bounds_mm(frames: list[dict[str, Any]]) -> dict[str, float]:
    points: list[tuple[float, float]] = []
    for frame in frames:
        for key in ("parking_space", "slot_corners", "target_slot_corners", "fused_p0_p5", "realtime_parkingspace"):
            for point in frame.get(key) or []:
                points.append((float(point["x_mm"]), float(point["y_mm"])))
        for pose_key in ("vehicle_location", "plan_stage_target_pose", "plan_final_target_pose"):
            pose = frame.get(pose_key)
            if pose:
                points.append((float(pose["x_mm"]), float(pose["y_mm"])))
                points.extend(_vehicle_outline_points(pose))
        for point in frame.get("trajectory_xy_mm") or []:
            points.append((float(point["x_mm"]), float(point["y_mm"])))

    if not points:
        return {
            "min_x_mm": -10000.0,
            "max_x_mm": 10000.0,
            "min_y_mm": -10000.0,
            "max_y_mm": 10000.0,
        }

    plausible_points = [
        (x, y) for x, y in points if abs(x) <= 100000.0 and abs(y) <= 100000.0
    ]
    bounded_points = plausible_points or points
    xs = [x for x, _ in bounded_points]
    ys = [y for _, y in bounded_points]
    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    x_margin = max((x_max - x_min) * 0.18, 1400.0)
    y_margin = max((y_max - y_min) * 0.18, 1400.0)
    return {
        "min_x_mm": round(x_min - x_margin, 3),
        "max_x_mm": round(x_max + x_margin, 3),
        "min_y_mm": round(y_min - y_margin, 3),
        "max_y_mm": round(y_max + y_margin, 3),
    }


def extract_process_replay(log_path: Path) -> dict[str, Any]:
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    frames: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    sequence = 0
    warnings: list[str] = []

    for raw_line in lines:
        line = _remove_log_prefix(raw_line)
        if not line:
            continue

        frame_match = _PLAN_FRAME_RE.search(line)
        if frame_match:
            if current is not None:
                frames.append(_finalize_frame(current))
            current = _frame_template(sequence, log_path.name)
            current["plan_frame_id"] = int(frame_match.group(1))
            current["source_lines"].append(line)
            sequence += 1
            continue

        if current is None:
            continue
        current["source_lines"].append(line)

        for field, (pattern, labels) in _VALUE_PATTERNS.items():
            if current.get(field) is not None:
                continue
            match = pattern.search(line)
            if not match:
                continue
            raw_value = int(match.group(1))
            current[field] = {
                "value": raw_value,
                "label": labels.get(raw_value, str(raw_value)) if labels else None,
            }

        for field, pattern in _POSE_PATTERNS.items():
            if current.get(field) is not None:
                continue
            match = pattern.search(line)
            if match:
                current[field] = _pose(match.group(1), match.group(2), match.group(3))

        if current.get("parking_space") is None and "Parking Space:" in line:
            current["parking_space"] = _parse_parking_space(line)

        if current.get("slot_corners") is None and "Slot corners after coordinate conversion" in line:
            current["slot_corners"] = _parse_named_points(line, ["A", "B", "C", "D"])

        if current.get("target_slot_corners") is None and "Target Slot Corners" in line:
            current["target_slot_corners"] = _parse_named_points(line, ["A", "B", "C", "D"])

        if current.get("fused_p0_p5") is None:
            match = _FUSED_RE.search(line)
            if match:
                current["fused_p0_p5"] = [
                    {"label": "P0", "x_mm": _to_float(match.group(1)), "y_mm": _to_float(match.group(2))},
                    {"label": "P5", "x_mm": _to_float(match.group(3)), "y_mm": _to_float(match.group(4))},
                ]

        if current.get("stopper_distance_mm") is None:
            match = _STOPPER_RE.search(line)
            if match:
                current["stopper_distance_mm"] = _to_float(match.group(1))

        if current.get("fork_star_start") is None:
            if "PARA FORK STAR STARTS!" in line:
                current["fork_star_start"] = "PARA"
            elif "FORK STAR STARTS!" in line:
                current["fork_star_start"] = "PERP"

        if "Realtime updating parkingspace" in line:
            points = _parse_realtime_points(line)
            if points:
                merged = {point["label"]: point for point in (current.get("realtime_parkingspace") or [])}
                for point in points:
                    merged[point["label"]] = point
                current["realtime_parkingspace"] = [merged[key] for key in sorted(merged)]

        for idx, x, y in _TRAJECTORY_POINT_RE.findall(line):
            current["trajectory_xy_mm"].append({"idx": int(idx), "x_mm": _to_float(x), "y_mm": _to_float(y)})

    if current is not None:
        frames.append(_finalize_frame(current))

    if not frames:
        warnings.append("No process replay frames extracted from planning log.")

    fields_present: list[str] = []
    candidate_fields = [
        "parking_space",
        "slot_corners",
        "target_slot_corners",
        "vehicle_location",
        "trajectory_xy_mm",
        "plan_stage_target_pose",
        "plan_final_target_pose",
        "fused_p0_p5",
        "parking_function_status",
        "parking_function_stage",
        "parking_function_mode",
        "vehicle_stop_reason",
        "control_work_mode",
        "vehicle_moving_status",
        "path_current_segment_id",
        "replan_type",
        "path_segment_target_gear",
        "stopper_distance_mm",
        "realtime_parkingspace",
        "fork_star_start",
    ]
    for field in candidate_fields:
        if any(frame.get(field) for frame in frames):
            fields_present.append(field)

    return {
        "enabled": bool(frames),
        "frame_count": len(frames),
        "fields_present": fields_present,
        "fixed_bounds_mm": _compute_fixed_bounds_mm(frames),
        "file_boundaries": [
            {
                "filename": log_path.name,
                "start_frame_index": 0,
                "end_frame_index": max(len(frames) - 1, 0),
            }
        ] if frames else [],
        "frames": frames[:240],
        "warnings": warnings,
    }


def extract_process_replay_files(log_paths: list[Path]) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    file_boundaries: list[dict[str, Any]] = []
    warnings: list[str] = []
    fields_present: set[str] = set()

    for log_path in log_paths:
        result = extract_process_replay(log_path)
        for warning in result.get("warnings", []):
            warnings.append(f"{log_path.name}: {warning}")
        start_idx = len(frames)
        for frame in result.get("frames", []):
            item = dict(frame)
            item["frame_index"] = len(frames)
            item["log_name"] = log_path.name
            item["source_log_path"] = str(log_path)
            frames.append(item)
        if len(frames) > start_idx:
            file_boundaries.append(
                {
                    "filename": log_path.name,
                    "start_frame_index": start_idx,
                    "end_frame_index": len(frames) - 1,
                }
            )
        fields_present.update(result.get("fields_present", []))

    if not frames:
        warnings.append("No process replay frames extracted from planning logs.")

    return {
        "enabled": bool(frames),
        "frame_count": len(frames),
        "fields_present": sorted(fields_present),
        "fixed_bounds_mm": _compute_fixed_bounds_mm(frames),
        "file_boundaries": file_boundaries,
        "frames": frames[:240],
        "warnings": warnings,
    }
