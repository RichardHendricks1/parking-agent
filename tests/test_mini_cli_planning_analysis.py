import json
from datetime import datetime, timedelta
from pathlib import Path

from mini_nanobot.cli import main as mini_main
from parking_judge.cli import main as parking_main


def _ts(base: datetime, ms: int) -> str:
    dt = base + timedelta(milliseconds=ms)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _line(base: datetime, ms: int, level: str, module: str, message: str) -> str:
    return f"[{_ts(base, ms)}] [{level}] [{module}] [PID:1 TID:1] {message}\n"


def _decplan_message(points: list[tuple[int, float, float, float, float]]) -> str:
    chunks = []
    for idx, x, y, yaw, curv in points:
        chunks.append(f"No[{idx}] x[{x}mm] y[{y}mm] yaw[{yaw}degree] curv[{curv}mm]")
    return "([DecPlan Output] " + ", ".join(chunks) + ")"


def _cycle_lines(base: datetime, start_ms: int) -> list[str]:
    points = [
        (0, 8000.0, 2500.0, 182.0, -0.02),
        (1, 7600.0, 2485.0, 181.6, -0.021),
        (2, 7200.0, 2470.0, 181.2, -0.022),
        (3, 6800.0, 2450.0, 180.8, -0.023),
    ]
    return [
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
            "[Fork STAR] Replan:0, trans fix vehicle loc:(7.8, 2.5, 3.1)",
        ),
        _line(
            base,
            start_ms + 2,
            "INFO",
            "fork_star_manager.cpp:1275",
            "[FORK STAR] FORK STAR USED TIME:120 ms",
        ),
        _line(
            base,
            start_ms + 3,
            "INFO",
            "fork_star_manager.cpp:1895",
            "[FORK STAR] OUTPUT PATH SIZE:350",
        ),
        _line(
            base,
            start_ms + 4,
            "INFO",
            "fork_star_manager.cpp:2851",
            "[Fork Star] Converted fork_star_output to trajectory_points_partitioned_:2 segments",
        ),
        _line(base, start_ms + 5, "DEBUG", "planningComponent.cpp:330", _decplan_message(points)),
        _line(base, start_ms + 7, "INFO", "path_smoother.cpp:143", "Path smooth collision check pass!!!!!!"),
        _line(base, start_ms + 8, "INFO", "planning_process.cpp:2057", "Plan finished, g_last_trajectory_segment_gear 1"),
    ]


