"""Planning analysis tool wrapper for the full nanobot agent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from mini_nanobot.planning import analyze_planning_log

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class AnalyzePlanningLogTool(Tool):
    """Async wrapper around the mini_nanobot planning analyzer."""

    def __init__(
        self,
        workspace: Path,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ) -> None:
        self._workspace = workspace
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id

    @property
    def name(self) -> str:
        return "analyze_planning_log"

    @property
    def description(self) -> str:
        return (
            "Analyze J6B parking planning logs, score planning risk, and produce a JSON report plus "
            "an interactive HTML dashboard. When invoked from a Feishu chat, completed reports are "
            "also sent back to the current conversation."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "log_path": {
                    "type": "string",
                    "description": (
                        "Planning log file path, containing directory, or approximate planning.log hint. "
                        "Nearby planning.log* files are auto-resolved when possible."
                    ),
                },
                "log_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of planning log file paths or searchable hints to merge in one run.",
                },
                "focus": {
                    "type": "string",
                    "enum": ["comprehensive", "safety", "stability"],
                    "default": "comprehensive",
                },
                "save_report": {"type": "boolean", "default": True},
                "generate_dashboard": {"type": "boolean", "default": True},
                "report_dir": {"type": "string", "description": "Optional directory for the saved JSON/HTML report."},
                "max_lines": {"type": "integer", "default": 200000},
                "evidence_limit": {"type": "integer", "default": 8},
                "profile": {
                    "type": "string",
                    "enum": ["conservative", "j6b_default", "lenient"],
                    "default": "j6b_default",
                },
                "profile_path": {
                    "type": "string",
                    "description": "Optional JSON file with threshold overrides based on a built-in profile.",
                },
                "planner_inputs_csv_path": {
                    "type": "string",
                    "description": "Optional planner_inputs.csv path. If omitted, auto-detect next to the log file.",
                },
                "generate_process_replay": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to render the planning process replay section in the dashboard.",
                },
                "generate_gridmap_view": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to render the planner_inputs.csv gridmap section in the dashboard.",
                },
            },
            "required": [],
        }

    def set_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id

    async def execute(self, **kwargs: Any) -> str:
        try:
            payload = await asyncio.to_thread(
                analyze_planning_log,
                workspace=self._workspace,
                **kwargs,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "summary": "Planning log analysis failed.",
                    "risk_level": "unknown",
                    "score_0_to_100": 0.0,
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )

        delivery = await self._deliver_to_current_feishu_chat(payload)
        if delivery:
            payload["delivery"] = delivery
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def _deliver_to_current_feishu_chat(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self._send_callback or self._default_channel != "feishu" or not self._default_chat_id:
            return None

        report_path = payload.get("report_path")
        dashboard_path = payload.get("dashboard_path")
        attachments = [path for path in [report_path, dashboard_path] if isinstance(path, str) and Path(path).exists()]

        summary = str(payload.get("summary") or "Planning log analysis complete.")
        key_metrics = payload.get("key_metrics") or {}
        focus = payload.get("focus") or key_metrics.get("risk_breakdown", {}).get("focus", "comprehensive")
        profile = payload.get("profile") or "j6b_default"
        risk_level = str(payload.get("risk_level") or "unknown")
        score = payload.get("score_0_to_100")
        cycle_count = key_metrics.get("cycle_count", 0)
        high_anomalies = sum(1 for item in payload.get("top_anomalies", []) if item.get("severity") == "high")
        lines = [
            "# Planning Log Analysis",
            f"- Risk: **{risk_level}** ({score}/100)",
            f"- Focus / Profile: `{focus}` / `{profile}`",
            f"- Cycles: `{cycle_count}`",
            f"- High anomalies: `{high_anomalies}`",
            "",
            summary,
        ]
        if attachments:
            names = ", ".join(Path(path).name for path in attachments)
            lines.extend(["", f"Attachments: `{names}`"])

        outbound = OutboundMessage(
            channel=self._default_channel,
            chat_id=self._default_chat_id,
            content="\n".join(lines),
            reply_to=self._default_message_id,
            media=attachments,
            metadata={"message_id": self._default_message_id, "source_tool": self.name},
        )
        await self._send_callback(outbound)
        return {
            "channel": self._default_channel,
            "chat_id": self._default_chat_id,
            "attachment_count": len(attachments),
        }
