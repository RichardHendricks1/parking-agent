import json
from datetime import datetime, timedelta
from pathlib import Path

from mini_nanobot.tools import AnalyzePlanningLogTool, ToolRegistry


def _ts(base: datetime, ms: int) -> str:
    dt = base + timedelta(milliseconds=ms)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _line(base: datetime, ms: int, level: str, module: str, message: str) -> str:
    return f"[{_ts(base, ms)}] [{level}] [{module}] [PID:1 TID:1] {message}\n"


def _decplan_message(points: list[tuple[int, float, float, float, float]]) -> str:
    chunks = []
    for idx, x, y, yaw, curv in points:
        chunks.append(
            f"No[{idx}] x[{x}mm] y[{y}mm] yaw[{yaw}degree] curv[{curv}mm]"
        )
    return "([DecPlan Output] " + ", ".join(chunks) + ")"


def _cycle_lines(
    base: datetime,
    start_ms: int,
    *,
    replan: int = 0,
    fork_time_ms: int = 120,
    path_size: int = 350,
    seg_count: int = 2,
    points: list[tuple[int, float, float, float, float]] | None = None,
    split_decplan: bool = False,
) -> list[str]:
    points = points or [
        (0, 8000.0, 2500.0, 182.0, -0.02),
        (1, 7600.0, 2485.0, 181.6, -0.021),
        (2, 7200.0, 2470.0, 181.2, -0.022),
        (3, 6800.0, 2450.0, 180.8, -0.023),
    ]
    lines = [
        _line(
            base,
            start_ms,
            "DEBUG",
            "planningComponent.cpp:44",
            "planningComponent: Executing timer task (100ms), thread_id = 1",
        ),
        _line(
            base,
            start_ms + 1,
            "INFO",
            "fork_star_manager.cpp:1346",
            f"[Fork STAR] Replan:{replan}, trans fix vehicle loc:(7.8, 2.5, 3.1)",
        ),
        _line(
            base,
            start_ms + 2,
            "INFO",
            "fork_star_manager.cpp:1275",
            f"[FORK STAR] FORK STAR USED TIME:{fork_time_ms} ms",
        ),
        _line(
            base,
            start_ms + 3,
            "INFO",
            "fork_star_manager.cpp:1895",
            f"[FORK STAR] OUTPUT PATH SIZE:{path_size}",
        ),
        _line(
            base,
            start_ms + 4,
            "INFO",
            "fork_star_manager.cpp:2851",
            f"[Fork Star] Converted fork_star_output to trajectory_points_partitioned_:{seg_count} segments",
        ),
    ]
    if split_decplan:
        mid = max(1, len(points) // 2)
        lines.append(
            _line(
                base,
                start_ms + 5,
                "DEBUG",
                "planningComponent.cpp:330",
                _decplan_message(points[:mid]),
            )
        )
        lines.append(
            _line(
                base,
                start_ms + 6,
                "DEBUG",
                "planningComponent.cpp:330",
                _decplan_message(points[mid:]),
            )
        )
    else:
        lines.append(
            _line(
                base,
                start_ms + 5,
                "DEBUG",
                "planningComponent.cpp:330",
                _decplan_message(points),
            )
        )
    lines.extend(
        [
            _line(
                base,
                start_ms + 7,
                "INFO",
                "path_smoother.cpp:143",
                "Path smooth collision check pass!!!!!!",
            ),
            _line(
                base,
                start_ms + 8,
                "INFO",
                "planning_process.cpp:2057",
                "Plan finished, g_last_trajectory_segment_gear 1",
            ),
        ]
    )
    return lines


def _write_log(path: Path, lines: list[str], with_null_bytes: bool = False) -> None:
    raw = "".join(lines).encode("utf-8")
    if with_null_bytes:
        raw = raw.replace(b"DecPlan", b"\x00DecPlan", 1)
    path.write_bytes(raw)


def test_analyze_planning_log_handles_null_bytes_and_extracts_cycles(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    lines = _cycle_lines(base, 0) + _cycle_lines(base, 100)
    log_path = tmp_path / "planning.log"
    _write_log(log_path, lines, with_null_bytes=True)

    result = json.loads(tool.run(log_path=str(log_path), save_report=False))
    assert result["risk_level"] in {"low", "medium", "high"}
    assert result["key_metrics"]["cycle_count"] == 2
    assert any("null bytes" in w.lower() for w in result["parse_warnings"])


def test_analyze_planning_log_parses_multiline_decplan_geometry(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    points = [
        (0, 0.0, 0.0, 180.0, 0.01),
        (1, 1000.0, 0.0, 179.0, 0.015),
        (2, 2000.0, 100.0, 177.8, 0.02),
        (3, 3000.0, 120.0, 176.5, 0.018),
    ]
    lines = _cycle_lines(base, 0, points=points, split_decplan=True) + _cycle_lines(base, 100)
    log_path = tmp_path / "planning_multiline.log"
    _write_log(log_path, lines)

    result = json.loads(tool.run(log_path=str(log_path), save_report=False))
    geom = result["key_metrics"]["geometry"]
    assert geom["point_count"]["max"] >= 4
    assert geom["path_length_m"]["max"] > 2.0
    assert geom["yaw_jump_max_deg"]["max"] > 1.0
    assert geom["curv_delta_max"]["max"] > 0.0


def test_analyze_planning_log_hits_expected_rules(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    dangerous_points = [
        (0, 0.0, 0.0, 180.0, 0.01),
        (1, 500.0, 0.0, 195.5, 0.12),
        (2, 900.0, 50.0, 196.8, 0.16),
    ]
    lines = []
    lines += _cycle_lines(
        base,
        0,
        replan=1,
        fork_time_ms=900,
        path_size=80,
        points=dangerous_points,
    )
    lines += _cycle_lines(base, 200, replan=1, points=dangerous_points)  # 200ms => timer jitter
    lines += _cycle_lines(base, 300, replan=1, points=dangerous_points)
    lines += _cycle_lines(base, 400, replan=0, points=dangerous_points)
    log_path = tmp_path / "planning_rules.log"
    _write_log(log_path, lines)

    result = json.loads(tool.run(log_path=str(log_path), focus="comprehensive", save_report=False))
    rules = {a["rule"] for a in result["top_anomalies"]}
    assert "timer_interval_range" in rules
    assert "fork_star_time" in rules
    assert "output_path_size" in rules
    assert "yaw_jump_max_deg" in rules
    assert "curvature_limits" in rules
    assert "replan_streak" in rules
    assert result["risk_level"] == "high"


def test_analyze_planning_log_writes_json_and_gui_dashboard(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    lines = _cycle_lines(base, 0) + _cycle_lines(base, 100)
    log_path = tmp_path / "planning_report.log"
    _write_log(log_path, lines)

    result = json.loads(tool.run(log_path=str(log_path)))
    report_path = result["report_path"]
    dashboard_path = result["dashboard_path"]
    assert report_path is not None
    assert dashboard_path is not None
    assert Path(report_path).exists()
    assert Path(dashboard_path).exists()

    report_obj = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert "summary" in report_obj
    assert "trajectory_preview" in report_obj
    assert len(report_obj["trajectory_preview"]) >= 1
    html = Path(dashboard_path).read_text(encoding="utf-8")
    assert "Planning Log Dashboard" in html
    assert "timerChart" in html
    assert "trajectoryCanvas" in html
    assert "trajectorySelect" in html


def test_analyze_planning_log_defaults_reports_to_log_directory(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path / "workspace")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    base = datetime(2026, 3, 4, 16, 41, 49)
    log_path = log_dir / "planning_default_dir.log"
    _write_log(log_path, _cycle_lines(base, 0) + _cycle_lines(base, 100))

    result = json.loads(tool.run(log_path=str(log_path)))

    assert result["report_path"] is not None
    assert result["dashboard_path"] is not None
    assert Path(result["report_path"]).parent == log_dir / "reports"
    assert Path(result["dashboard_path"]).parent == log_dir / "reports"


def test_analyze_planning_log_tool_registry_integration(tmp_path):
    base = datetime(2026, 3, 4, 16, 41, 49)
    lines = _cycle_lines(base, 0) + _cycle_lines(base, 100)
    log_path = tmp_path / "planning_registry.log"
    _write_log(log_path, lines)

    registry = ToolRegistry()
    registry.register(AnalyzePlanningLogTool(tmp_path))
    out = registry.execute(
        "analyze_planning_log",
        {"log_path": str(log_path), "save_report": False, "generate_dashboard": False},
    )
    result = json.loads(out)
    assert "summary" in result
    assert "top_anomalies" in result
