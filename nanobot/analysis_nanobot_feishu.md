# nanobot 项目解析（Feishu 格式）

**项目概览**
- **名称**: nanobot — Ultra-Lightweight Personal AI Assistant
- **语言/环境**: Python (>=3.11)
- **仓库根**: [README.md](README.md)
- **安装**: 支持 `pip install`, `pip install -e .` 与 `uv` 安装

**关键目录与文件**

| 路径 | 说明 |
|---|---|
| [README.md](README.md) | 项目总览、快速上手、架构图与通道支持说明 |
| [pyproject.toml](pyproject.toml) | Python 包描述与依赖 |
| [nanobot/__main__.py](nanobot/__main__.py) | CLI 入口 |
| [nanobot/agent/__init__.py](nanobot/agent/__init__.py) | Agent 子包 |
| [nanobot/agent/subagent.py](nanobot/agent/subagent.py) | 子代理（subagent）实现 - 当前正在编辑的文件 |
| [nanobot/agent/context.py](nanobot/agent/context.py) | 上下文管理 |
| [nanobot/agent/loop.py](nanobot/agent/loop.py) | Agent 主循环 |
| [nanobot/agent/memory.py](nanobot/agent/memory.py) | 内存/持久化逻辑 |
| [nanobot/channels/](nanobot/channels/) | 各类渠道实现（Feishu、Slack、Telegram 等） |
| [nanobot/providers/](nanobot/providers/) | LLM/provider 适配器（registry、provider 实现） |
| [nanobot/templates/](nanobot/templates/) | 提示模板与 agent/skill 模板 |
| [nanobot/skills/](nanobot/skills/) | 内置 skill 示例与说明 |
| [tests/](tests/) | 单元测试，覆盖 CLI、channels、工具等 |

**核心架构要点**

- **Agent 层（`nanobot/agent`）**: 负责接收输入、维护上下文、触发子任务（subagents）、管理 memory 与 turn 历史。
- **Channels（`nanobot/channels`）**: 将 Agent 输出/输入适配到具体聊天平台；每个 channel 实现 `base.py` 中的接口并注册到 manager。
- **Providers（`nanobot/providers`）**: 抽象 LLM 提供者（OpenRouter、Anthropic、OpenAI Codex 等），通过 `registry.py` 管理不同 provider 的适配器。
- **Skills 与 Templates（`nanobot/skills`, `nanobot/templates`）**: 可复用的技能脚本与提示模板，便于扩展 agent 功能。
- **Tools（`nanobot/agent/tools`）**: 小工具集合（文件系统、web、shell、cron 等），允许 agent 发起可执行动作。
- **Session 与 Heartbeat**: 支持会话管理和心跳服务，适合长期运行的 agent 实例。

**主要文件快速解读（选取）**
- `nanobot/agent/subagent.py`: 子代理实现，负责短期的子任务执行、并发或 CLI 模式下的子工作流。
- `nanobot/agent/loop.py`: Agent 主循环调度入口，处理消息队列、调用 skills 与 tools。
- `nanobot/providers/registry.py`: provider 注册与发现逻辑；新增 provider 通常只需实现 base 接口并注册。
- `nanobot/channels/feishu.py`、`nanobot/channels/slack.py`: 各渠道消息格式化、授权与事件映射示例。
- `nanobot/templates/` 下的 `AGENTS.md` / `TOOLS.md`: 文档化模板与使用说明，便于创建自定义 agents 或 tools。

**运行与测试（建议步骤）**

```bash
# 激活开发环境（用户环境说明：使用 conda my_env）
conda activate my_env
# 安装（开发模式）
pip install -e .
# 运行 agent（本地交互）
nanobot agent
# 运行测试
pytest -q
```

**配置要点**
- 用户配置位于 `~/.nanobot/config.json`（README 有示例）；主要是 `providers` 与 `channels` 的密钥/凭证。
- 日志与心跳配置可在 `nanobot/heartbeat/service.py` 中查看与调整。

**安全与部署注意**
- 请勿把 provider API key 提交到仓库；使用本地 `~/.nanobot/config.json` 或环境变量。
- Docker 支持：仓库含 `Dockerfile` 与 `docker-compose.yml`，便于容器化部署。

**建议的后续深挖点**
1. 深入 `nanobot/agent/subagent.py`：理解子代理的生命周期与并发模型（当前文件）
2. 检查 `nanobot/providers/*`：新增 LLM provider 的接入步骤
3. 浏览 `nanobot/channels/*`：研究要接入的新消息平台的实现方式
4. 查看 `tests/`：学习测试覆盖点与示例调用方式

---
文档生成时间: 2026-03-06

如果需要，我可以：
- 针对 `nanobot/agent/subagent.py` 做逐行详解并生成调用图；
- 为某个 provider 或 channel 撰写接入指南与示例配置；
- 执行一次本地 `pytest` 并输出失败详情（需确认 Python 环境）。
