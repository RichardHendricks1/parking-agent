import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.planning import AnalyzePlanningLogTool
from nanobot.bus.queue import MessageBus


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


def _write_log(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8")


def test_planning_tool_pushes_report_back_to_feishu_chat(tmp_path: Path) -> None:
    sent = []

    async def _send(msg):
        sent.append(msg)

    tool = AnalyzePlanningLogTool(workspace=tmp_path, send_callback=_send)
    tool.set_context("feishu", "ou_123456")

    base = datetime(2026, 3, 4, 16, 41, 49)
    log_path = tmp_path / "planning.log"
    _write_log(log_path, _cycle_lines(base, 0) + _cycle_lines(base, 100))

    result = json.loads(asyncio.run(tool.execute(log_path=str(log_path), save_report=True, generate_dashboard=True)))

    assert result["report_path"] is not None
    assert result["dashboard_path"] is not None
    assert result["delivery"]["channel"] == "feishu"
    assert result["delivery"]["chat_id"] == "ou_123456"
    assert len(sent) == 1
    outbound = sent[0]
    assert outbound.channel == "feishu"
    assert outbound.chat_id == "ou_123456"
    assert result["report_path"] in outbound.media
    assert result["dashboard_path"] in outbound.media
    assert "Planning Log Analysis" in outbound.content
    assert "Risk:" in outbound.content


def test_planning_tool_does_not_push_when_not_in_feishu(tmp_path: Path) -> None:
    send = AsyncMock()
    tool = AnalyzePlanningLogTool(workspace=tmp_path, send_callback=send)
    tool.set_context("telegram", "12345")

    base = datetime(2026, 3, 4, 16, 41, 49)
    log_path = tmp_path / "planning.log"
    _write_log(log_path, _cycle_lines(base, 0) + _cycle_lines(base, 100))

    result = json.loads(asyncio.run(tool.execute(log_path=str(log_path), save_report=True, generate_dashboard=True)))

    assert result.get("delivery") is None
    send.assert_not_awaited()


def test_agent_loop_registers_planning_tool(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model", memory_window=10)

    assert loop.tools.has("analyze_planning_log")
