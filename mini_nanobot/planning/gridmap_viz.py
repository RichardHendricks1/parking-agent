from __future__ import annotations

import base64
import math
from pathlib import Path
from typing import Any


def _parse_number_list(line: str) -> list[float]:
    if not line.strip():
        return []
    out: list[float] = []
    for item in line.split(","):
        item = item.strip()
        if not item:
            continue
        out.append(float(item))
    return out


def _pair_points(values: list[float], labels: list[str] | None = None) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for idx in range(0, len(values) - 1, 2):
        point = {"x_mm": round(values[idx], 3), "y_mm": round(values[idx + 1], 3)}
        if labels and idx // 2 < len(labels):
            point["label"] = labels[idx // 2]
        points.append(point)
    return points


def _compact_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    last_key: tuple[float, float] | None = None
    for point in points:
        key = (float(point["x_mm"]), float(point["y_mm"]))
        if last_key == key:
            continue
        compacted.append(point)
        last_key = key
    if len(compacted) >= 2:
        first = compacted[0]
        last = compacted[-1]
        if float(first["x_mm"]) == float(last["x_mm"]) and float(first["y_mm"]) == float(last["y_mm"]):
            compacted.pop()
    return compacted


def _pose(values: list[float]) -> dict[str, float] | None:
    if len(values) < 3:
        return None
    return {"x_mm": round(values[0], 3), "y_mm": round(values[1], 3), "yaw_deg": round(values[2], 3)}


def _slot_to_gridmap_pixel(
    *,
    x_mm: float,
    y_mm: float,
    gridmap_origin: dict[str, float] | None,
    resolution_mm: float,
    grid_size: int,
) -> dict[str, float]:
    if not gridmap_origin:
        pixel_x = x_mm / resolution_mm + grid_size / 2
        pixel_y = y_mm / resolution_mm + grid_size / 2
        return {"x_px": round(pixel_x, 3), "y_px": round(pixel_y, 3)}

    dx = x_mm - float(gridmap_origin["x_mm"])
    dy = y_mm - float(gridmap_origin["y_mm"])
    theta_rad = math.radians(float(gridmap_origin["yaw_deg"]))
    cos_theta = math.cos(-theta_rad)
    sin_theta = math.sin(-theta_rad)
    rotated_x = dx * cos_theta - dy * sin_theta
    rotated_y = dx * sin_theta + dy * cos_theta
    pixel_x = rotated_x / resolution_mm + grid_size / 2
    pixel_y = rotated_y / resolution_mm + grid_size / 2
    return {"x_px": round(pixel_x, 3), "y_px": round(pixel_y, 3)}


def _point_pixels(
    points: list[dict[str, Any]],
    *,
    gridmap_origin: dict[str, float] | None,
    resolution_mm: float,
    grid_size: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for point in points:
        pixel = _slot_to_gridmap_pixel(
            x_mm=float(point["x_mm"]),
            y_mm=float(point["y_mm"]),
            gridmap_origin=gridmap_origin,
            resolution_mm=resolution_mm,
            grid_size=grid_size,
        )
        item = {"x_px": pixel["x_px"], "y_px": pixel["y_px"]}
        if "label" in point:
            item["label"] = point["label"]
        out.append(item)
    return out


def _pose_pixel(
    pose: dict[str, float] | None,
    *,
    gridmap_origin: dict[str, float] | None,
    resolution_mm: float,
    grid_size: int,
) -> dict[str, float] | None:
    if not pose:
        return None
    pixel = _slot_to_gridmap_pixel(
        x_mm=float(pose["x_mm"]),
        y_mm=float(pose["y_mm"]),
        gridmap_origin=gridmap_origin,
        resolution_mm=resolution_mm,
        grid_size=grid_size,
    )
    yaw_gridmap_deg = float(pose["yaw_deg"]) - float(gridmap_origin["yaw_deg"]) if gridmap_origin else float(pose["yaw_deg"])
    return {
        "x_px": pixel["x_px"],
        "y_px": pixel["y_px"],
        "yaw_deg": round(yaw_gridmap_deg, 3),
    }


def _grid_to_base64(grid_rows: list[list[int]]) -> str:
    payload = bytearray()
    for row in grid_rows:
        for value in row:
            payload.append(max(0, min(255, int(value))))
    return base64.b64encode(bytes(payload)).decode("ascii")


def _looks_like_grid_row(line: str, grid_size: int) -> bool:
    parts = line.split(",")
    if len(parts) < grid_size:
        return False
    sample = parts[: min(grid_size, 16)]
    try:
        for item in sample:
            int(float(item.strip() or "0"))
    except ValueError:
        return False
    return True


def _build_frame(frame_index: int, grid_rows: list[list[int]], meta_lines: list[str], resolution_mm: float) -> dict[str, Any]:
    meta = [_parse_number_list(line) for line in meta_lines]
    timestamp_line = meta[0] if len(meta) >= 1 else []
    base_polygon_line = meta[1] if len(meta) >= 2 else []
    gridmap_origin_line = meta[2] if len(meta) >= 3 else []
    target_pose_line = meta[3] if len(meta) >= 4 else []
    slot_line = meta[4] if len(meta) >= 5 else []
    trajectory_line = meta[-1] if meta else []

    timestamp_pose = None
    timestamp_ns = None
    if len(timestamp_line) >= 4:
        timestamp_pose = {"x_mm": round(timestamp_line[0], 3), "y_mm": round(timestamp_line[1], 3), "yaw_deg": round(timestamp_line[2], 3)}
        timestamp_ns = str(int(timestamp_line[3]))

    slot_points = _pair_points(slot_line[:8], ["A", "B", "C", "D"]) if len(slot_line) >= 8 else []
    slot_points_absolute_hint = _pair_points(slot_line[8:16], ["A_abs", "B_abs", "C_abs", "D_abs"]) if len(slot_line) >= 16 else []
    slot_points_transform_source = slot_points if len(slot_points) >= 4 else slot_points_absolute_hint
    trajectory_points = []
    for idx in range(0, len(trajectory_line) - 2, 3):
        trajectory_points.append(
            {
                "x_mm": round(trajectory_line[idx], 3),
                "y_mm": round(trajectory_line[idx + 1], 3),
                "yaw_deg": round(trajectory_line[idx + 2], 3),
            }
        )

    grid_size = len(grid_rows)
    gridmap_origin = _pose(gridmap_origin_line)
    ego_pose = _pose(gridmap_origin_line)
    target_pose = _pose(target_pose_line)
    base_polygon = _compact_points(_pair_points(base_polygon_line))

    trajectory_pixel = []
    for point in trajectory_points:
        pixel = _slot_to_gridmap_pixel(
            x_mm=point["x_mm"],
            y_mm=point["y_mm"],
            gridmap_origin=gridmap_origin,
            resolution_mm=resolution_mm,
            grid_size=grid_size,
        )
        yaw_gridmap_deg = point["yaw_deg"] - gridmap_origin["yaw_deg"] if gridmap_origin else point["yaw_deg"]
        trajectory_pixel.append(
            {
                "x_px": pixel["x_px"],
                "y_px": pixel["y_px"],
                "yaw_deg": round(yaw_gridmap_deg, 3),
            }
        )

    return {
        "frame_index": frame_index,
        "grid_size": grid_size,
        "resolution_mm_per_cell": resolution_mm,
        "grid_b64": _grid_to_base64(grid_rows),
        "timestamp_ns": timestamp_ns,
        "timestamp_pose": timestamp_pose,
        "base_polygon": base_polygon,
        "base_polygon_pixel": _point_pixels(
            base_polygon,
            gridmap_origin=gridmap_origin,
            resolution_mm=resolution_mm,
            grid_size=grid_size,
        ),
        "gridmap_origin": gridmap_origin,
        "ego_pose": ego_pose,
        "ego_pose_pixel": _pose_pixel(
            ego_pose,
            gridmap_origin=gridmap_origin,
            resolution_mm=resolution_mm,
            grid_size=grid_size,
        ),
        "target_pose": target_pose,
        "target_pose_pixel": _pose_pixel(
            target_pose,
            gridmap_origin=gridmap_origin,
            resolution_mm=resolution_mm,
            grid_size=grid_size,
        ),
        "slot_points": slot_points,
        "slot_points_world": slot_points_transform_source,
        "slot_points_pixel": _point_pixels(
            slot_points_transform_source,
            gridmap_origin=gridmap_origin,
            resolution_mm=resolution_mm,
            grid_size=grid_size,
        ),
        "slot_points_absolute_hint": slot_points_absolute_hint,
        "trajectory": trajectory_points,
        "trajectory_pixel": trajectory_pixel,
        "timestamp_pose_pixel": _pose_pixel(
            timestamp_pose,
            gridmap_origin=gridmap_origin,
            resolution_mm=resolution_mm,
            grid_size=grid_size,
        ),
        "meta_line_count": len(meta_lines),
    }


def extract_gridmap_view(csv_path: Path, *, grid_size: int = 512, resolution_mm_per_cell: float = 100.0) -> dict[str, Any]:
    lines = csv_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    frames: list[dict[str, Any]] = []
    warnings: list[str] = []
    idx = 0

    while idx < len(lines):
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx >= len(lines):
            break
        if idx + grid_size > len(lines):
            warnings.append(f"Incomplete gridmap frame near line {idx + 1}.")
            break
        if not _looks_like_grid_row(lines[idx], grid_size):
            warnings.append(f"planner_inputs.csv format mismatch near line {idx + 1}.")
            break

        grid_rows: list[list[int]] = []
        valid = True
        for row_idx in range(grid_size):
            row_values = lines[idx + row_idx].split(",")[:grid_size]
            try:
                grid_rows.append([int(float(item.strip() or "0")) for item in row_values])
            except ValueError:
                valid = False
                warnings.append(f"Invalid grid value near line {idx + row_idx + 1}.")
                break
        if not valid:
            break

        cursor = idx + grid_size
        meta_lines: list[str] = []
        while cursor < len(lines) and lines[cursor].strip():
            meta_lines.append(lines[cursor])
            cursor += 1

        frames.append(_build_frame(len(frames), grid_rows, meta_lines, resolution_mm_per_cell))
        idx = cursor + 1

    if not frames:
        warnings.append("No valid planner_inputs.csv frames extracted.")

    fields_present: list[str] = []
    candidate_fields = [
        "timestamp_pose",
        "base_polygon",
        "gridmap_origin",
        "ego_pose",
        "target_pose",
        "slot_points",
        "slot_points_absolute_hint",
        "trajectory",
    ]
    for field in candidate_fields:
        if any(frame.get(field) for frame in frames):
            fields_present.append(field)

    return {
        "enabled": bool(frames),
        "frame_count": len(frames),
        "grid_size": grid_size,
        "resolution_mm_per_cell": resolution_mm_per_cell,
        "fields_present": fields_present,
        "frames": frames[:24],
        "warnings": warnings,
    }
