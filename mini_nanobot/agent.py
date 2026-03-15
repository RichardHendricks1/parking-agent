"""Minimal tool-calling agent loop."""

from __future__ import annotations

from typing import Any

from mini_nanobot.provider import OpenAICompatibleProvider, ProviderError
from mini_nanobot.session import SessionStore
from mini_nanobot.tools import ToolRegistry, parse_tool_args


class MiniAgent:
    POST_TOOL_ANALYSIS_TARGETS = {"analyze_planning_log"}

    def __init__(
        self,
        provider: OpenAICompatibleProvider,
        tools: ToolRegistry,
        session: SessionStore,
        *,
        max_iterations: int = 8,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        post_tool_analysis_rounds: int = 2,
    ):
        self.provider = provider
        self.tools = tools
        self.session = session
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.post_tool_analysis_rounds = max(1, int(post_tool_analysis_rounds))

    def _build_refinement_prompt(
        self,
        round_idx: int,
        total_rounds: int,
        tools_in_turn: set[str],
    ) -> str:
        tools_text = ", ".join(sorted(tools_in_turn)) if tools_in_turn else "none"
        return (
            f"请基于本轮已有工具输出与上一轮结论，进行第 {round_idx + 1}/{total_rounds} 轮复核分析。"
            "要求：1) 校验是否有遗漏或矛盾；2) 引用关键证据（指标/阈值/异常）；"
            "3) 给出更稳健的最终结论；4) 若 analyze_planning_log 输出包含 module_diagnosis，优先引用 "
            "primary_module、confidence_0_to_1 和 reason。"
            f"本轮工具仅有：{tools_text}。"
            "严格忽略本轮之前的历史工具结果（例如 analyze_parking 等），只基于当前回合工具产出复核。"
        )

    def _pick_message(self, response: dict[str, Any]) -> dict[str, Any]:
        choices = response.get("choices") or []
        if not choices:
            return {"role": "assistant", "content": "Error: empty response"}
        return choices[0].get("message") or {"role": "assistant", "content": "Error: malformed response"}

    def chat_once(self, user_text: str) -> str:
        history = self.session.load()
        messages: list[dict[str, Any]] = list(history)
        turn_messages: list[dict[str, Any]] = []
        tools_used_in_turn: set[str] = set()
        post_tool_rounds_done = 0

        user_msg = {"role": "user", "content": user_text}
        messages.append(user_msg)
        turn_messages.append(user_msg)

        final_text = ""

        for _ in range(self.max_iterations):
            try:
                raw = self.provider.chat(
                    messages,
                    self.tools.schemas(),
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
            except ProviderError as e:
                final_text = f"Provider error: {e}"
                break

            assistant = self._pick_message(raw)
            tool_calls = assistant.get("tool_calls") or []

            if tool_calls:
                msg = {
                    "role": "assistant",
                    "content": assistant.get("content"),
                    "tool_calls": tool_calls,
                }
                messages.append(msg)
                turn_messages.append(msg)

                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name", "")
                    args = parse_tool_args(fn.get("arguments"))
                    result = self.tools.execute(name, args)
                    if name:
                        tools_used_in_turn.add(name)
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "name": name,
                        "content": result,
                    }
                    messages.append(tool_msg)
                    turn_messages.append(tool_msg)
                continue

            final_text = assistant.get("content") or ""
            final_msg = {"role": "assistant", "content": final_text}
            messages.append(final_msg)
            turn_messages.append(final_msg)
            eligible_for_refine = bool(
                tools_used_in_turn & self.POST_TOOL_ANALYSIS_TARGETS
            )
            if eligible_for_refine:
                post_tool_rounds_done += 1
                if post_tool_rounds_done < self.post_tool_analysis_rounds:
                    messages.append(
                        {
                            "role": "user",
                            "content": self._build_refinement_prompt(
                                post_tool_rounds_done,
                                self.post_tool_analysis_rounds,
                                tools_used_in_turn,
                            ),
                        }
                    )
                    continue
            break

        if not final_text:
            final_text = "I could not finish the task within iteration limit."

        self.session.append_many(turn_messages)
        return final_text
