"""Very small OpenAI-compatible chat-completions client (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ProviderError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, api_key: str, api_base: str, model: str, timeout: int = 60):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("Missing api_key. Set it in ~/.mini_nanobot/config.json")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max(1, int(max_tokens)),
            "temperature": float(temperature),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{self.api_base}/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise ProviderError(f"HTTP {e.code}: {detail[:500]}") from e
        except urllib.error.URLError as e:
            raise ProviderError(f"Network error: {e}") from e

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"Invalid JSON response: {raw[:300]}") from e
