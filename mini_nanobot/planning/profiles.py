from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PlanningThresholdProfile:
    name: str
    timer_interval_low_ms: float = 80.0
    timer_interval_high_ms: float = 140.0
    fork_star_time_medium_ms: int = 300
    fork_star_time_high_ms: int = 800
    path_size_min: int = 100
    yaw_jump_max_deg: float = 8.0
    curv_abs_max: float = 0.10
    curv_delta_max: float = 0.03
    replan_streak_high: int = 3
    short_path_length_m: float = 2.0
    signal_missing_ratio_high: float = 0.4
    localization_pose_jump_max_mm: float = 800.0
    localization_yaw_jump_max_deg: float = 15.0
    perception_geometry_jump_max_mm: float = 500.0
    stopper_distance_jump_max_mm: float = 400.0
    module_min_evidence_score: float = 3.0
    module_primary_margin_score: float = 2.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BUILTIN_PROFILES: dict[str, PlanningThresholdProfile] = {
    "j6b_default": PlanningThresholdProfile(name="j6b_default"),
    "conservative": PlanningThresholdProfile(
        name="conservative",
        timer_interval_low_ms=85.0,
        timer_interval_high_ms=130.0,
        fork_star_time_medium_ms=250,
        fork_star_time_high_ms=700,
        path_size_min=120,
        yaw_jump_max_deg=6.0,
        curv_abs_max=0.08,
        curv_delta_max=0.02,
        replan_streak_high=2,
        short_path_length_m=2.5,
        signal_missing_ratio_high=0.3,
        localization_pose_jump_max_mm=650.0,
        localization_yaw_jump_max_deg=12.0,
        perception_geometry_jump_max_mm=350.0,
        stopper_distance_jump_max_mm=300.0,
        module_min_evidence_score=4.0,
        module_primary_margin_score=3.0,
    ),
    "lenient": PlanningThresholdProfile(
        name="lenient",
        timer_interval_low_ms=70.0,
        timer_interval_high_ms=160.0,
        fork_star_time_medium_ms=400,
        fork_star_time_high_ms=1000,
        path_size_min=80,
        yaw_jump_max_deg=10.0,
        curv_abs_max=0.12,
        curv_delta_max=0.04,
        replan_streak_high=4,
        short_path_length_m=1.5,
        signal_missing_ratio_high=0.5,
        localization_pose_jump_max_mm=1000.0,
        localization_yaw_jump_max_deg=20.0,
        perception_geometry_jump_max_mm=700.0,
        stopper_distance_jump_max_mm=550.0,
        module_min_evidence_score=2.0,
        module_primary_margin_score=1.0,
    ),
}


def available_profile_names() -> list[str]:
    return sorted(BUILTIN_PROFILES)


def get_builtin_profile(name: str | None) -> PlanningThresholdProfile:
    key = (name or "j6b_default").strip().lower() or "j6b_default"
    if key not in BUILTIN_PROFILES:
        raise ValueError(
            f"Unknown planning profile: {name}. Available profiles: {', '.join(available_profile_names())}"
        )
    return BUILTIN_PROFILES[key]


def resolve_profile(profile: str | None = None, profile_path: str | Path | None = None) -> PlanningThresholdProfile:
    base = get_builtin_profile(profile)
    if profile_path is None:
        return base

    path = Path(profile_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"profile file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to load profile file: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("profile file must be a JSON object")

    override_base = raw.get("base_profile")
    if override_base is not None:
        base = get_builtin_profile(str(override_base))

    valid_fields = {field.name for field in PlanningThresholdProfile.__dataclass_fields__.values()}
    overrides = {k: v for k, v in raw.items() if k in valid_fields and k != "name"}
    if not overrides:
        return replace(base, name=str(raw.get("name", f"{base.name}+file")))
    return replace(base, name=str(raw.get("name", path.stem)), **overrides)