def _process_frame_lines(base: datetime, start_ms: int, frame_id: int) -> list[str]:
    return [
        _line(base, start_ms + 10, "INFO", "plan_debug.cpp:10", f"Plan Frame ID [{frame_id}]"),
        _line(base, start_ms + 11, "INFO", "plan_debug.cpp:11", "Parking Function Status: [1]"),
        _line(base, start_ms + 12, "INFO", "plan_debug.cpp:12", "Parking Function Stage: [2]"),
        _line(base, start_ms + 13, "INFO", "plan_debug.cpp:13", "Parking Function Mode: [6]"),
        _line(base, start_ms + 14, "INFO", "plan_debug.cpp:14", "Vehicle Stop Reason: [9]"),
        _line(base, start_ms + 15, "INFO", "plan_debug.cpp:15", "Control Work Mode: [1]"),
        _line(base, start_ms + 16, "INFO", "plan_debug.cpp:16", "Vehicle Moving Status: [0]"),
        _line(base, start_ms + 17, "INFO", "plan_debug.cpp:17", "Path Current Segment ID: [3]"),
        _line(base, start_ms + 18, "INFO", "plan_debug.cpp:18", "Replan type: 1"),
        _line(base, start_ms + 19, "INFO", "plan_debug.cpp:19", "Path Segment Target Gear: [2]"),
        _line(base, start_ms + 20, "INFO", "plan_debug.cpp:20", f"Vehicle Location Time Stamp: [{123450 + frame_id}]"),
        _line(base, start_ms + 21, "INFO", "plan_debug.cpp:21", f"Perception Fusion Time Stamp: [{223450 + frame_id}]"),
        _line(
            base,
            start_ms + 22,
            "INFO",
            "plan_debug.cpp:22",
            f"Vehicle Realtime Location: X[{9500 - frame_id * 120}mm] Y[{2400 + frame_id * 30}mm] Yaw[{181.5 - frame_id * 0.3}degree]",
        ),
        _line(
            base,
            start_ms + 23,
            "INFO",
            "plan_debug.cpp:23",
            f"Plan Stage Target Pose: X[{9300 - frame_id * 80}mm] Y[{2200 + frame_id * 35}mm] Yaw[{180.1 - frame_id * 0.2}degree]",
        ),
        _line(
            base,
            start_ms + 24,
            "INFO",
            "plan_debug.cpp:24",
            f"Plan Final Target Pose: X[{9100 - frame_id * 70}mm] Y[{2100 + frame_id * 25}mm] Yaw[{179.5 - frame_id * 0.2}degree]",
        ),
        _line(
            base,
            start_ms + 25,
            "INFO",
            "plan_debug.cpp:25",
            "Parking Space: P0[9000 mm 2000 mm] P1[9600 mm 2000 mm] P2[9600 mm 2600 mm] P3[9000 mm 2600 mm]",
        ),
        _line(
            base,
            start_ms + 26,
            "INFO",
            "plan_debug.cpp:26",
            "Slot corners after coordinate conversion A[9000 mm, 2000 mm] B[9600 mm, 2000 mm] C[9600 mm, 2600 mm] D[9000 mm, 2600 mm]",
        ),
        _line(
            base,
            start_ms + 27,
            "INFO",
            "plan_debug.cpp:27",
            "Target Slot Corners A[8980 mm, 1980 mm] B[9580 mm, 1980 mm] C[9580 mm, 2580 mm] D[8980 mm, 2580 mm]",
        ),
        _line(
            base,
            start_ms + 28,
            "INFO",
            "plan_debug.cpp:28",
            "Parking Space P0 & P5 from Fused Points: P0[9000 mm 2000 mm] P5[9100 mm 2100 mm]",
        ),
        _line(
            base,
            start_ms + 29,
            "INFO",
            "plan_debug.cpp:29",
            "Realtime updating parkingspace p0[9000mm, 2000mm] p1[9600mm, 2000mm] p2[9600mm, 2600mm] p3[9000mm, 2600mm]",
        ),
        _line(base, start_ms + 30, "INFO", "plan_debug.cpp:30", "Stopper dis record: 320"),
        _line(base, start_ms + 31, "INFO", "plan_debug.cpp:31", "PARA FORK STAR STARTS!"),
        _line(
            base,
            start_ms + 32,
            "DEBUG",
            "planningComponent.cpp:330",
            "No[0] x[9500mm] y[2400mm], No[1] x[9380mm] y[2360mm], No[2] x[9260mm] y[2315mm], No[3] x[9140mm] y[2260mm]",
        ),
    ]


