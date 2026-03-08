"""CLI for the minimal nanobot implementation."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from mini_nanobot.agent import MiniAgent
from mini_nanobot.config import ensure_workspace, load_config, onboard, save_config
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
    if args.cmd == "chat":
        return cmd_chat(args.message)
    if args.cmd == "clear-session":
        return cmd_clear_session()
    return 1
