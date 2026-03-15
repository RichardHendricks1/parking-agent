"""Configuration loading and onboarding helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    api_key: str = ""
    api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-4-flash"
    workspace: str = "~/.mini_nanobot/workspace"
    session_id: str = "cli:default"
    max_iterations: int = 8
    max_tokens: int = 1024
    temperature: float = 0.2
    post_tool_analysis_rounds: int = 2


def data_dir() -> Path:
    return Path.home() / ".mini_nanobot"


def config_path() -> Path:
    return data_dir() / "config.json"


def workspace_path(cfg: AppConfig) -> Path:
    return Path(cfg.workspace).expanduser()


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    if not path.exists():
        return AppConfig()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cfg = AppConfig()
    for key, val in raw.items():
        if hasattr(cfg, key):
            setattr(cfg, key, val)
    return cfg


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.__dict__, f, indent=2, ensure_ascii=False)


def ensure_workspace(cfg: AppConfig) -> Path:
    ws = workspace_path(cfg)
    (ws / "sessions").mkdir(parents=True, exist_ok=True)
    return ws


def onboard() -> tuple[Path, Path]:
    """Create default config + workspace if missing."""
    cfg = load_config()
    save_config(cfg)
    ws = ensure_workspace(cfg)
    return config_path(), ws
