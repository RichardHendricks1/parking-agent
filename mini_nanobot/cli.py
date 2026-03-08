"""CLI for the minimal nanobot implementation."""

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from mini_nanobot.agent import MiniAgent
from mini_nanobot.config import data_dir, ensure_workspace, load_config, onboard, save_config
from mini_nanobot.provider import OpenAICompatibleProvider
from mini_nanobot.session import SessionStore
from mini_nanobot.tools import (
    AnalyzeParkingTool,
    AnalyzePlanningLogTool,
    ExecTool,
    ReadFileTool,
    ToolRegistry,
    WriteFileTool,
)


def _build_agent() -> MiniAgent:
    cfg = load_config()
    ws = ensure_workspace(cfg)

    provider = OpenAICompatibleProvider(
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        model=cfg.model,
    )

    tools = ToolRegistry()
    tools.register(ReadFileTool(ws))
    tools.register(WriteFileTool(ws))
    tools.register(ExecTool(ws))
    tools.register(AnalyzeParkingTool())
    tools.register(AnalyzePlanningLogTool(ws))

    session = SessionStore(ws, cfg.session_id)
    return MiniAgent(
        provider=provider,
        tools=tools,
        session=session,
        max_iterations=cfg.max_iterations,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
        post_tool_analysis_rounds=cfg.post_tool_analysis_rounds,
    )


def cmd_onboard() -> int:
    cfg_path, ws = onboard()
    print(f"Config: {cfg_path}")
    print(f"Workspace: {ws}")
    print("Next: open config and set api_key.")
    print("Run: python3 -m mini_nanobot chat")
    return 0


def cmd_set_key(key: str) -> int:
    cfg = load_config()
    cfg.api_key = key.strip()
    save_config(cfg)
    print("Saved api_key into ~/.mini_nanobot/config.json")
    return 0


def cmd_use_local(model: str, api_base: str, skip_pull: bool = False) -> int:
    cfg = load_config()

    if not skip_pull:
        if not shutil.which("ollama"):
            print("Error: ollama not found.")
            print("Install ollama first, or rerun with --skip-pull to use your own local OpenAI-compatible endpoint.")
            return 1
        print(f"Pulling local model via ollama: {model}")
        proc = subprocess.run(["ollama", "pull", model], text=True)
        if proc.returncode != 0:
            print(f"Error: failed to pull model {model} (exit={proc.returncode})")
            return proc.returncode

    cfg.api_base = api_base.rstrip("/")
    cfg.model = model
    if not (cfg.api_key or "").strip():
        cfg.api_key = "local"
    save_config(cfg)

    print("Configured local model for mini_nanobot:")
    print(f"- model: {cfg.model}")
    print(f"- api_base: {cfg.api_base}")
    print("- api_key: local")
    print("Run: python3 -m mini_nanobot chat")
    return 0


def cmd_use_remote(api_base: str, model: str, api_key: str | None = None) -> int:
    cfg = load_config()
    cfg.api_base = api_base.rstrip("/")
    cfg.model = model

    if api_key is not None:
        new_key = api_key.strip()
        if not new_key:
            print("Error: --api-key is empty.")
            return 1
        cfg.api_key = new_key

    save_config(cfg)

    print("Configured remote model for mini_nanobot:")
    print(f"- model: {cfg.model}")
    print(f"- api_base: {cfg.api_base}")
    if (cfg.api_key or "").strip():
        print("- api_key: set")
    else:
        print("- api_key: empty (run `python3 -m mini_nanobot set-key YOUR_API_KEY`)")
    print("Run: python3 -m mini_nanobot chat")
    return 0


def _local_server_state_path() -> Path:
    run_dir = data_dir() / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / "local_server.json"


def _load_local_server_state(path: Path | None = None) -> dict[str, Any] | None:
    state_path = path or _local_server_state_path()
    if not state_path.exists():
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _save_local_server_state(state: dict[str, Any], path: Path | None = None) -> None:
    state_path = path or _local_server_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _probe_local_server(host: str, port: int, timeout_s: float = 1.0) -> bool:
    url = f"http://{host}:{port}/v1/models"
    req = url_request.Request(url=url, method="GET")
    try:
        with url_request.urlopen(req, timeout=timeout_s) as resp:
            return int(getattr(resp, "status", 0)) in range(200, 300)
    except (url_error.URLError, OSError):
        return False


def _wait_for_local_server(host: str, port: int, timeout_s: float) -> bool:
    timeout_s = max(timeout_s, 0.0)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _probe_local_server(host, port):
            return True
        time.sleep(0.25)
    return _probe_local_server(host, port)