def _write_log(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8")


def _write_planner_inputs_csv(path: Path, frame_count: int = 1, grid_size: int = 512) -> None:
    lines: list[str] = []
    for frame_idx in range(frame_count):
        for row in range(grid_size):
            values = []
            for col in range(grid_size):
                if row in {180 + frame_idx * 2, 181 + frame_idx * 2} and 180 <= col <= 330:
                    values.append("180")
                elif col in {210 + frame_idx * 2, 211 + frame_idx * 2} and 180 <= row <= 320:
                    values.append("110")
                else:
                    values.append("0")
            lines.append(",".join(values))
        lines.append(f"{9500 - frame_idx * 50},{2400 + frame_idx * 20},{181.5 - frame_idx * 0.2},{123456789 + frame_idx}")
        lines.append("8800,1900,9800,1900,9800,2900,8800,2900")
        lines.append(f"{9500 - frame_idx * 50},{2400 + frame_idx * 20},{181.5 - frame_idx * 0.2}")
        lines.append(f"{9100 - frame_idx * 40},{2100 + frame_idx * 10},{179.5 - frame_idx * 0.1}")
        lines.append("9000,2000,9600,2000,9600,2600,9000,2600,8980,1980,9580,1980,9580,2580,8980,2580")
        lines.append("0,0,100,100")
        lines.append("9500,2400,181.5,9380,2360,181.0,9260,2315,180.4,9140,2260,179.8")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_root_cli_analyze_log_generates_dashboard_and_visualizations(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("mini_nanobot.cli._analysis_workspace", lambda: tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    log_path = tmp_path / "planning_visuals.log"
    lines = _cycle_lines(base, 0) + _process_frame_lines(base, 0, 1) + _cycle_lines(base, 100) + _process_frame_lines(base, 100, 2)
    _write_log(log_path, lines)
    _write_planner_inputs_csv(tmp_path / "planner_inputs.csv")

    exit_code = mini_main(
        [
            "analyze-log",
            "--log-path",
            str(log_path.resolve()),
            "--report-dir",
            str(tmp_path / "reports"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["dashboard_path"] is not None
    assert payload["report_path"] is not None
    assert Path(payload["dashboard_path"]).exists()
    assert payload["module_diagnosis"]["primary_module"] in {"planning", "localization", "perception", "unknown"}
    assert isinstance(payload["module_signals"], list)
    assert payload["visualizations"]["process_replay"]["enabled"] is True
    assert payload["visualizations"]["gridmap_view"]["enabled"] is True
    assert payload["visualizations"]["planner_inputs_csv_resolved"] == str((tmp_path / "planner_inputs.csv").resolve())
    report_obj = json.loads(Path(payload["report_path"]).read_text(encoding="utf-8"))
    preview = report_obj["dashboard_data_preview"]
    assert "analysisOverview" in preview
    assert "riskDrivers" in preview
    assert "sourceCoverage" in preview
    assert "cycleDiagnostics" in preview
    assert "moduleDiagnosis" in preview
    assert "moduleSignals" in preview
    html = Path(payload["dashboard_path"]).read_text(encoding="utf-8")
    assert "Module Diagnosis" in html
    assert "Risk Breakdown" in html
    assert "Cycle Diagnostics" in html
    assert "sourceCoverageList" in html
    assert "cycleTable" in html


def test_root_cli_batch_analyze_logs_defaults_summary_to_log_dir_reports(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("mini_nanobot.cli._analysis_workspace", lambda: tmp_path / "workspace")
    log_dir = tmp_path / "log_dir"
    log_dir.mkdir()
    base = datetime(2026, 3, 4, 16, 41, 49)
    _write_log(log_dir / "planning_a.log", _cycle_lines(base, 0) + _cycle_lines(base, 100))

    exit_code = mini_main(
        [
            "batch-analyze-logs",
            "--log-dir",
            str(log_dir.resolve()),
            "--pattern",
            "planning_*.log",
            "--no-dashboard",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["summary_path"] is not None
    assert Path(payload["summary_path"]).parent == log_dir / "reports"


def test_root_cli_analyze_log_auto_resolves_missing_directory_hint_and_merges_logs(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("mini_nanobot.cli._analysis_workspace", lambda: tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    log_dir = tmp_path / "Downloads" / "j6b_0305"
    log_dir.mkdir(parents=True)
    log_a = log_dir / "planning.log.20260305110616"
    log_b = log_dir / "planning.log.20260305110632"
    _write_log(log_a, _cycle_lines(base, 0) + _cycle_lines(base, 100))
    _write_log(log_b, _cycle_lines(base, 200) + _cycle_lines(base, 300))

    exit_code = mini_main(
        [
            "analyze-log",
            "--log-path",
            str(tmp_path / "Downloads" / "Jj6b_0305"),
            "--no-save-report",
            "--no-dashboard",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["resolved_log_paths"] == [str(log_a.resolve()), str(log_b.resolve())]
    assert payload["key_metrics"]["cycle_count"] == 4
    assert any("auto-resolved to directory" in warning for warning in payload["parse_warnings"])


def test_parking_judge_cli_alias_runs_same_analysis_entrypoint(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("mini_nanobot.cli._analysis_workspace", lambda: tmp_path)
    base = datetime(2026, 3, 4, 16, 41, 49)
    log_path = tmp_path / "planning_low_risk.log"
    _write_log(log_path, _cycle_lines(base, 0) + _cycle_lines(base, 100))

    exit_code = parking_main(
        [
            "analyze-log",
            "--log-path",
            str(log_path.resolve()),
            "--no-save-report",
            "--no-dashboard",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["risk_level"] == "low"
    assert payload["report_path"] is None
    assert payload["dashboard_path"] is None
