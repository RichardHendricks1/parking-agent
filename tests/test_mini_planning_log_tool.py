import json
import os
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


def _process_frame_lines(
    base: datetime,
    start_ms: int,
    *,
    frame_id: int,
    stop_reason: int = 9,
    vehicle_x_mm: float = 9500.0,
    vehicle_y_mm: float = 2400.0,
    vehicle_yaw_deg: float = 181.5,
    geometry_offset_mm: float = 0.0,
    stopper_distance_mm: float = 320.0,
    include_vehicle_location: bool = True,
    include_vehicle_location_timestamp: bool = True,
    include_perception_fusion_timestamp: bool = True,
    include_geometry: bool = True,
) -> list[str]:
    lines = [
        _line(base, start_ms + 10, "INFO", "plan_debug.cpp:10", f"Plan Frame ID [{frame_id}]"),
        _line(base, start_ms + 11, "INFO", "plan_debug.cpp:11", "Parking Function Status: [1]"),
        _line(base, start_ms + 12, "INFO", "plan_debug.cpp:12", "Parking Function Stage: [2]"),
        _line(base, start_ms + 13, "INFO", "plan_debug.cpp:13", "Parking Function Mode: [6]"),
        _line(base, start_ms + 14, "INFO", "plan_debug.cpp:14", f"Vehicle Stop Reason: [{stop_reason}]"),
        _line(base, start_ms + 15, "INFO", "plan_debug.cpp:15", "Control Work Mode: [1]"),
        _line(base, start_ms + 16, "INFO", "plan_debug.cpp:16", "Vehicle Moving Status: [0]"),
        _line(base, start_ms + 17, "INFO", "plan_debug.cpp:17", "Path Current Segment ID: [3]"),
        _line(base, start_ms + 18, "INFO", "plan_debug.cpp:18", "Replan type: 1"),
        _line(base, start_ms + 19, "INFO", "plan_debug.cpp:19", "Path Segment Target Gear: [2]"),
    ]
    if include_vehicle_location_timestamp:
        lines.append(
            _line(
                base,
                start_ms + 20,
                "INFO",
                "plan_debug.cpp:20",
                f"Vehicle Location Time Stamp: [{123450 + frame_id}]",
            )
        )
    if include_perception_fusion_timestamp:
        lines.append(
            _line(
                base,
                start_ms + 21,
                "INFO",
                "plan_debug.cpp:21",
                f"Perception Fusion Time Stamp: [{223450 + frame_id}]",
            )
        )
    if include_vehicle_location:
        lines.append(
            _line(
                base,
                start_ms + 22,
                "INFO",
                "plan_debug.cpp:22",
                (
                    f"Vehicle Realtime Location: X[{vehicle_x_mm}mm] Y[{vehicle_y_mm}mm] "
                    f"Yaw[{vehicle_yaw_deg}degree]"
                ),
            )
        )
    lines.extend(
        [
            _line(
                base,
                start_ms + 23,
                "INFO",
                "plan_debug.cpp:23",
                (
                    f"Plan Stage Target Pose: X[{vehicle_x_mm - 120.0}mm] Y[{vehicle_y_mm - 180.0}mm] "
                    f"Yaw[{vehicle_yaw_deg - 1.0}degree]"
                ),
            ),
            _line(
                base,
                start_ms + 24,
                "INFO",
                "plan_debug.cpp:24",
                (
                    f"Plan Final Target Pose: X[{vehicle_x_mm - 300.0}mm] Y[{vehicle_y_mm - 280.0}mm] "
                    f"Yaw[{vehicle_yaw_deg - 2.0}degree]"
                ),
            ),
        ]
    )
    if include_geometry:
        p0_x = 9000.0 + geometry_offset_mm
        p1_x = 9600.0 + geometry_offset_mm
        p2_x = 9600.0 + geometry_offset_mm
        p3_x = 9000.0 + geometry_offset_mm
        p0_y = 2000.0
        p1_y = 2000.0
        p2_y = 2600.0
        p3_y = 2600.0
        lines.extend(
            [
                _line(
                    base,
                    start_ms + 25,
                    "INFO",
                    "plan_debug.cpp:25",
                    (
                        f"Parking Space: P0[{p0_x} mm {p0_y} mm] P1[{p1_x} mm {p1_y} mm] "
                        f"P2[{p2_x} mm {p2_y} mm] P3[{p3_x} mm {p3_y} mm]"
                    ),
                ),
                _line(
                    base,
                    start_ms + 26,
                    "INFO",
                    "plan_debug.cpp:26",
                    (
                        f"Slot corners after coordinate conversion A[{p0_x} mm, {p0_y} mm] "
                        f"B[{p1_x} mm, {p1_y} mm] C[{p2_x} mm, {p2_y} mm] D[{p3_x} mm, {p3_y} mm]"
                    ),
                ),
                _line(
                    base,
                    start_ms + 27,
                    "INFO",
                    "plan_debug.cpp:27",
                    (
                        f"Target Slot Corners A[{p0_x - 20.0} mm, {p0_y - 20.0} mm] "
                        f"B[{p1_x - 20.0} mm, {p1_y - 20.0} mm] C[{p2_x - 20.0} mm, {p2_y - 20.0} mm] "
                        f"D[{p3_x - 20.0} mm, {p3_y - 20.0} mm]"
                    ),
                ),
                _line(
                    base,
                    start_ms + 28,
                    "INFO",
                    "plan_debug.cpp:28",
                    (
                        f"Parking Space P0 & P5 from Fused Points: P0[{p0_x} mm {p0_y} mm] "
                        f"P5[{p0_x + 100.0} mm {p0_y + 100.0} mm]"
                    ),
                ),
                _line(
                    base,
                    start_ms + 29,
                    "INFO",
                    "plan_debug.cpp:29",
                    (
                        f"Realtime updating parkingspace p0[{p0_x}mm, {p0_y}mm] p1[{p1_x}mm, {p1_y}mm] "
                        f"p2[{p2_x}mm, {p2_y}mm] p3[{p3_x}mm, {p3_y}mm]"
                    ),
                ),
            ]
        )
    lines.extend(
        [
            _line(base, start_ms + 30, "INFO", "plan_debug.cpp:30", f"Stopper dis record: {stopper_distance_mm}"),
            _line(base, start_ms + 31, "INFO", "plan_debug.cpp:31", "PARA FORK STAR STARTS!"),
            _line(
                base,
                start_ms + 32,
                "DEBUG",
                "planningComponent.cpp:330",
                "No[0] x[9500mm] y[2400mm], No[1] x[9380mm] y[2360mm], No[2] x[9260mm] y[2315mm], No[3] x[9140mm] y[2260mm]",
            ),
        ]
    )
    return lines


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
    assert result["module_diagnosis"]["primary_module"] == "planning"
    assert result["module_diagnosis"]["module_scores"]["planning"] >= 3
    assert all(signal["module"] == "planning" for signal in result["module_signals"])


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
    assert "module_diagnosis" in report_obj
    assert "module_signals" in report_obj
    assert "analysisOverview" in report_obj["dashboard_data_preview"]
    assert "riskDrivers" in report_obj["dashboard_data_preview"]
    assert "sourceCoverage" in report_obj["dashboard_data_preview"]
    assert "cycleDiagnostics" in report_obj["dashboard_data_preview"]
    assert "moduleDiagnosis" in report_obj["dashboard_data_preview"]
    assert "moduleSignals" in report_obj["dashboard_data_preview"]
    assert "primary_module" in result["module_diagnosis"]
    assert "module_scores" in result["module_diagnosis"]
    assert isinstance(result["module_signals"], list)
    html = Path(dashboard_path).read_text(encoding="utf-8")
    assert "Planning Log Dashboard" in html
    assert "timerChart" in html
    assert "trajectoryCanvas" in html
    assert "trajectorySelect" in html
    assert "Module Diagnosis" in html
    assert "Risk Breakdown" in html
    assert "Cycle Diagnostics" in html
    assert "cycleTable" in html


