"""Built-in tools and registry."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolError(RuntimeError):
    pass


@dataclass
class ToolCall:
    tool_name: str
    arguments: dict[str, Any]


class Tool:
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, **kwargs: Any) -> str:
        raise NotImplementedError


def _resolve_path(workspace: Path, path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = workspace / p
    rp = p.resolve()
    ws = workspace.resolve()
    try:
        rp.relative_to(ws)
    except ValueError as e:
        raise ToolError(f"path outside workspace: {rp}") from e
    return rp


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read UTF-8 text from a file in workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def run(self, **kwargs: Any) -> str:
        path = _resolve_path(self.workspace, kwargs["path"])
        if not path.exists():
            return f"Error: file not found: {path}"
        if not path.is_file():
            return f"Error: not a file: {path}"
        text = path.read_text(encoding="utf-8")
        max_chars = 32_000
        if len(text) > max_chars:
            return text[:max_chars] + "\n... (truncated)"
        return text


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write UTF-8 text to a file in workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def run(self, **kwargs: Any) -> str:
        path = _resolve_path(self.workspace, kwargs["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        content = kwargs["content"]
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {path}"


class ExecTool(Tool):
    name = "exec"
    description = "Run a shell command inside workspace and return output."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path, timeout: int = 20):
        self.workspace = workspace
        self.timeout = timeout

    def run(self, **kwargs: Any) -> str:
        cmd = kwargs["command"]
        blocked = ("rm -rf", "shutdown", "reboot", "mkfs", "dd if=")
        if any(x in cmd for x in blocked):
            return "Error: command blocked by guard"
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            return f"Error: command timeout after {self.timeout}s"
        out = proc.stdout or ""
        err = proc.stderr or ""
        merged = out
        if err.strip():
            merged += ("\n" if merged else "") + "STDERR:\n" + err
        if proc.returncode != 0:
            merged += ("\n" if merged else "") + f"\nExit code: {proc.returncode}"
        merged = merged.strip() or "(no output)"
        return merged[:10_000]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Error: unknown tool {name}"
        try:
            return tool.run(**args)
        except Exception as e:
            return f"Error executing {name}: {e}"


def parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
