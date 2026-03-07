"""Built-in tools and registry."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolError(RuntimeError):
    pass


@dataclass
class ToolCall:
    tool_name: str
    arguments: dict[str, Any]


class Tool:
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, **kwargs: Any) -> str:
        raise NotImplementedError


def _resolve_path(workspace: Path, path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = workspace / p
    rp = p.resolve()
    ws = workspace.resolve()
    try:
        rp.relative_to(ws)
    except ValueError as e:
        raise ToolError(f"path outside workspace: {rp}") from e
    return rp


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read UTF-8 text from a file in workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def run(self, **kwargs: Any) -> str:
        path = _resolve_path(self.workspace, kwargs["path"])
        if not path.exists():
            return f"Error: file not found: {path}"
        if not path.is_file():
            return f"Error: not a file: {path}"
        text = path.read_text(encoding="utf-8")
        max_chars = 32_000
        if len(text) > max_chars:
            return text[:max_chars] + "\n... (truncated)"
        return text


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write UTF-8 text to a file in workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def run(self, **kwargs: Any) -> str:
        path = _resolve_path(self.workspace, kwargs["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        content = kwargs["content"]
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {path}"


class ExecTool(Tool):
    name = "exec"
    description = "Run a shell command inside workspace and return output."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path, timeout: int = 20):
        self.workspace = workspace
        self.timeout = timeout

    def run(self, **kwargs: Any) -> str:
        cmd = kwargs["command"]
        blocked = ("rm -rf", "shutdown", "reboot", "mkfs", "dd if=")
        if any(x in cmd for x in blocked):
            return "Error: command blocked by guard"
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            return f"Error: command timeout after {self.timeout}s"
        out = proc.stdout or ""
        err = proc.stderr or ""
        merged = out
        if err.strip():
            merged += ("\n" if merged else "") + "STDERR:\n" + err
        if proc.returncode != 0:
            merged += ("\n" if merged else "") + f"\nExit code: {proc.returncode}"
        merged = merged.strip() or "(no output)"
        return merged[:10_000]


class AnalyzeParkingTool(Tool):
    name = "analyze_parking"
    description = (
        "Analyze a parking scenario and return structured risk, feasibility, and maneuver guidance."
    )
    parameters = {
        "type": "object",
        "properties": {
            "scenario": {
                "type": "object",
                "properties": {
                    "slot_width_m": {"type": "number"},
                    "slot_length_m": {"type": "number"},
                    "vehicle_width_m": {"type": "number"},
                    "vehicle_length_m": {"type": "number"},
                    "left_clearance_m": {"type": "number"},
                    "right_clearance_m": {"type": "number"},
                    "front_clearance_m": {"type": "number"},
                    "rear_clearance_m": {"type": "number"},
                    "speed_kmh": {"type": "number"},
                    "slope_deg": {"type": "number"},
                    "steering_angle_deg": {"type": "number"},
                    "sensor_confidence": {"type": "number"},
                    "camera_occlusion_ratio": {"type": "number"},
                    "weather": {"type": "string"},
                    "obstacles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "distance_m": {"type": "number"},
                                "relative_direction": {"type": "string"},
                            },
                            "required": ["distance_m"],
                        },
                    },
                },
                "required": [
                    "slot_width_m",
                    "slot_length_m",
                    "vehicle_width_m",
                    "vehicle_length_m",
                ],
            }
        },
        "required": ["scenario"],
    }

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _to_float(data: dict[str, Any], key: str, default: float = 0.0) -> float:
        raw = data.get(key, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def run(self, **kwargs: Any) -> str:
        scenario = kwargs.get("scenario")
        if not isinstance(scenario, dict):
            return "Error: scenario must be an object"

        slot_width = self._to_float(scenario, "slot_width_m")
        slot_length = self._to_float(scenario, "slot_length_m")
        vehicle_width = self._to_float(scenario, "vehicle_width_m")
        vehicle_length = self._to_float(scenario, "vehicle_length_m")
        if min(slot_width, slot_length, vehicle_width, vehicle_length) <= 0:
            return "Error: slot and vehicle dimensions must be positive numbers"

        width_margin = slot_width - vehicle_width
        length_margin = slot_length - vehicle_length

        left = scenario.get("left_clearance_m")
        right = scenario.get("right_clearance_m")
        front = scenario.get("front_clearance_m")
        rear = scenario.get("rear_clearance_m")
        if left is None or right is None:
            left = right = width_margin / 2
        if front is None or rear is None:
            front = rear = length_margin / 2

        left = float(left)
        right = float(right)
        front = float(front)
        rear = float(rear)

        obstacles = scenario.get("obstacles", [])
        obstacle_distances = []
        closest_obstacle = None
        for item in obstacles if isinstance(obstacles, list) else []:
            if not isinstance(item, dict):
                continue
            distance = item.get("distance_m")
            try:
                distance = float(distance)
            except (TypeError, ValueError):
                continue
            if distance < 0:
                continue
            obstacle_distances.append(distance)
            if closest_obstacle is None or distance < closest_obstacle["distance_m"]:
                closest_obstacle = {
                    "name": item.get("name", "unknown"),
                    "distance_m": round(distance, 3),
                    "relative_direction": item.get("relative_direction", "unknown"),
                }

        clearance_values = [left, right, front, rear]
        clearance_values.extend(obstacle_distances)
        min_clearance = min(clearance_values) if clearance_values else 0.0

        sensor_conf = self._clip(self._to_float(scenario, "sensor_confidence", 0.85), 0.0, 1.0)
        occlusion = self._clip(self._to_float(scenario, "camera_occlusion_ratio", 0.1), 0.0, 1.0)
        speed_kmh = max(0.0, self._to_float(scenario, "speed_kmh", 3.0))
        slope_deg = abs(self._to_float(scenario, "slope_deg", 0.0))
        steering_deg = abs(self._to_float(scenario, "steering_angle_deg", 18.0))
        weather = str(scenario.get("weather", "clear")).lower()

        # Heuristic scores (0-100). Higher is better for each sub-score.
        width_score = self._clip((width_margin / 0.8) * 100.0, 0.0, 100.0)
        length_score = self._clip((length_margin / 1.0) * 100.0, 0.0, 100.0)
        space_score = round((width_score * 0.6) + (length_score * 0.4), 1)

        speed_penalty = self._clip((speed_kmh - 2.0) * 10.0, 0.0, 40.0)
        steering_penalty = self._clip((steering_deg - 20.0) * 0.8, 0.0, 20.0)
        slope_penalty = self._clip(slope_deg * 3.0, 0.0, 20.0)
        maneuver_score = round(self._clip(100.0 - speed_penalty - steering_penalty - slope_penalty, 0.0, 100.0), 1)

        visibility_penalty = self._clip(occlusion * 50.0, 0.0, 50.0)
        sensor_penalty = self._clip((1.0 - sensor_conf) * 60.0, 0.0, 60.0)
        weather_penalty = 0.0
        if weather in {"rain", "snow", "fog", "storm"}:
            weather_penalty = 10.0
        perception_score = round(self._clip(100.0 - visibility_penalty - sensor_penalty - weather_penalty, 0.0, 100.0), 1)

        # Collision risk from minimum clearance.
        if min_clearance < 0.10:
            collision_risk = 95.0
        elif min_clearance < 0.20:
            collision_risk = 78.0
        elif min_clearance < 0.30:
            collision_risk = 60.0
        elif min_clearance < 0.45:
            collision_risk = 40.0
        else:
            collision_risk = 20.0

        risk_raw = (
            (100.0 - space_score) * 0.35
            + (100.0 - maneuver_score) * 0.20
            + (100.0 - perception_score) * 0.20
            + collision_risk * 0.25
        )
        risk_score = round(self._clip(risk_raw, 0.0, 100.0), 1)

        fit_feasible = width_margin >= 0.20 and length_margin >= 0.30 and min_clearance >= 0.10

        if risk_score >= 75 or not fit_feasible:
            risk_level = "high"
        elif risk_score >= 45:
            risk_level = "medium"
        else:
            risk_level = "low"

        recommendations = []
        if not fit_feasible:
            recommendations.append("Current slot is likely too tight; choose a larger slot if possible.")
        if speed_kmh > 3:
            recommendations.append("Reduce approach speed to <= 3 km/h before final alignment.")
        if min_clearance < 0.20:
            recommendations.append("Use multi-point adjustment; stop and re-center before final reverse.")
        if occlusion > 0.35:
            recommendations.append("Visibility is limited; rely on cross-check from all sensors before moving.")
        if sensor_conf < 0.7:
            recommendations.append("Sensor confidence is low; switch to conservative mode and increase stop checks.")
        if not recommendations:
            recommendations.append("Proceed with standard slow-speed parking, keep continuous clearance monitoring.")

        result = {
            "fit_feasible": fit_feasible,
            "risk_level": risk_level,
            "risk_score_0_to_100": risk_score,
            "scores": {
                "space_score_0_to_100": space_score,
                "maneuver_score_0_to_100": maneuver_score,
                "perception_score_0_to_100": perception_score,
            },
            "key_metrics_m": {
                "width_margin": round(width_margin, 3),
                "length_margin": round(length_margin, 3),
                "left_clearance": round(left, 3),
                "right_clearance": round(right, 3),
                "front_clearance": round(front, 3),
                "rear_clearance": round(rear, 3),
                "min_clearance": round(min_clearance, 3),
            },
            "closest_obstacle": closest_obstacle,
            "recommended_actions": recommendations,
            "summary": (
                f"Parking fit={fit_feasible}, risk={risk_level} ({risk_score}/100), "
                f"minimum clearance={round(min_clearance, 3)}m."
            ),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Error: unknown tool {name}"
        try:
            return tool.run(**args)
        except Exception as e:
            return f"Error executing {name}: {e}"


def parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