def test_analyze_planning_log_prefers_localization_module_when_track_loss_appears(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    lines = _cycle_lines(base, 0) + _process_frame_lines(base, 0, frame_id=1, stop_reason=13)
    log_path = tmp_path / "planning_localization.log"
    _write_log(log_path, lines)

    result = json.loads(tool.run(log_path=str(log_path), save_report=False, generate_dashboard=False))

    assert result["module_diagnosis"]["primary_module"] == "localization"
    assert result["module_diagnosis"]["confidence_0_to_1"] >= 1.0
    assert any(signal["signal"] == "vehicle_stop_reason_track_loss" for signal in result["module_signals"])


def test_analyze_planning_log_prefers_perception_module_when_geometry_jumps_with_stable_pose(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    lines = []
    lines += _cycle_lines(base, 0)
    lines += _process_frame_lines(
        base,
        0,
        frame_id=1,
        vehicle_x_mm=9500.0,
        vehicle_y_mm=2400.0,
        vehicle_yaw_deg=181.5,
        geometry_offset_mm=0.0,
    )
    lines += _cycle_lines(base, 100)
    lines += _process_frame_lines(
        base,
        100,
        frame_id=2,
        vehicle_x_mm=9520.0,
        vehicle_y_mm=2410.0,
        vehicle_yaw_deg=181.8,
        geometry_offset_mm=900.0,
    )
    log_path = tmp_path / "planning_perception.log"
    _write_log(log_path, lines)

    result = json.loads(tool.run(log_path=str(log_path), save_report=False, generate_dashboard=False))

    assert result["module_diagnosis"]["primary_module"] == "perception"
    assert any(signal["signal"] == "parking_space_geometry_jump" for signal in result["module_signals"])
    assert result["module_diagnosis"]["module_scores"]["perception"] >= 3


def test_analyze_planning_log_returns_unknown_module_when_evidence_is_weak(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    lines = _cycle_lines(base, 0) + _cycle_lines(base, 100)
    log_path = tmp_path / "planning_unknown.log"
    _write_log(log_path, lines)

    result = json.loads(tool.run(log_path=str(log_path), save_report=False, generate_dashboard=False))

    assert result["module_diagnosis"]["primary_module"] == "unknown"
    assert result["module_diagnosis"]["module_scores"] == {
        "planning": 0,
        "localization": 0,
        "perception": 0,
    }
    assert result["module_diagnosis"]["limitations"][0] == "Based on planning.log heuristics only."


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


def test_analyze_planning_log_merges_all_logs_from_directory(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    log_dir = tmp_path / "Downloads" / "j6b_0305"
    log_dir.mkdir(parents=True)
    older_log = log_dir / "planning.log.20260305110616"
    newer_log = log_dir / "planning.log.20260305110632"
    _write_log(older_log, _cycle_lines(base, 0) + _cycle_lines(base, 100))
    _write_log(newer_log, _cycle_lines(base, 0) + _cycle_lines(base, 100))
    os.utime(older_log, (1_700_000_000, 1_700_000_000))
    os.utime(newer_log, (1_700_000_100, 1_700_000_100))

    result = json.loads(tool.run(log_path=str(log_dir), save_report=False, generate_dashboard=False))

    assert result["resolved_log_paths"] == [str(older_log.resolve()), str(newer_log.resolve())]
    assert result["key_metrics"]["cycle_count"] == 4
    assert any("merged 2 candidate log(s)" in warning for warning in result["parse_warnings"])


def test_analyze_planning_log_directory_merge_ignores_reports_subdir(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    log_dir = tmp_path / "Downloads" / "j6b_0305"
    reports_dir = log_dir / "reports"
    log_dir.mkdir(parents=True)
    reports_dir.mkdir()
    log_a = log_dir / "planning.log.20260305110616"
    log_b = log_dir / "planning.log.20260305110632"
    noise = reports_dir / "planning.log.20260305110632.analysis.json"
    _write_log(log_a, _cycle_lines(base, 0) + _cycle_lines(base, 100))
    _write_log(log_b, _cycle_lines(base, 200) + _cycle_lines(base, 300))
    noise.write_text("not a log", encoding="utf-8")

    result = json.loads(tool.run(log_path=str(log_dir), save_report=False, generate_dashboard=False))

    assert result["resolved_log_paths"] == [str(log_a.resolve()), str(log_b.resolve())]
    assert all("analysis.json" not in path for path in result["resolved_log_paths"])


def test_analyze_planning_log_auto_resolves_missing_directory_hint_and_merges_logs(tmp_path):
    tool = AnalyzePlanningLogTool(tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    log_dir = tmp_path / "Downloads" / "j6b_0305"
    log_dir.mkdir(parents=True)
    log_a = log_dir / "planning.log.20260305110616"
    log_b = log_dir / "planning.log.20260305110632"
    _write_log(log_a, _cycle_lines(base, 0) + _cycle_lines(base, 100))
    _write_log(log_b, _cycle_lines(base, 200) + _cycle_lines(base, 300))

    result = json.loads(
        tool.run(
            log_path=str(tmp_path / "Downloads" / "Jj6b_0305"),
            save_report=False,
            generate_dashboard=False,
        )
    )

    assert result["resolved_log_paths"] == [str(log_a.resolve()), str(log_b.resolve())]
    assert result["key_metrics"]["cycle_count"] == 4
    assert any("auto-resolved to directory" in warning for warning in result["parse_warnings"])


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
