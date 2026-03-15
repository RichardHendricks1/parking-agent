from __future__ import annotations

from mini_nanobot import cli
from mini_nanobot.config import AppConfig


def test_use_remote_keeps_existing_key_when_api_key_not_provided(monkeypatch):
    saved: dict[str, str] = {}
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: AppConfig(
            api_key="existing-key",
            api_base="http://127.0.0.1:18080/v1",
            model="tiny.gguf",
        ),
    )
    monkeypatch.setattr(cli, "save_config", lambda cfg: saved.update(cfg.__dict__))

    rc = cli.cmd_use_remote(
        api_base="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        api_key=None,
    )

    assert rc == 0
    assert saved["api_base"] == "https://open.bigmodel.cn/api/paas/v4"
    assert saved["model"] == "glm-4-flash"
    assert saved["api_key"] == "existing-key"


def test_use_remote_overrides_key_when_api_key_provided(monkeypatch):
    saved: dict[str, str] = {}
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig(api_key="", api_base="", model=""))
    monkeypatch.setattr(cli, "save_config", lambda cfg: saved.update(cfg.__dict__))

    rc = cli.cmd_use_remote(
        api_base="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        api_key="new-key",
    )

    assert rc == 0
    assert saved["api_key"] == "new-key"


def test_use_remote_rejects_empty_explicit_key(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig(api_key="old", api_base="", model=""))
    monkeypatch.setattr(cli, "save_config", lambda cfg: (_ for _ in ()).throw(RuntimeError("should not save")))

    rc = cli.cmd_use_remote(
        api_base="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        api_key="   ",
    )

    assert rc == 1
