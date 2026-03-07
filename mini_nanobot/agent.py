"""Minimal tool-calling agent loop."""

from __future__ import annotations

from typing import Any

from mini_nanobot.provider import OpenAICompatibleProvider, ProviderError
from mini_nanobot.session import SessionStore
from mini_nanobot.tools import ToolRegistry, parse_tool_args


class MiniAgent:
    def __init__(
        self,
        provider: OpenAICompatibleProvider,
        tools: ToolRegistry,
        session: SessionStore,
        *,
        max_iterations: int = 8,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ):
        self.provider = provider
        self.tools = tools
        self.session = session
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.temperature = temperature

    def _pick_message(self, response: dict[str, Any]) -> dict[str, Any]:
        choices = response.get("choices") or []
        if not choices:
            return {"role": "assistant", "content": "Error: empty response"}
        return choices[0].get("message") or {"role": "assistant", "content": "Error: malformed response"}

    def chat_once(self, user_text: str) -> str:
        history = self.session.load()
        messages: list[dict[str, Any]] = list(history)
        turn_messages: list[dict[str, Any]] = []

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
            break

        if not final_text:
            final_text = "I could not finish the task within iteration limit."

        self.session.append_many(turn_messages)
        return final_text