def _tail_text(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return ""
    return "".join(lines[-max_lines:]).strip()


def cmd_start_local_server(
    model_path: str,
    host: str,
    port: int,
    ctx_size: int,
    n_gpu_layers: int,
    binary: str,
    wait_timeout_s: float,
    configure_agent: bool = True,
) -> int:
    model = Path(model_path).expanduser()
    if not model.is_absolute():
        model = (Path.cwd() / model).resolve()
    if not model.exists():
        print(f"Error: model file not found: {model}")
        return 1

    binary_path = shutil.which(binary)
    if not binary_path:
        print(f"Error: {binary} not found.")
        print("Install llama.cpp first (`brew install llama.cpp`) or use --binary with a full path.")
        return 1

    state_path = _local_server_state_path()
    old = _load_local_server_state(state_path)
    if old:
        old_pid = int(old.get("pid", 0) or 0)
        old_host = str(old.get("host", "127.0.0.1"))
        old_port = int(old.get("port", 0) or 0)
        if _is_pid_running(old_pid):
            print(f"Local server already running: pid={old_pid}, endpoint=http://{old_host}:{old_port}/v1")
            print("Run `python3 -m mini_nanobot local-server-status` to verify health.")
            return 0
        try:
            state_path.unlink()
        except OSError:
            pass

    if _probe_local_server(host, port):
        print(f"Error: endpoint http://{host}:{port}/v1 is already reachable.")
        print("Another local model service is already using this address.")
        print("Use a different --port or stop the existing service first.")
        return 1

    run_dir = state_path.parent
    log_path = run_dir / "local_server.log"
    cmd = [
        binary_path,
        "-m",
        str(model),
        "--host",
        host,
        "--port",
        str(port),
        "-ngl",
        str(n_gpu_layers),
        "-c",
        str(ctx_size),
    ]

    run_dir.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    if not _wait_for_local_server(host, port, wait_timeout_s):
        if _is_pid_running(proc.pid):
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except OSError:
                pass
        print(f"Error: local server failed to become ready within {wait_timeout_s:.1f}s.")
        print(f"Log: {log_path}")
        tail = _tail_text(log_path, max_lines=20)
        if tail:
            print("Last log lines:")
            print(tail)
        return 1

    state = {
        "pid": proc.pid,
        "host": host,
        "port": port,
        "model_path": str(model),
        "model_name": model.name,
        "binary": binary_path,
        "log_path": str(log_path),
        "started_at_epoch": int(time.time()),
    }
    _save_local_server_state(state, state_path)

    if configure_agent:
        cfg = load_config()
        client_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        cfg.api_base = f"http://{client_host}:{port}/v1"
        cfg.model = model.name
        if not (cfg.api_key or "").strip():
            cfg.api_key = "local"
        save_config(cfg)
        print("mini_nanobot config updated:")
        print(f"- api_base: {cfg.api_base}")
        print(f"- model: {cfg.model}")
        print(f"- api_key: {cfg.api_key}")

    print("Local llama.cpp server started:")
    print(f"- pid: {proc.pid}")
    print(f"- endpoint: http://{host}:{port}/v1")
    print(f"- model: {model}")
    print(f"- log: {log_path}")
    print("Run: python3 -m mini_nanobot chat")
    return 0


def cmd_stop_local_server(wait_timeout_s: float) -> int:
    state_path = _local_server_state_path()
    state = _load_local_server_state(state_path)
    if not state:
        print("Local server is not running.")
        return 0

    pid = int(state.get("pid", 0) or 0)
    if not _is_pid_running(pid):
        try:
            state_path.unlink()
        except OSError:
            pass
        print("Local server state cleared (process not running).")
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    deadline = time.time() + max(wait_timeout_s, 0.0)
    while time.time() < deadline and _is_pid_running(pid):
        time.sleep(0.2)

    if _is_pid_running(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        time.sleep(0.2)

    still_running = _is_pid_running(pid)
    try:
        state_path.unlink()
    except OSError:
        pass

    if still_running:
        print(f"Error: failed to stop local server pid={pid}.")
        return 1
    print(f"Stopped local server (pid={pid}).")
    return 0


def cmd_local_server_status() -> int:
    state = _load_local_server_state()
    if not state:
        print("Local server status: stopped (no state file).")
        return 1

    pid = int(state.get("pid", 0) or 0)
    host = str(state.get("host", "127.0.0.1"))
    port = int(state.get("port", 0) or 0)
    model = str(state.get("model_name", ""))
    log_path = str(state.get("log_path", ""))

    running = _is_pid_running(pid)
    healthy = running and _probe_local_server(host, port)

    print("Local server status:")
    print(f"- pid: {pid}")
    print(f"- process: {'running' if running else 'stopped'}")
    print(f"- endpoint: http://{host}:{port}/v1")
    print(f"- health: {'ok' if healthy else 'unreachable'}")
    print(f"- model: {model}")
    print(f"- log: {log_path}")
    return 0 if healthy else 1


def cmd_chat(message: str | None = None) -> int:
    agent = _build_agent()

    if message:
        print(agent.chat_once(message))
        return 0

    print("mini_nanobot interactive mode. type 'exit' to quit.")
    while True:
        try:
            text = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nbye")
            return 0
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            print("bye")
            return 0
        reply = agent.chat_once(text)
        print(f"Bot: {reply}")


def cmd_clear_session() -> int:
    cfg = load_config()
    ws = ensure_workspace(cfg)
    session = SessionStore(ws, cfg.session_id)
    session_path: Path = session.path
    session.clear()
    print(f"Cleared session: {session_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mini_nanobot")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("onboard", help="Create default config and workspace")

    set_key = sub.add_parser("set-key", help="Save API key into config")
    set_key.add_argument("key", help="Provider API key")

    local = sub.add_parser("use-local", help="Configure a local model endpoint (default: Ollama)")
    local.add_argument("--model", default="llama3.2:1b", help="Local model name")
    local.add_argument("--api-base", default="http://127.0.0.1:11434/v1", help="Local OpenAI-compatible API base")
    local.add_argument("--skip-pull", action="store_true", help="Skip `ollama pull`")

    remote = sub.add_parser("use-remote", help="Configure a remote model endpoint")
    remote.add_argument("--api-base", default="https://open.bigmodel.cn/api/paas/v4", help="Remote API base URL")
    remote.add_argument("--model", default="glm-4-flash", help="Remote model name")
    remote.add_argument("--api-key", help="Optional API key; if omitted keeps existing key")

    local_start = sub.add_parser("start-local-server", help="Start local llama.cpp server with one command")
    local_start.add_argument("--model-path", required=True, help="Path to GGUF model file")
    local_start.add_argument("--host", default="127.0.0.1", help="Bind host")
    local_start.add_argument("--port", type=int, default=18080, help="Bind port")
    local_start.add_argument("--ctx-size", type=int, default=2048, help="Context size (-c)")
    local_start.add_argument("--n-gpu-layers", type=int, default=0, help="GPU layers (-ngl)")
    local_start.add_argument("--binary", default="llama-server", help="llama.cpp server binary")
    local_start.add_argument("--wait-timeout", type=float, default=30.0, help="Startup wait timeout (seconds)")
    local_start.add_argument(
        "--no-configure-agent",
        action="store_true",
        help="Do not update ~/.mini_nanobot/config.json after startup",
    )

    local_stop = sub.add_parser("stop-local-server", help="Stop previously started local llama.cpp server")
    local_stop.add_argument("--wait-timeout", type=float, default=10.0, help="Graceful stop timeout (seconds)")

    sub.add_parser("local-server-status", help="Show local llama.cpp server status")

    chat = sub.add_parser("chat", help="Interactive chat or one-shot message")
    chat.add_argument("-m", "--message", help="One-shot message")

    sub.add_parser("clear-session", help="Clear current chat session")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "onboard":
        return cmd_onboard()
    if args.cmd == "set-key":
        return cmd_set_key(args.key)
    if args.cmd == "use-local":
        return cmd_use_local(args.model, args.api_base, args.skip_pull)
    if args.cmd == "use-remote":
        return cmd_use_remote(args.api_base, args.model, args.api_key)
    if args.cmd == "start-local-server":
        return cmd_start_local_server(
            model_path=args.model_path,
            host=args.host,
            port=args.port,
            ctx_size=args.ctx_size,
            n_gpu_layers=args.n_gpu_layers,
            binary=args.binary,
            wait_timeout_s=args.wait_timeout,
            configure_agent=not args.no_configure_agent,
        )
    if args.cmd == "stop-local-server":
        return cmd_stop_local_server(args.wait_timeout)
    if args.cmd == "local-server-status":
        return cmd_local_server_status()
    if args.cmd == "chat":
        return cmd_chat(args.message)
    if args.cmd == "clear-session":
        return cmd_clear_session()
    return 1
