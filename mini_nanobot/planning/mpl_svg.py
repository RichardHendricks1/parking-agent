from __future__ import annotations

import base64
import importlib.util
import io
import math
import os
import site
import sys
import tempfile
from pathlib import Path
from typing import Any


def _prepare_matplotlib_env() -> None:
    current = os.environ.get("MPLCONFIGDIR")
    if current:
        Path(current).mkdir(parents=True, exist_ok=True)
        return
    cache_dir = Path(tempfile.gettempdir()) / "mini_nanobot_mplconfig"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache_dir)


def _ensure_matplotlib_importable() -> None:
    if importlib.util.find_spec("matplotlib") is not None:
        return

    candidate_paths: list[str] = []
    for getter_name in ("getusersitepackages", "getsitepackages"):
        getter = getattr(site, getter_name, None)
        if not callable(getter):
            continue
        try:
            value = getter()
        except Exception:
            continue
        if isinstance(value, str):
            candidate_paths.append(value)
        else:
            candidate_paths.extend(str(item) for item in value)

    for raw_path in candidate_paths:
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.exists():
            continue
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.append(path_str)


def _svg_data_uri(fig: Any, plt: Any) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    payload = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{payload}"


def _vehicle_model_local(length: float, width: float, rear: float) -> dict[str, list[Any]]:
    front = length - rear
    half_width = width / 2.0
    wheel_length = min(length * 0.18, 780.0)
    wheel_width = min(width * 0.12, 235.0)
    wheel_inset = half_width + wheel_width * 0.1

    def wheel(center_x: float, side: float) -> list[tuple[float, float]]:
        center_y = side * wheel_inset
        half_len = wheel_length / 2.0
        half_wheel = wheel_width / 2.0
        return [
            (center_x - half_len, center_y - half_wheel),
            (center_x + half_len, center_y - half_wheel),
            (center_x + half_len, center_y + half_wheel),
            (center_x - half_len, center_y + half_wheel),
        ]

    return {
        "outline": [
            (-rear, half_width),
            (front, half_width),
            (front, -half_width),
            (-rear, -half_width),
        ],
        "wheels": [
            wheel(-rear * 0.18, 1.0),
            wheel(-rear * 0.18, -1.0),
            wheel(front * 0.42, 1.0),
            wheel(front * 0.42, -1.0),
        ],
    }


