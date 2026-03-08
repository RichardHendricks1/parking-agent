import json
from unittest.mock import patch

import pytest

from mini_nanobot.provider import OpenAICompatibleProvider, ProviderError


class _Resp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_local_base_allows_missing_api_key():
    provider = OpenAICompatibleProvider(
        api_key="",
        api_base="http://127.0.0.1:11434/v1",
        model="llama3.2:1b",
    )

    def fake_urlopen(req, timeout=60):
        assert req.full_url.endswith("/chat/completions")
        assert req.headers.get("Authorization") is None
        payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        return _Resp(json.dumps(payload))

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = provider.chat([{"role": "user", "content": "hi"}], tools=[])
    assert out["choices"][0]["message"]["content"] == "ok"


def test_remote_base_requires_api_key():
    provider = OpenAICompatibleProvider(
        api_key="",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
    )
    with pytest.raises(ProviderError):
        provider.chat([{"role": "user", "content": "hi"}], tools=[])
