from __future__ import annotations

import json

from mini_nanobot import cli
from mini_nanobot.config import AppConfig


class _DummyProc:
    def __init__(self, pid: int = 4321):
        self.pid = pid


def test_start_local_server_success_writes_state_and_config(tmp_path, monkeypatch):
    model_path = tmp_path / "tiny.gguf"
    model_path.write_bytes(b"gguf")
    home_dir = tmp_path / "home"
    saved_cfg: dict[str, str] = {}

    monkeypatch.setattr(cli, "data_dir", lambda: home_dir)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/llama-server")
    monkeypatch.setattr(cli, "_probe_local_server", lambda host, port, timeout_s=1.0: False)
    monkeypatch.setattr(cli, "_wait_for_local_server", lambda host, port, timeout_s: True)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *args, **kwargs: _DummyProc(pid=2468))
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig(api_key="", api_base="", model=""))
    monkeypatch.setattr(cli, "save_config", lambda cfg: saved_cfg.update(cfg.__dict__))

    rc = cli.cmd_start_local_server(
        model_path=str(model_path),
        host="127.0.0.1",
        port=18080,
        ctx_size=2048,
        n_gpu_layers=0,
        binary="llama-server",
        wait_timeout_s=1.0,
        configure_agent=True,
    )

    assert rc == 0
    state_path = home_dir / "run" / "local_server.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["pid"] == 2468
    assert state["port"] == 18080
    assert state["model_name"] == "tiny.gguf"

    assert saved_cfg["api_base"] == "http://127.0.0.1:18080/v1"
    assert saved_cfg["model"] == "tiny.gguf"
    assert saved_cfg["api_key"] == "local"


def test_start_local_server_missing_model_returns_error(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    monkeypatch.setattr(cli, "data_dir", lambda: home_dir)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/llama-server")

    rc = cli.cmd_start_local_server(
        model_path=str(tmp_path / "missing.gguf"),
        host="127.0.0.1",
        port=18080,
        ctx_size=2048,
        n_gpu_layers=0,
        binary="llama-server",
        wait_timeout_s=1.0,
        configure_agent=True,
    )
    assert rc == 1


def test_start_local_server_fails_if_endpoint_already_reachable(tmp_path, monkeypatch):
    model_path = tmp_path / "tiny.gguf"
    model_path.write_bytes(b"gguf")
    home_dir = tmp_path / "home"

    monkeypatch.setattr(cli, "data_dir", lambda: home_dir)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/llama-server")
    monkeypatch.setattr(cli, "_probe_local_server", lambda host, port, timeout_s=1.0: True)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not spawn")))

    rc = cli.cmd_start_local_server(
        model_path=str(model_path),
        host="127.0.0.1",
        port=18080,
        ctx_size=2048,
        n_gpu_layers=0,
        binary="llama-server",
        wait_timeout_s=1.0,
        configure_agent=True,
    )
    assert rc == 1


def test_stop_local_server_clears_stale_state(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    state_path = home_dir / "run" / "local_server.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "pid": 999999,
                "host": "127.0.0.1",
                "port": 18080,
                "model_name": "tiny.gguf",
                "log_path": "/tmp/llama.log",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "data_dir", lambda: home_dir)
    monkeypatch.setattr(cli, "_is_pid_running", lambda pid: False)

    rc = cli.cmd_stop_local_server(wait_timeout_s=0.1)
    assert rc == 0
    assert not state_path.exists()


def test_local_server_status_returns_success_when_healthy(tmp_path, monkeypatch, capsys):
    home_dir = tmp_path / "home"
    state_path = home_dir / "run" / "local_server.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "pid": 2468,
                "host": "127.0.0.1",
                "port": 18080,
                "model_name": "tiny.gguf",
                "log_path": str(tmp_path / "local_server.log"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "data_dir", lambda: home_dir)
    monkeypatch.setattr(cli, "_is_pid_running", lambda pid: True)
    monkeypatch.setattr(cli, "_probe_local_server", lambda host, port, timeout_s=1.0: True)

    rc = cli.cmd_local_server_status()

    out = capsys.readouterr().out
    assert rc == 0
    assert "health: ok" in out