def _transform_local_world(pose: dict[str, Any], points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    yaw = math.radians(float(pose.get("yaw_deg", 0.0)))
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    transformed: list[tuple[float, float]] = []
    for lx, ly in points:
        wx = float(pose["x_mm"]) + lx * cos_yaw - ly * sin_yaw
        wy = float(pose["y_mm"]) + lx * sin_yaw + ly * cos_yaw
        transformed.append((wx / 1000.0, wy / 1000.0))
    return transformed


def _transform_local_px(pose: dict[str, Any], points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    theta = math.radians(float(pose.get("yaw_deg", 0.0)))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    transformed: list[tuple[float, float]] = []
    for lx, ly in points:
        px = float(pose["x_px"]) + lx * cos_t - ly * sin_t
        py = float(pose["y_px"]) + lx * sin_t + ly * cos_t
        transformed.append((px, py))
    return transformed


def _vehicle_outline_world(
    pose: dict[str, Any] | None,
    *,
    length_mm: float = 5260.0,
    width_mm: float = 1980.0,
    rear_to_center_mm: float = 970.0,
) -> list[tuple[float, float]]:
    if not pose:
        return []
    model = _vehicle_model_local(length_mm, width_mm, rear_to_center_mm)
    return _transform_local_world(pose, model["outline"])


def _vehicle_outline_px(
    pose: dict[str, Any] | None,
    *,
    resolution_mm: float,
    length_mm: float = 5250.0,
    width_mm: float = 2000.0,
    rear_axle_to_rear_mm: float = 1134.0,
) -> list[tuple[float, float]]:
    if not pose:
        return []
    model = _vehicle_model_local(length_mm / resolution_mm, width_mm / resolution_mm, rear_axle_to_rear_mm / resolution_mm)
    return _transform_local_px(pose, model["outline"])


def _vehicle_geometry_world(
    pose: dict[str, Any] | None,
    *,
    length_mm: float = 5260.0,
    width_mm: float = 1980.0,
    rear_to_center_mm: float = 970.0,
) -> dict[str, Any] | None:
    if not pose:
        return None
    model = _vehicle_model_local(length_mm, width_mm, rear_to_center_mm)
    return {
        "outline": _transform_local_world(pose, model["outline"]),
        "wheels": [_transform_local_world(pose, wheel) for wheel in model["wheels"]],
    }


def _vehicle_geometry_px(
    pose: dict[str, Any] | None,
    *,
    resolution_mm: float,
    length_mm: float = 5250.0,
    width_mm: float = 2000.0,
    rear_axle_to_rear_mm: float = 1134.0,
) -> dict[str, Any] | None:
    if not pose:
        return None
    model = _vehicle_model_local(length_mm / resolution_mm, width_mm / resolution_mm, rear_axle_to_rear_mm / resolution_mm)
    return {
        "outline": _transform_local_px(pose, model["outline"]),
        "wheels": [_transform_local_px(pose, wheel) for wheel in model["wheels"]],
    }


def _trajectory_box_px(
    pose: dict[str, Any],
    *,
    resolution_mm: float,
    length_mm: float = 5200.0,
    width_mm: float = 2000.0,
    rear_axle_to_rear_mm: float = 1000.0,
) -> list[tuple[float, float]]:
    theta = math.radians(float(pose.get("yaw_deg", 0.0)))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    rear = rear_axle_to_rear_mm / resolution_mm
    front = (length_mm - rear_axle_to_rear_mm) / resolution_mm
    half_width = (width_mm / resolution_mm) / 2.0
    corners_local = [
        (-rear, -half_width),
        (front, -half_width),
        (front, half_width),
        (-rear, half_width),
    ]
    corners: list[tuple[float, float]] = []
    for lx, ly in corners_local:
        px = float(pose["x_px"]) + lx * cos_t - ly * sin_t
        py = float(pose["y_px"]) + lx * sin_t + ly * cos_t
        corners.append((px, py))
    return corners


def _label_text(point: dict[str, Any] | None) -> str:
    if not point:
        return ""
    label = str(point.get("label", ""))
    return label.replace("_abs", "")


def _enum_label(value: Any) -> str:
    if not isinstance(value, dict):
        return "-"
    label = value.get("label")
    if label not in (None, ""):
        return str(label)
    raw = value.get("value")
    return "-" if raw in (None, "") else str(raw)


def _render_process_frame(frame: dict[str, Any], fixed_bounds_mm: dict[str, float], *, plt: Any, patches: Any) -> str:
    fig, ax = plt.subplots(figsize=(10.8, 9.8))
    fig.patch.set_facecolor("#f8fbff")
    ax.set_facecolor("#ffffff")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(fixed_bounds_mm["min_x_mm"] / 1000.0, fixed_bounds_mm["max_x_mm"] / 1000.0)
    ax.set_ylim(fixed_bounds_mm["min_y_mm"] / 1000.0, fixed_bounds_mm["max_y_mm"] / 1000.0)
    ax.grid(True, color="#dbe8f8", linewidth=0.8, alpha=0.9)
    ax.set_title(f"Planning Process Replay · Frame {frame.get('plan_frame_id', frame.get('frame_index', 0))}", fontsize=12)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")

    def draw_polygon(points: list[dict[str, Any]] | None, *, edge: str, face: str, alpha: float, linewidth: float) -> None:
        if not points or len(points) < 2:
            return
        xy = [(float(point["x_mm"]) / 1000.0, float(point["y_mm"]) / 1000.0) for point in points]
        patch = patches.Polygon(xy, closed=True, edgecolor=edge, facecolor=face, alpha=alpha, linewidth=linewidth)
        ax.add_patch(patch)

    draw_polygon(frame.get("parking_space"), edge="#1f77cf", face="#9dd0ff", alpha=0.12, linewidth=2.0)
    draw_polygon(frame.get("slot_corners"), edge="#0c9c86", face="#9de7dd", alpha=0.18, linewidth=2.0)
    draw_polygon(frame.get("target_slot_corners"), edge="#de7f10", face="#ffd89f", alpha=0.14, linewidth=1.8)

    for points, color in (
        (frame.get("fused_p0_p5"), "#c84c47"),
        (frame.get("realtime_parkingspace"), "#6583a7"),
    ):
        if not points:
            continue
        xs = [float(point["x_mm"]) / 1000.0 for point in points]
        ys = [float(point["y_mm"]) / 1000.0 for point in points]
        ax.scatter(xs, ys, c=color, s=22, zorder=4)
        for point in points:
            ax.text(
                float(point["x_mm"]) / 1000.0 + 0.05,
                float(point["y_mm"]) / 1000.0 + 0.05,
                _label_text(point),
                fontsize=8,
                color=color,
            )

    trajectory = frame.get("trajectory_xy_mm") or []
    if trajectory:
        xs = [float(point["x_mm"]) / 1000.0 for point in trajectory]
        ys = [float(point["y_mm"]) / 1000.0 for point in trajectory]
        ax.plot(xs, ys, color="#1185ff", linewidth=2.7, alpha=0.95, zorder=3)
        ax.scatter([xs[0]], [ys[0]], c="#15a26e", s=34, zorder=5)
        ax.scatter([xs[-1]], [ys[-1]], c="#d43f3a", s=34, zorder=5)

    for pose, stroke, fill, label in (
        (frame.get("vehicle_location"), "#7b5cff", "#c7b8ff", "vehicle"),
        (frame.get("plan_stage_target_pose"), "#ff8c37", "#ffd3b0", "stage"),
        (frame.get("plan_final_target_pose"), "#d43f3a", "#f6b9b7", "final"),
    ):
        geom = _vehicle_geometry_world(pose)
        if geom:
            ax.add_patch(
                patches.Polygon(
                    geom["outline"],
                    closed=True,
                    edgecolor=stroke,
                    facecolor=fill,
                    alpha=0.3,
                    linewidth=2.2,
                    zorder=6,
                    joinstyle="round",
                )
            )
            for wheel in geom["wheels"]:
                ax.add_patch(patches.Polygon(wheel, closed=True, edgecolor="#0b1220", facecolor="#111827", alpha=0.92, linewidth=0.9, zorder=7))
            rear_x = float(pose["x_mm"]) / 1000.0
            rear_y = float(pose["y_mm"]) / 1000.0
            theta = math.radians(float(pose.get("yaw_deg", 0.0)))
            ax.scatter([rear_x], [rear_y], c=stroke, s=28, zorder=8)
            ax.arrow(rear_x, rear_y, math.cos(theta) * 0.55, math.sin(theta) * 0.55, head_width=0.16, head_length=0.22, fc=stroke, ec=stroke, linewidth=1.9, zorder=9)
            ax.text(
                rear_x + 0.05,
                rear_y + 0.05,
                label,
                fontsize=8,
                color=stroke,
                weight="bold",
            )

    text_lines = [
        f"mode: {_enum_label(frame.get('parking_function_mode'))}",
        f"stage: {_enum_label(frame.get('parking_function_stage'))}",
        f"replan: {_enum_label(frame.get('replan_type'))}",
        f"stop: {_enum_label(frame.get('vehicle_stop_reason'))}",
    ]
    ax.text(
        0.01,
        0.99,
        "\n".join(text_lines),
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=8.5,
        color="#19324d",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "#ffffff", "edgecolor": "#dbe8f8", "alpha": 0.95},
    )

    return _svg_data_uri(fig, plt)


def _render_grid_frame(frame: dict[str, Any], *, plt: Any, patches: Any, np: Any) -> str:
    grid_size = int(frame.get("grid_size") or 512)
    resolution_mm = float(frame.get("resolution_mm_per_cell") or 100.0)
    fig, ax = plt.subplots(figsize=(10.8, 10.4))
    fig.patch.set_facecolor("#f8fbff")
    ax.set_facecolor("#ffffff")

    grid_b64 = str(frame.get("grid_b64") or "")
    if grid_b64:
        grid = np.frombuffer(base64.b64decode(grid_b64), dtype=np.uint8).reshape((grid_size, grid_size))
        ax.imshow(grid, cmap="gray", vmin=0, vmax=255, origin="lower", interpolation="nearest")

    ticks = list(range(0, grid_size, 10))
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    labels = [f"{int(tick * resolution_mm / 1000)}m" if tick % 50 == 0 else "" for tick in ticks]
    ax.set_xticklabels(labels, fontsize=6)
    ax.set_yticklabels(labels, fontsize=6)
    ax.grid(True, alpha=0.3, color="blue", linewidth=0.5)
    ax.set_xlim(-0.5, grid_size - 0.5)
    ax.set_ylim(-0.5, grid_size - 0.5)
    ax.set_title("World Editor", fontsize=12)

    base_polygon = frame.get("base_polygon_pixel") or []
    if len(base_polygon) >= 3:
        xy = [(float(point["x_px"]), float(point["y_px"])) for point in base_polygon]
        ax.add_patch(patches.Polygon(xy, closed=True, edgecolor="#0f7dcf", facecolor="#9dd0ff", alpha=0.12, linewidth=1.8))

    slot_points = frame.get("slot_points_pixel") or []
    if len(slot_points) >= 4:
        slot_xy = [(float(point["x_px"]), float(point["y_px"])) for point in slot_points]
        ax.add_patch(patches.Polygon(slot_xy, closed=True, edgecolor="red", facecolor="yellow", alpha=0.3, linewidth=2.0, zorder=10))
        ax.plot([p[0] for p in slot_xy] + [slot_xy[0][0]], [p[1] for p in slot_xy] + [slot_xy[0][1]], color="red", linewidth=2.0, zorder=11)
        point_colors = ["red", "green", "blue", "orange"]
        for idx, point in enumerate(slot_points[:4]):
            px = float(point["x_px"])
            py = float(point["y_px"])
            label = _label_text(point) or chr(65 + idx)
            ax.scatter([px], [py], c=point_colors[idx], s=42, zorder=12)
            ax.text(
                px + 2,
                py + 2,
                label,
                fontsize=10,
                color=point_colors[idx],
                weight="bold",
                bbox={"boxstyle": "round,pad=0.25", "facecolor": "#ffffff", "alpha": 0.75},
                zorder=13,
            )

    for pose, is_ego in (
        (frame.get("ego_pose_pixel"), True),
        (frame.get("target_pose_pixel"), False),
    ):
        geom = _vehicle_geometry_px(pose, resolution_mm=resolution_mm)
        if not geom:
            continue
        edge_color = "lime" if is_ego else "red"
        face_color = "lime" if is_ego else "red"
        label = "START" if is_ego else "GOAL"
        label_text_color = "black" if is_ego else "white"
        ax.add_patch(
            patches.Polygon(
                geom["outline"],
                closed=True,
                edgecolor=edge_color,
                facecolor=face_color,
                alpha=0.38,
                linewidth=2.5,
                zorder=15,
                joinstyle="round",
            )
        )
        for wheel in geom["wheels"]:
            ax.add_patch(patches.Polygon(wheel, closed=True, edgecolor="#0b1220", facecolor="#111827", alpha=0.95, linewidth=0.9, zorder=16))
        rear_x = float(pose["x_px"])
        rear_y = float(pose["y_px"])
        ax.scatter([rear_x], [rear_y], c=edge_color, s=64, zorder=17)
        ax.text(
            rear_x + 3,
            rear_y + 3,
            label,
            fontsize=9,
            color=label_text_color,
            weight="bold",
            bbox={"boxstyle": "round,pad=0.3", "facecolor": face_color, "alpha": 0.8},
            zorder=18,
        )
        theta = math.radians(float(pose.get("yaw_deg", 0.0)))
        front_dx = math.cos(theta) * 20.0
        front_dy = math.sin(theta) * 20.0
        ax.arrow(rear_x, rear_y, front_dx, front_dy, head_width=8, head_length=10, fc=edge_color, ec=edge_color, linewidth=2.0, zorder=17)

    trajectory = frame.get("trajectory_pixel") or []
    if len(trajectory) >= 2:
        xs = [float(point["x_px"]) for point in trajectory]
        ys = [float(point["y_px"]) for point in trajectory]
        ax.plot(xs, ys, "b-", linewidth=2, alpha=0.7, zorder=8)

        box_interval = max(1, len(trajectory) // 80)
        for point in trajectory[::box_interval]:
            box = _trajectory_box_px(point, resolution_mm=resolution_mm)
            ax.add_patch(patches.Polygon(box, closed=True, edgecolor="cyan", facecolor="cyan", alpha=0.15, linewidth=1.0, zorder=5))

        arrow_interval = max(1, len(trajectory) // 10)
        for point in trajectory[::arrow_interval]:
            theta = math.radians(float(point.get("yaw_deg", 0.0)))
            dx = math.cos(theta) * 1.0
            dy = math.sin(theta) * 1.0
            ax.arrow(float(point["x_px"]), float(point["y_px"]), dx, dy, head_width=2, head_length=2.5, fc="blue", ec="blue", linewidth=0.8, alpha=0.6, zorder=9)

        ax.scatter([xs[0]], [ys[0]], c="green", s=70, zorder=10)
        ax.text(xs[0] + 5, ys[0] + 5, "Start", fontsize=9, color="green", weight="bold", bbox={"boxstyle": "round,pad=0.25", "facecolor": "#ffffff", "alpha": 0.8}, zorder=11)
        ax.scatter([xs[-1]], [ys[-1]], c="red", s=70, zorder=10)
        ax.text(xs[-1] + 5, ys[-1] + 5, "End", fontsize=9, color="red", weight="bold", bbox={"boxstyle": "round,pad=0.25", "facecolor": "#ffffff", "alpha": 0.8}, zorder=11)

    return _svg_data_uri(fig, plt)


def render_svg_visualizations(*, process_replay: dict[str, Any], gridmap_view: dict[str, Any]) -> dict[str, Any]:
    _prepare_matplotlib_env()
    _ensure_matplotlib_importable()
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib import patches

    process_frames = process_replay.get("frames") or []
    fixed_bounds = process_replay.get("fixed_bounds_mm") or {
        "min_x_mm": -10000.0,
        "max_x_mm": 10000.0,
        "min_y_mm": -10000.0,
        "max_y_mm": 10000.0,
    }
    grid_frames = gridmap_view.get("frames") or []

    return {
        "backend": "matplotlib-svg",
        "processReplayFrames": [_render_process_frame(frame, fixed_bounds, plt=plt, patches=patches) for frame in process_frames],
        "gridMapFrames": [_render_grid_frame(frame, plt=plt, patches=patches, np=np) for frame in grid_frames],
    }
