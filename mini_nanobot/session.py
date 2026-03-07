"""Simple JSONL-backed session store."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class SessionStore:
    def __init__(self, workspace: Path, session_id: str):
        self.workspace = workspace
        safe = session_id.replace(":", "_")
        self.path = workspace / "sessions" / f"{safe}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def append_many(self, messages: list[dict[str, Any]]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            for m in messages:
                item = dict(m)
                item.setdefault("timestamp", datetime.now().isoformat())
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
