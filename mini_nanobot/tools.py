"""Built-in tools and registry."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
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


class AnalyzePlanningLogTool(Tool):
    name = "analyze_planning_log"
    description = (
        "Analyze J6B parking planning logs with cycle segmentation, trajectory geometry checks, "
        "risk scoring, and structured report output."
    )
    parameters = {
        "type": "object",
        "properties": {
            "log_path": {"type": "string", "description": "Absolute path to planning log file."},
            "focus": {
                "type": "string",
                "enum": ["comprehensive", "safety", "stability"],
                "default": "comprehensive",
            },
            "save_report": {"type": "boolean", "default": True},
            "generate_dashboard": {"type": "boolean", "default": True},
            "report_dir": {"type": "string", "description": "Directory to save analysis JSON report."},
            "max_lines": {"type": "integer", "default": 200000},
            "evidence_limit": {"type": "integer", "default": 8},
        },
        "required": ["log_path"],
    }

    _LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<level>[A-Z]+)\]\s+\[(?P<module>[^\]]+)\](?P<rest>.*)$")
    _REPLAN_RE = re.compile(r"Replan:(\d+)")
    _FORK_TIME_RE = re.compile(r"FORK STAR USED TIME:([0-9]+)\s*ms", re.IGNORECASE)
    _PATH_SIZE_RE = re.compile(r"OUTPUT PATH SIZE:([0-9]+)", re.IGNORECASE)
    _TRAJ_SEG_RE = re.compile(r"trajectory[^\n]*?([0-9]+)\s*segments", re.IGNORECASE)
    _POINT_RE = re.compile(
        r"No\[(?P<idx>\d+)\]\s*x\[(?P<x>-?\d+(?:\.\d+)?)mm\]\s*y\[(?P<y>-?\d+(?:\.\d+)?)mm\]"
        r"\s*yaw\[(?P<yaw>-?\d+(?:\.\d+)?)degree\]\s*curv\[(?P<curv>-?\d+(?:\.\d+)?)mm\]"
    )

    def __init__(self, workspace: Path):
        self.workspace = workspace

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _to_int(raw: Any, default: int) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(raw: Any, default: bool) -> bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            low = raw.strip().lower()
            if low in {"true", "1", "yes", "y"}:
                return True
            if low in {"false", "0", "no", "n"}:
                return False
        return default

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {"high": 3, "medium": 2, "low": 1}.get(severity, 0)

    @staticmethod
    def _parse_ts(raw: str) -> datetime | None:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _stats(values: list[float], ndigits: int = 3) -> dict[str, Any]:
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

    @staticmethod
    def _angle_delta(a: float, b: float) -> float:
        diff = b - a
        while diff > 180.0:
            diff -= 360.0
        while diff < -180.0:
            diff += 360.0
        return abs(diff)

    @staticmethod
    def _safe_message(msg: str, max_len: int = 220) -> str:
        clean = msg.replace("\n", " ").replace("\r", " ")
        return clean if len(clean) <= max_len else clean[:max_len] + "..."

    def _parse_line(self, line: str, line_no: int) -> dict[str, Any] | None:
        m = self._LINE_RE.match(line.strip())
        if not m:
            return None
        rest = m.group("rest").strip()
        # Remove optional bracketed metadata blocks such as [PID:... TID:...].
        while rest.startswith("["):
            end = rest.find("]")
            if end <= 0:
                break
            rest = rest[end + 1 :].strip()

        ts_raw = m.group("ts")
        return {
            "line_no": line_no,
            "timestamp_raw": ts_raw,
            "timestamp": self._parse_ts(ts_raw),
            "level": m.group("level"),
            "module": m.group("module"),
            "message": rest,
            "raw": line,
        }

    def _build_error(self, message: str, parse_warnings: list[str] | None = None) -> str:
        payload = {
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
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _build_dashboard_html(
        self,
        *,
        log_path: Path,
        summary: str,
        risk_level: str,
        score: float,
        key_metrics: dict[str, Any],
        anomalies: list[dict[str, Any]],
        timer_intervals_ms: list[float],
        fork_times: list[int],
        cycle_preview: list[dict[str, Any]],
        trajectory_preview: list[dict[str, Any]],
    ) -> str:
        dashboard_data = {
            "timerIntervals": [round(v, 3) for v in timer_intervals_ms[:300]],
            "forkTimes": [int(v) for v in fork_times[:300]],
            "cycleIndex": [int(c["cycle_index"]) for c in cycle_preview[:200]],
            "yawJump": [float(c["yaw_jump_max_deg"]) for c in cycle_preview[:200]],
            "pathLength": [float(c["path_length_m"]) for c in cycle_preview[:200]],
            "curvAbs": [float(c["curv_abs_max"]) for c in cycle_preview[:200]],
            "trajectoryPreview": trajectory_preview[:24],
            "anomalies": [
                {
                    "rule": a.get("rule"),
                    "severity": a.get("severity"),
                    "count": a.get("count"),
                    "detail": a.get("detail"),
                }
                for a in anomalies[:30]
            ],
        }
        data_json = json.dumps(dashboard_data, ensure_ascii=False)
        summary_safe = summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        log_path_safe = str(log_path).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        log_name_safe = log_path.name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        risk_class = {"high": "risk-high", "medium": "risk-medium", "low": "risk-low"}.get(risk_level, "risk-medium")
        html_template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Planning Log Dashboard - __LOG_NAME__</title>
  <style>
    :root {{
      --bg: #eef3fb;
      --card: #ffffff;
      --text: #10233f;
      --muted: #4f6481;
      --line: #d2deef;
      --accent: #0f6bd9;
      --ok: #0f9d6a;
      --warn: #b7791f;
      --bad: #c53030;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at 8% 10%, #dbeafe 0%, rgba(219, 234, 254, 0) 38%),
        radial-gradient(circle at 90% 0%, #d1fae5 0%, rgba(209, 250, 229, 0) 30%),
        linear-gradient(160deg, #edf3fb 0%, #f8fbff 100%);
      color: var(--text);
      font-family: "Avenir Next", "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .wrap {{ max-width: 1320px; margin: 0 auto; padding: 24px 20px 30px; }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 20px 22px;
      border-radius: 18px;
      background:
        linear-gradient(130deg, rgba(15,107,217,0.10), rgba(255,255,255,0.88)),
        linear-gradient(45deg, rgba(16,35,63,0.05), rgba(16,35,63,0));
      border: 1px solid #d8e5f7;
      box-shadow: 0 14px 36px rgba(20, 56, 110, 0.12);
      margin-bottom: 14px;
    }}
    .hero h1 {{ margin: 0; font-size: 30px; letter-spacing: 0.2px; }}
    .hero .meta {{ margin-top: 6px; font-size: 13px; color: var(--muted); word-break: break-all; }}
    .hero .summary {{
      margin-top: 12px;
      color: #0f2b4f;
      background: rgba(255,255,255,0.78);
      border: 1px solid #dbe7f8;
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
      line-height: 1.5;
      max-width: 860px;
    }}
    .risk-chip {{
      align-self: flex-start;
      padding: 10px 14px;
      border-radius: 999px;
      font-size: 13px;
      color: #fff;
      font-weight: 700;
      letter-spacing: 0.3px;
      box-shadow: 0 8px 18px rgba(17, 40, 77, 0.16);
    }}
    .risk-high {{ background: linear-gradient(135deg, #c53030, #ef4444); }}
    .risk-medium {{ background: linear-gradient(135deg, #b7791f, #f59e0b); }}
    .risk-low {{ background: linear-gradient(135deg, #0f9d6a, #10b981); }}

    .grid {{ display: grid; gap: 14px; grid-template-columns: repeat(12, 1fr); margin-top: 14px; }}
    .card {{
      background: var(--card);
      border: 1px solid #dce7f6;
      border-radius: 16px;
      box-shadow: 0 10px 28px rgba(16, 44, 89, 0.08);
      padding: 14px 15px;
    }}
    .kpi {{ grid-column: span 2; min-height: 108px; }}
    .kpi.accent {{
      background: linear-gradient(135deg, #0f6bd9 0%, #2c84ea 70%);
      color: #fff;
      border-color: transparent;
    }}
    .kpi .label {{ color: var(--muted); font-size: 12px; }}
    .kpi.accent .label {{ color: rgba(255,255,255,0.82); }}
    .kpi .val {{ font-size: 26px; font-weight: 700; margin-top: 6px; }}
    .kpi .sub {{ margin-top: 6px; font-size: 11px; color: #6b7c96; }}
    .kpi.accent .sub {{ color: rgba(255,255,255,0.80); }}
    .wide {{ grid-column: span 6; min-height: 332px; }}
    .trajectory-card {{ grid-column: span 12; }}
    .full {{ grid-column: span 12; }}
    h3 {{ margin: 4px 0 10px 0; font-size: 16px; letter-spacing: 0.1px; }}
    .hint {{ margin-top: -4px; margin-bottom: 8px; color: #6b7c96; font-size: 12px; }}
    canvas {{ width: 100%; height: 250px; background: #fbfdff; border-radius: 10px; border: 1px solid #e7eef9; }}
    #trajectoryCanvas {{ height: 420px; background: linear-gradient(180deg, #fbfdff 0%, #f5f9ff 100%); }}

    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }}
    .toolbar .left {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    select {{
      border: 1px solid #d0def2;
      border-radius: 10px;
      padding: 6px 10px;
      background: #fff;
      color: #123054;
      font-weight: 500;
    }}
    .legend {{
      display: flex;
      align-items: center;
      gap: 12px;
      color: #5a6e8d;
      font-size: 12px;
    }}
    .legend .dot {{
      width: 9px;
      height: 9px;
      border-radius: 99px;
      display: inline-block;
      margin-right: 5px;
    }}

    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #edf2f7; text-align: left; padding: 8px; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 650; background: #f8fbff; }}
    .sev-high {{ color: var(--bad); font-weight: 700; }}
    .sev-medium {{ color: var(--warn); font-weight: 700; }}
    .sev-low {{ color: var(--ok); font-weight: 700; }}

    @media (max-width: 980px) {{
      .hero {{ flex-direction: column; }}
      .kpi {{ grid-column: span 6; }}
      .kpi.accent {{ grid-column: span 12; }}
      .kpi {{ grid-column: span 6; }}
      .wide {{ grid-column: span 12; }}
      #trajectoryCanvas {{ height: 320px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>Planning Log Dashboard</h1>
        <div class="meta">__LOG_PATH__</div>
        <div class="summary">__SUMMARY__</div>
      </div>
      <div class="risk-chip __RISK_CLASS__">Risk: __RISK_LEVEL__ / Score: __SCORE__</div>
    </div>

    <div class="grid">
      <div class="card kpi accent"><div class="label">Overall Risk Score</div><div class="val">__SCORE__</div><div class="sub">Focus: __FOCUS__</div></div>
      <div class="card kpi"><div class="label">Cycle Count</div><div class="val">__CYCLE_COUNT__</div><div class="sub">with points: __CYCLE_WITH_POINTS__</div></div>
      <div class="card kpi"><div class="label">Parsed Lines</div><div class="val">__PARSED_LINES__</div><div class="sub">total: __LINE_COUNT__</div></div>
      <div class="card kpi"><div class="label">Timer Jitter</div><div class="val">__TIMER_JITTER__</div><div class="sub">out of [80, 140] ms</div></div>
      <div class="card kpi"><div class="label">Replan Ratio</div><div class="val">__REPLAN_RATIO__</div><div class="sub">longest streak: __REPLAN_STREAK__</div></div>
      <div class="card kpi"><div class="label">Top Severity</div><div class="val">__HIGH_ANOMALY_COUNT__</div><div class="sub">high anomalies</div></div>

      <div class="card wide">
        <h3>Timer Interval (ms)</h3>
        <div class="hint">Planner loop interval trend with threshold lines.</div>
        <canvas id="timerChart"></canvas>
      </div>
      <div class="card wide">
        <h3>Fork Star Used Time (ms)</h3>
        <div class="hint">Runtime cost distribution by cycle.</div>
        <canvas id="forkChart"></canvas>
      </div>

      <div class="card wide">
        <h3>Yaw Jump Max per Cycle (deg)</h3>
        <div class="hint">Steering continuity risk view (threshold at 8 deg).</div>
        <canvas id="yawChart"></canvas>
      </div>
      <div class="card wide">
        <h3>Path Length / Curvature per Cycle</h3>
        <div class="hint">Composite trend for trajectory scale and curvature intensity.</div>
        <canvas id="pathChart"></canvas>
      </div>

      <div class="card trajectory-card">
        <h3>Output Trajectory Map</h3>
        <div class="toolbar">
          <div class="left">
            <label for="trajectorySelect">Cycle:</label>
            <select id="trajectorySelect"></select>
            <span id="trajectoryMeta" class="hint"></span>
          </div>
          <div class="legend">
            <span><span class="dot" style="background:#0f6bd9;"></span>selected</span>
            <span><span class="dot" style="background:#ef4444;"></span>high</span>
            <span><span class="dot" style="background:#f59e0b;"></span>medium</span>
            <span><span class="dot" style="background:#94a3b8;"></span>normal</span>
          </div>
        </div>
        <canvas id="trajectoryCanvas"></canvas>
      </div>

      <div class="card full">
        <h3>Top Anomalies</h3>
        <table id="anomalyTable">
          <thead><tr><th>Rule</th><th>Severity</th><th>Count</th><th>Detail</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </div>
<script>
const data = __DATA_JSON__;

function yScale(min, max, h, pad) {
  return (v) => {
    if (max === min) return h / 2;
    return h - pad - ((v - min) / (max - min)) * (h - pad * 2);
  };
}

function drawLine(canvasId, values, opts) {{
  const c = document.getElementById(canvasId);
  const ctx = c.getContext("2d");
  c.width = c.clientWidth * 2;
  c.height = c.clientHeight * 2;
  ctx.scale(2, 2);
  const vw = c.clientWidth, vh = c.clientHeight;
  ctx.clearRect(0, 0, vw, vh);
  if (!values || !values.length) {{
    ctx.fillStyle = "#64748b"; ctx.fillText("No data", 12, 24); return;
  }}
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = 28;
  const xStep = values.length > 1 ? (vw - pad * 2) / (values.length - 1) : 0;
  const yMap = yScale(min, max, vh, pad);

  ctx.strokeStyle = "#d9e2f0"; ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {{
    const y = pad + (i * (vh - pad * 2) / 4);
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(vw - pad, y); ctx.stroke();
  }}

  ctx.strokeStyle = opts.color || "#1f6feb";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((v, i) => {{
    const x = pad + i * xStep;
    const y = yMap(v);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }});
  ctx.stroke();

  if (opts.thresholds) {{
    opts.thresholds.forEach(t => {{
      const y = yMap(t.value);
      ctx.strokeStyle = t.color;
      ctx.setLineDash([5,4]);
      ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(vw-pad, y); ctx.stroke();
      ctx.setLineDash([]);
    }});
  }}
}}

function drawBars(canvasId, values, color) {{
  const c = document.getElementById(canvasId);
  const ctx = c.getContext("2d");
  c.width = c.clientWidth * 2;
  c.height = c.clientHeight * 2;
  ctx.scale(2, 2);
  const vw = c.clientWidth, vh = c.clientHeight;
  ctx.clearRect(0, 0, vw, vh);
  if (!values || !values.length) {{
    ctx.fillStyle = "#64748b"; ctx.fillText("No data", 12, 24); return;
  }}
  const pad = 28;
  const max = Math.max(...values, 1);
  const barW = Math.max(1, (vw - pad * 2) / values.length - 1);
  values.forEach((v, i) => {{
    const x = pad + i * (barW + 1);
    const hVal = ((v / max) * (vh - pad * 2));
    const y = vh - pad - hVal;
    ctx.fillStyle = color;
    ctx.fillRect(x, y, barW, hVal);
  }});
}}

function trajectoryColor(tag, selected) {
  if (selected) return "#0f6bd9";
  if (tag === "high") return "#ef4444";
  if (tag === "medium") return "#f59e0b";
  return "#94a3b8";
}

function drawTrajectoryMap(selectedCycleIndex) {
  const c = document.getElementById("trajectoryCanvas");
  const ctx = c.getContext("2d");
  c.width = c.clientWidth * 2;
  c.height = c.clientHeight * 2;
  ctx.scale(2, 2);
  const vw = c.clientWidth, vh = c.clientHeight;
  ctx.clearRect(0, 0, vw, vh);
  const trajectories = data.trajectoryPreview || [];
  if (!trajectories.length) {
    ctx.fillStyle = "#64748b";
    ctx.fillText("No trajectory preview data", 16, 24);
    return;
  }

  const allPts = [];
  trajectories.forEach(t => (t.points_xy_m || []).forEach(p => allPts.push(p)));
  if (!allPts.length) {
    ctx.fillStyle = "#64748b";
    ctx.fillText("No trajectory points", 16, 24);
    return;
  }

  const xs = allPts.map(p => p[0]);
  const ys = allPts.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 34;

  const scaleX = (x) => {
    if (maxX === minX) return vw / 2;
    return pad + ((x - minX) / (maxX - minX)) * (vw - pad * 2);
  };
  const scaleY = (y) => {
    if (maxY === minY) return vh / 2;
    return vh - pad - ((y - minY) / (maxY - minY)) * (vh - pad * 2);
  };

  ctx.strokeStyle = "#deebfb";
  ctx.lineWidth = 1;
  for (let i = 0; i < 6; i++) {
    const x = pad + (i * (vw - pad * 2) / 5);
    ctx.beginPath(); ctx.moveTo(x, pad); ctx.lineTo(x, vh - pad); ctx.stroke();
  }
  for (let i = 0; i < 6; i++) {
    const y = pad + (i * (vh - pad * 2) / 5);
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(vw - pad, y); ctx.stroke();
  }

  trajectories.forEach(t => {
    const pts = t.points_xy_m || [];
    if (pts.length < 2) return;
    const selected = t.cycle_index === selectedCycleIndex;
    ctx.lineWidth = selected ? 2.8 : 1.2;
    ctx.strokeStyle = trajectoryColor(t.risk_tag, selected);
    ctx.globalAlpha = selected ? 1.0 : 0.35;
    ctx.beginPath();
    pts.forEach((p, i) => {
      const x = scaleX(p[0]);
      const y = scaleY(p[1]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    if (selected) {
      const first = pts[0], last = pts[pts.length - 1];
      ctx.globalAlpha = 1.0;
      ctx.fillStyle = "#16a34a";
      ctx.beginPath(); ctx.arc(scaleX(first[0]), scaleY(first[1]), 3.8, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#dc2626";
      ctx.beginPath(); ctx.arc(scaleX(last[0]), scaleY(last[1]), 3.8, 0, Math.PI * 2); ctx.fill();
    }
  });
  ctx.globalAlpha = 1.0;
}

function initTrajectorySelector() {
  const trajectories = data.trajectoryPreview || [];
  const sel = document.getElementById("trajectorySelect");
  const meta = document.getElementById("trajectoryMeta");
  if (!trajectories.length) {
    sel.innerHTML = "<option>No trajectory</option>";
    drawTrajectoryMap(-1);
    return;
  }
  sel.innerHTML = trajectories.map((t, i) =>
    `<option value="${t.cycle_index}" ${i === 0 ? "selected" : ""}>Cycle ${t.cycle_index} (${t.risk_tag})</option>`
  ).join("");

  const refresh = () => {
    const target = Number(sel.value);
    const item = trajectories.find(t => t.cycle_index === target) || trajectories[0];
    meta.textContent = `points=${item.point_count}, len=${item.path_length_m}m, yawJump=${item.yaw_jump_max_deg}, curv=${item.curv_abs_max}`;
    drawTrajectoryMap(item.cycle_index);
  };
  sel.addEventListener("change", refresh);
  refresh();
}

drawLine("timerChart", data.timerIntervals, {{
  color: "#2563eb",
  thresholds: [{{value: 80, color: "#f59e0b"}}, {{value: 140, color: "#ef4444"}}]
}});
drawBars("forkChart", data.forkTimes, "#0ea5e9");
drawLine("yawChart", data.yawJump, {{
  color: "#f97316",
  thresholds: [{{value: 8, color: "#ef4444"}}]
}});
drawLine("pathChart", data.pathLength.map((v, i) => v + (data.curvAbs[i] || 0) * 20), {{
  color: "#10b981"
}});
initTrajectorySelector();

const tbody = document.querySelector("#anomalyTable tbody");
data.anomalies.forEach(a => {{
  const tr = document.createElement("tr");
  tr.innerHTML = `<td>${{a.rule || ""}}</td>
                  <td class="sev-${{a.severity || "low"}}">${{a.severity || ""}}</td>
                  <td>${{a.count ?? ""}}</td>
                  <td>${{a.detail || ""}}</td>`;
  tbody.appendChild(tr);
}});
</script>
</body>
</html>
"""
        replacements = {
            "__LOG_NAME__": log_name_safe,
            "__LOG_PATH__": log_path_safe,
            "__SUMMARY__": summary_safe,
            "__RISK_CLASS__": risk_class,
            "__RISK_LEVEL__": risk_level,
            "__SCORE__": str(score),
            "__FOCUS__": str(key_metrics.get("risk_breakdown", {}).get("focus", "comprehensive")),
            "__CYCLE_COUNT__": str(key_metrics.get("cycle_count", 0)),
            "__CYCLE_WITH_POINTS__": str(key_metrics.get("cycle_with_points_count", 0)),
            "__PARSED_LINES__": str(key_metrics.get("parsed_line_count", 0)),
            "__LINE_COUNT__": str(key_metrics.get("line_count", 0)),
            "__TIMER_JITTER__": str(key_metrics.get("timer_jitter_count", 0)),
            "__REPLAN_RATIO__": str(key_metrics.get("replan_ratio", 0.0)),
            "__REPLAN_STREAK__": str(key_metrics.get("longest_replan_streak", 0)),
            "__HIGH_ANOMALY_COUNT__": str(sum(1 for a in anomalies if a.get("severity") == "high")),
            "__DATA_JSON__": data_json,
        }
        out = html_template
        for key, value in replacements.items():
            out = out.replace(key, value)
        return out

    def _finalize_cycle(self, cycle: dict[str, Any]) -> dict[str, Any]:
        points = [cycle["points"][i] for i in sorted(cycle["points"])]
        point_count = len(points)
        path_length_m = 0.0
        yaw_jump_max_deg = 0.0
        curv_abs_max = 0.0
        curv_delta_max = 0.0
        if point_count >= 1:
            curv_abs_max = max(abs(p["curv"]) for p in points)
        if point_count >= 2:
            for i in range(1, point_count):
                prev = points[i - 1]
                curr = points[i]
                dx = curr["x_mm"] - prev["x_mm"]
                dy = curr["y_mm"] - prev["y_mm"]
                path_length_m += math.sqrt(dx * dx + dy * dy) / 1000.0
                yaw_jump_max_deg = max(yaw_jump_max_deg, self._angle_delta(prev["yaw_deg"], curr["yaw_deg"]))
                curv_delta_max = max(curv_delta_max, abs(curr["curv"] - prev["curv"]))

        cycle["point_count"] = point_count
        cycle["path_length_m"] = path_length_m
        cycle["yaw_jump_max_deg"] = yaw_jump_max_deg
        cycle["curv_abs_max"] = curv_abs_max
        cycle["curv_delta_max"] = curv_delta_max
        if cycle["replan_values"]:
            cycle["replan"] = 1 if any(v == 1 for v in cycle["replan_values"]) else 0
        else:
            cycle["replan"] = None
        return cycle

    def run(self, **kwargs: Any) -> str:
        try:
            return self._run_impl(**kwargs)
        except Exception as e:
            return self._build_error(f"Unexpected analyzer error: {e}")

    def _run_impl(self, **kwargs: Any) -> str:
        parse_warnings: list[str] = []
        log_path_raw = kwargs.get("log_path", "")
        log_path = Path(str(log_path_raw)).expanduser()
        if not str(log_path_raw).strip():
            return self._build_error("Missing required argument: log_path")
        if not log_path.is_absolute():
            return self._build_error("log_path must be an absolute path")
        if not log_path.exists() or not log_path.is_file():
            return self._build_error(f"log file not found: {log_path}")

        focus = str(kwargs.get("focus", "comprehensive")).strip().lower()
        if focus not in {"comprehensive", "safety", "stability"}:
            focus = "comprehensive"

        save_report = self._to_bool(kwargs.get("save_report", True), True)
        generate_dashboard = self._to_bool(kwargs.get("generate_dashboard", True), True)
        max_lines = max(1000, self._to_int(kwargs.get("max_lines", 200000), 200000))
        evidence_limit = self._clip(float(self._to_int(kwargs.get("evidence_limit", 8), 8)), 1.0, 20.0)
        evidence_limit = int(evidence_limit)

        report_dir_raw = kwargs.get("report_dir")
        if report_dir_raw:
            report_dir = Path(str(report_dir_raw)).expanduser()
            if not report_dir.is_absolute():
                report_dir = self.workspace / report_dir
        else:
            report_dir = self.workspace / "reports"

        try:
            data = log_path.read_bytes()
        except Exception as e:
            return self._build_error(f"failed to read log file: {e}")

        null_byte_count = data.count(b"\x00")
        if null_byte_count:
            parse_warnings.append(f"Removed {null_byte_count} null bytes from log before parsing.")
            data = data.replace(b"\x00", b"")

        text = data.decode("utf-8", errors="ignore")
        all_lines = text.splitlines()
        total_lines = len(all_lines)
        if total_lines > max_lines:
            parse_warnings.append(
                f"Log has {total_lines} lines; only first {max_lines} lines were analyzed."
            )
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
            entry = self._parse_line(line, line_no)
            if not entry:
                unparsed_lines += 1
                continue
            parsed_lines += 1
            level_counts[entry["level"]] += 1
            module_counts[entry["module"]] += 1

            module = entry["module"]
            message = entry["message"]
            message_low = message.lower()

            is_timer = (
                module == "planningComponent.cpp:44"
                and "executing timer task (100ms)" in message_low
            )
            if is_timer:
                if current:
                    cycles.append(self._finalize_cycle(current))
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
                }
                continue

            if current is None:
                continue

            if m := self._REPLAN_RE.search(message):
                val = int(m.group(1))
                current["replan_values"].append(val)
                current["replan_evidence"].append(entry)

            if m := self._FORK_TIME_RE.search(message):
                val = int(m.group(1))
                current["fork_times"].append(val)
                current["fork_evidence"].append(entry)

            if m := self._PATH_SIZE_RE.search(message):
                val = int(m.group(1))
                current["path_sizes"].append(val)
                current["path_size_evidence"].append(entry)

            if m := self._TRAJ_SEG_RE.search(message):
                val = int(m.group(1))
                current["trajectory_segments"].append(val)
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
                for point in self._POINT_RE.finditer(message):
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
            cycles.append(self._finalize_cycle(current))

        if parsed_lines == 0:
            return self._build_error("Log format mismatch: no parseable lines found.", parse_warnings)

        if unparsed_lines > 0:
            parse_warnings.append(f"Skipped {unparsed_lines} lines that did not match expected log format.")

        if not cycles:
            return self._build_error("Log format mismatch: no planning cycles found.", parse_warnings)

        cycle_with_points = [c for c in cycles if c["point_count"] > 0]
        if not cycle_with_points:
            return self._build_error("No valid DecPlan trajectory points parsed from log.", parse_warnings)

        timer_intervals_ms: list[float] = []
        timer_jitter_evidence: list[dict[str, Any]] = []
        for i in range(1, len(cycles)):
            a = cycles[i - 1]["start_ts"]
            b = cycles[i]["start_ts"]
            if not a or not b:
                continue
            delta_ms = (b - a).total_seconds() * 1000.0
            timer_intervals_ms.append(delta_ms)
            if delta_ms < 80.0 or delta_ms > 140.0:
                timer_jitter_evidence.append(cycles[i]["start_entry"])

        fork_times = [t for c in cycles for t in c["fork_times"]]
        path_sizes = [s for c in cycles for s in c["path_sizes"]]
        traj_segments = [s for c in cycles for s in c["trajectory_segments"]]
        point_counts = [c["point_count"] for c in cycle_with_points]
        path_lengths = [c["path_length_m"] for c in cycle_with_points]
        yaw_jumps = [c["yaw_jump_max_deg"] for c in cycle_with_points]
        curv_abs = [c["curv_abs_max"] for c in cycle_with_points]
        curv_delta = [c["curv_delta_max"] for c in cycle_with_points]

        anomalies: list[dict[str, Any]] = []

        def evidence(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = []
            for e in entries[:evidence_limit]:
                out.append(
                    {
                        "line_no": e.get("line_no"),
                        "timestamp": e.get("timestamp_raw"),
                        "module": e.get("module"),
                        "message": self._safe_message(e.get("message", "")),
                    }
                )
            return out

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
                        f"{jitter_count} timer intervals outside [80,140]ms "
                        f"(ratio={round(ratio, 3)})."
                    ),
                    "evidence": evidence(timer_jitter_evidence),
                }
            )

        fork_high = []
        fork_medium = []
        for c in cycles:
            for idx, t in enumerate(c["fork_times"]):
                ev = c["fork_evidence"][min(idx, len(c["fork_evidence"]) - 1)]
                if t > 800:
                    fork_high.append(ev)
                elif t > 300:
                    fork_medium.append(ev)
        if fork_high:
            anomalies.append(
                {
                    "rule": "fork_star_time",
                    "severity": "high",
                    "category": "stability",
                    "count": len(fork_high),
                    "detail": f"{len(fork_high)} cycles with FORK STAR USED TIME > 800ms.",
                    "evidence": evidence(fork_high),
                }
            )
        elif fork_medium:
            anomalies.append(
                {
                    "rule": "fork_star_time",
                    "severity": "medium",
                    "category": "stability",
                    "count": len(fork_medium),
                    "detail": f"{len(fork_medium)} cycles with FORK STAR USED TIME > 300ms.",
                    "evidence": evidence(fork_medium),
                }
            )

        low_path_evidence = []
        for c in cycles:
            for idx, size in enumerate(c["path_sizes"]):
                if size < 100:
                    low_path_evidence.append(c["path_size_evidence"][min(idx, len(c["path_size_evidence"]) - 1)])
        if low_path_evidence:
            anomalies.append(
                {
                    "rule": "output_path_size",
                    "severity": "medium",
                    "category": "safety",
                    "count": len(low_path_evidence),
                    "detail": f"{len(low_path_evidence)} path outputs with size < 100.",
                    "evidence": evidence(low_path_evidence),
                }
            )

        yaw_evidence = [c["start_entry"] for c in cycle_with_points if c["yaw_jump_max_deg"] > 8.0]
        if yaw_evidence:
            anomalies.append(
                {
                    "rule": "yaw_jump_max_deg",
                    "severity": "high",
                    "category": "safety",
                    "count": len(yaw_evidence),
                    "detail": f"{len(yaw_evidence)} cycles with yaw_jump_max_deg > 8.",
                    "evidence": evidence(yaw_evidence),
                }
            )

        curv_evidence = [
            c["start_entry"]
            for c in cycle_with_points
            if c["curv_abs_max"] > 0.10 or c["curv_delta_max"] > 0.03
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
                        "(|curv|>0.10 or delta>0.03)."
                    ),
                    "evidence": evidence(curv_evidence),
                }
            )

        longest_replan_streak = 0
        streak = 0
        streak_end = -1
        for i, c in enumerate(cycles):
            if c["replan"] == 1:
                streak += 1
                if streak > longest_replan_streak:
                    longest_replan_streak = streak
                    streak_end = i
            else:
                streak = 0
        if longest_replan_streak >= 3:
            start = streak_end - longest_replan_streak + 1
            streak_evidence = [cycles[i]["start_entry"] for i in range(start, streak_end + 1)]
            anomalies.append(
                {
                    "rule": "replan_streak",
                    "severity": "high",
                    "category": "stability",
                    "count": longest_replan_streak,
                    "detail": f"Consecutive Replan=1 streak detected: {longest_replan_streak} cycles.",
                    "evidence": evidence(streak_evidence),
                }
            )

        collision_fail_entries = [
            ev
            for c in cycles
            for ev in c["collision_evidence"]
            if "fail" in ev["message"].lower()
        ]
        if collision_fail_entries:
            anomalies.append(
                {
                    "rule": "collision_check_fail",
                    "severity": "high",
                    "category": "safety",
                    "count": len(collision_fail_entries),
                    "detail": f"{len(collision_fail_entries)} collision check failure logs found.",
                    "evidence": evidence(collision_fail_entries),
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
        if longest_replan_streak >= 3:
            stability_risk += 25.0
            safety_risk += 10.0
        if not timer_intervals_ms:
            stability_risk += 10.0

        safety_risk = self._clip(safety_risk, 0.0, 100.0)
        stability_risk = self._clip(stability_risk, 0.0, 100.0)

        if focus == "safety":
            score = safety_risk
        elif focus == "stability":
            score = stability_risk
        else:
            score = (0.6 * safety_risk) + (0.4 * stability_risk)
        score = round(self._clip(score, 0.0, 100.0), 1)

        anomalies_sorted = sorted(
            anomalies,
            key=lambda x: (self._severity_rank(x["severity"]), x.get("count", 0)),
            reverse=True,
        )

        high_count = sum(1 for a in anomalies_sorted if a["severity"] == "high")
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

        summary = (
            f"Analyzed {len(lines)} lines in {len(cycles)} planning cycles. "
            f"Risk={risk_level} ({score}/100), high anomalies={high_count}."
        )

        cycle_replan_flags = [c["replan"] for c in cycles if c["replan"] is not None]
        replan_ratio = (
            round(sum(cycle_replan_flags) / len(cycle_replan_flags), 3)
            if cycle_replan_flags
            else 0.0
        )

        def downsample_points(points: list[dict[str, Any]], max_points: int = 220) -> list[list[float]]:
            if not points:
                return []
            if len(points) <= max_points:
                return [[round(p["x_mm"] / 1000.0, 3), round(p["y_mm"] / 1000.0, 3)] for p in points]
            result = []
            for i in range(max_points):
                pos = round(i * (len(points) - 1) / (max_points - 1))
                p = points[int(pos)]
                result.append([round(p["x_mm"] / 1000.0, 3), round(p["y_mm"] / 1000.0, 3)])
            return result

        def cycle_alert_score(c: dict[str, Any]) -> int:
            score_c = 0
            if c["yaw_jump_max_deg"] > 8.0:
                score_c += 2
            if c["curv_abs_max"] > 0.10 or c["curv_delta_max"] > 0.03:
                score_c += 2
            if c.get("replan") == 1:
                score_c += 1
            if c["path_length_m"] < 2.0:
                score_c += 1
            return score_c

        ranked_cycles = sorted(
            cycle_with_points,
            key=lambda c: (
                cycle_alert_score(c),
                c["curv_abs_max"],
                c["yaw_jump_max_deg"],
                c["path_length_m"],
            ),
            reverse=True,
        )
        selected_cycles: list[dict[str, Any]] = []
        selected_ids: set[int] = set()
        for c in ranked_cycles[:10]:
            cid = int(c["index"])
            selected_cycles.append(c)
            selected_ids.add(cid)
        for c in cycle_with_points[:5]:
            cid = int(c["index"])
            if cid in selected_ids:
                continue
            selected_cycles.append(c)
            selected_ids.add(cid)
            if len(selected_cycles) >= 14:
                break

        trajectory_preview = []
        for c in selected_cycles[:14]:
            points_sorted = [c["points"][i] for i in sorted(c["points"])]
            alert_score = cycle_alert_score(c)
            if alert_score >= 3:
                risk_tag = "high"
            elif alert_score >= 1:
                risk_tag = "medium"
            else:
                risk_tag = "normal"
            trajectory_preview.append(
                {
                    "cycle_index": c["index"],
                    "timestamp": c["start_entry"]["timestamp_raw"],
                    "point_count": c["point_count"],
                    "path_length_m": round(c["path_length_m"], 3),
                    "yaw_jump_max_deg": round(c["yaw_jump_max_deg"], 3),
                    "curv_abs_max": round(c["curv_abs_max"], 5),
                    "risk_tag": risk_tag,
                    "alert_score": alert_score,
                    "points_xy_m": downsample_points(points_sorted),
                }
            )

        key_metrics = {
            "line_count": len(lines),
            "parsed_line_count": parsed_lines,
            "cycle_count": len(cycles),
            "cycle_with_points_count": len(cycle_with_points),
            "trajectory_preview_count": len(trajectory_preview),
            "level_counts": dict(level_counts),
            "top_modules": [
                {"module": name, "count": count}
                for name, count in module_counts.most_common(12)
            ],
            "timer_interval_ms": self._stats(timer_intervals_ms, ndigits=2),
            "timer_jitter_count": jitter_count,
            "fork_star_time_ms": self._stats([float(v) for v in fork_times], ndigits=2),
            "replan_ratio": replan_ratio,
            "longest_replan_streak": longest_replan_streak,
            "path_size": self._stats([float(v) for v in path_sizes], ndigits=2),
            "trajectory_segments": self._stats([float(v) for v in traj_segments], ndigits=2),
            "geometry": {
                "point_count": self._stats([float(v) for v in point_counts], ndigits=2),
                "path_length_m": self._stats(path_lengths, ndigits=3),
                "yaw_jump_max_deg": self._stats(yaw_jumps, ndigits=3),
                "curv_abs_max": self._stats(curv_abs, ndigits=5),
                "curv_delta_max": self._stats(curv_delta, ndigits=5),
            },
            "risk_breakdown": {
                "focus": focus,
                "safety_risk_0_to_100": round(safety_risk, 1),
                "stability_risk_0_to_100": round(stability_risk, 1),
            },
        }

        report_path: str | None = None
        dashboard_path: str | None = None
        full_report = {
            "summary": summary,
            "risk_level": risk_level,
            "score_0_to_100": score,
            "focus": focus,
            "input": {
                "log_path": str(log_path),
                "analyzed_lines": len(lines),
                "total_lines": total_lines,
                "null_bytes_removed": null_byte_count,
            },
            "key_metrics": key_metrics,
            "top_anomalies": anomalies_sorted,
            "parse_warnings": parse_warnings,
            "trajectory_preview": trajectory_preview,
            "cycle_metrics_preview": [
                {
                    "cycle_index": c["index"],
                    "timestamp": c["start_entry"]["timestamp_raw"],
                    "point_count": c["point_count"],
                    "path_length_m": round(c["path_length_m"], 3),
                    "yaw_jump_max_deg": round(c["yaw_jump_max_deg"], 3),
                    "curv_abs_max": round(c["curv_abs_max"], 5),
                    "curv_delta_max": round(c["curv_delta_max"], 5),
                    "replan": c["replan"],
                    "fork_star_time_ms": c["fork_times"][0] if c["fork_times"] else None,
                    "path_size": c["path_sizes"][0] if c["path_sizes"] else None,
                }
                for c in cycles[:120]
            ],
        }

        if save_report:
            try:
                report_dir.mkdir(parents=True, exist_ok=True)
                out_name = f"{log_path.name}.analysis.json"
                out_path = report_dir / out_name
                out_path.write_text(json.dumps(full_report, ensure_ascii=False, indent=2), encoding="utf-8")
                report_path = str(out_path)

                if generate_dashboard:
                    html = self._build_dashboard_html(
                        log_path=log_path,
                        summary=summary,
                        risk_level=risk_level,
                        score=score,
                        key_metrics=key_metrics,
                        anomalies=anomalies_sorted,
                        timer_intervals_ms=timer_intervals_ms,
                        fork_times=fork_times,
                        cycle_preview=full_report["cycle_metrics_preview"],
                        trajectory_preview=trajectory_preview,
                    )
                    dashboard_file = report_dir / f"{log_path.name}.analysis.html"
                    dashboard_file.write_text(html, encoding="utf-8")
                    dashboard_path = str(dashboard_file)
            except Exception as e:
                parse_warnings.append(f"Failed to write report file: {e}")

        payload = {
            "summary": summary,
            "risk_level": risk_level,
            "score_0_to_100": score,
            "key_metrics": key_metrics,
            "top_anomalies": anomalies_sorted,
            "report_path": report_path,
            "dashboard_path": dashboard_path,
            "parse_warnings": parse_warnings,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


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
