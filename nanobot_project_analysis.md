# nanobot 项目技术分析报告

## 一、项目概述

### 1.1 项目定位

**nanobot** 是一个超轻量级的个人 AI 助手框架，灵感来源于 [OpenClaw](https://github.com/openclaw/openclaw)。项目核心特点：

| 特性 | 说明 |
|------|------|
| 代码规模 | 相比 OpenClaw 减少 99% 的代码量 |
| Python 版本 | >= 3.11 |
| 许可证 | MIT |
| 当前版本 | v0.1.4.post3 |

### 1.2 核心依赖

```python
# 核心框架依赖
typer           # CLI 框架
litellm         # LLM 统一接口
pydantic        # 数据验证
websockets      # WebSocket 支持
httpx           # HTTP 客户端
loguru          # 日志处理
```

---

## 二、项目架构

### 2.1 目录结构

```
nanobot-main/
├── nanobot/              # 主项目
│   ├── agent/           # Agent 核心逻辑
│   │   ├── loop.py      # Agent 循环引擎
│   │   ├── context.py   # 上下文构建
│   │   ├── memory.py    # 记忆存储
│   │   ├── skills.py    # 技能加载器
│   │   ├── subagent.py  # 子代理管理
│   │   └── tools/       # 工具集合
│   ├── channels/        # 消息通道
│   ├── providers/       # LLM 提供商
│   ├── config/          # 配置管理
│   ├── bus/             # 消息总线
│   ├── session/         # 会话管理
│   ├── skills/          # 内置技能
│   └── cli/             # 命令行接口
├── mini_nanobot/        # 最小化版本
│   ├── agent.py         # 精简 Agent
│   ├── provider.py      # OpenAI 兼容接口
│   ├── tools.py         # 基础工具
│   └── session.py       # 会话存储
└── bridge/              # JS 桥接层
```

### 2.2 架构分层

```
┌─────────────────────────────────────────────────┐
│              Channels Layer                     │
│  Feishu / DingTalk / Telegram / Discord / ...  │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│              Message Bus                        │
│         Event Queue / Dispatch                  │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│              Agent Loop                         │
│  Context Builder → LLM → Tool Execution         │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│              Tool Registry                      │
│  File / Shell / Web / Cron / MCP / ...          │
└─────────────────────────────────────────────────┘
```

---

## 三、核心模块分析

### 3.1 Agent 循环引擎 (loop.py)

**核心职责**：

```python
class AgentLoop:
    """
    1. 从消息总线接收消息
    2. 构建上下文（历史、记忆、技能）
    3. 调用 LLM
    4. 执行工具调用
    5. 发送响应
    """
```

**关键参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_iterations | 40 | 最大迭代次数 |
| temperature | 0.1 | 温度参数 |
| max_tokens | 4096 | 最大 token 数 |
| memory_window | 100 | 记忆窗口大小 |

### 3.2 工具调用循环 (mini_nanobot/agent.py)

**最小化实现的核心逻辑**：

```python
# 第 36-96 行：单次对话处理流程
def chat_once(self, user_text: str) -> str:
    # 1. 加载历史会话
    history = self.session.load()

    # 2. 迭代调用 LLM
    for _ in range(self.max_iterations):
        # 2.1 调用 Provider 获取响应
        raw = self.provider.chat(messages, tools, ...)

        # 2.2 检查是否有工具调用
        if tool_calls:
            # 执行工具并收集结果
            result = self.tools.execute(name, args)
            # 继续下一轮迭代
            continue

        # 2.3 获取最终文本响应
        final_text = assistant.get("content")
        break

    # 3. 持久化会话
    self.session.append_many(turn_messages)
    return final_text
```

**流程图**：

```
用户输入 → 加载历史 → 构建消息
    ↓
    ┌─────────────────┐
    │  LLM 调用       │
    └─────────────────┘
    ↓
    有工具调用？
    ├─ 是 → 执行工具 → 收集结果 → 继续 LLM 调用
    └─ 否 → 返回最终文本 → 保存会话
```

### 3.3 技能系统 (skills.py)

**技能加载机制**：

| 层级 | 优先级 | 说明 |
|------|--------|------|
| workspace skills | 最高 | 用户自定义技能 |
| builtin skills | 默认 | 框架内置技能 |

**技能元数据结构**：

```yaml
---
description: "技能描述"
nanobot:
  always: true/false    # 是否始终加载
  requires:
    bins: [cli1, cli2]  # 需要的 CLI 工具
    env: [ENV_VAR]      # 需要的环境变量
---
```

### 3.4 工具注册表

**内置工具类型**：

| 工具类 | 文件 | 功能 |
|--------|------|------|
| ReadFileTool | filesystem.py | 读取文件 |
| WriteFileTool | filesystem.py | 写入文件 |
| EditFileTool | filesystem.py | 编辑文件 |
| ListDirTool | filesystem.py | 列出目录 |
| ExecTool | shell.py | 执行 shell 命令 |
| WebFetchTool | web.py | 网页获取 |
| WebSearchTool | web.py | 网页搜索 |
| CronTool | cron.py | 定时任务 |
| MessageTool | message.py | 消息发送 |
| SpawnTool | spawn.py | 子代理生成 |

---

## 四、消息通道支持

### 4.1 支持的通道

| 通道 | 文件 | 状态 |
|------|------|------|
| 飞书 | feishu.py | 完整支持 |
| 钉钉 | dingtalk.py | 完整支持 |
| Telegram | telegram.py | 完整支持 |
| Discord | discord.py | 完整支持 |
| Slack | slack.py | 完整支持 |
| Matrix | matrix.py | 完整支持 |
| 微信企群 | mochat.py | 完整支持 |
| QQ | qq.py | 完整支持 |
| WhatsApp | whatsapp.py | 完整支持 |
| Email | email.py | 完整支持 |

### 4.2 通道基类设计

```python
class BaseChannel(ABC):
    @abstractmethod
    async def start(self): ...

    @abstractmethod
    async def stop(self): ...

    @abstractmethod
    async def send_message(self, target, message): ...
```

---

## 五、LLM 提供商

### 5.1 Provider 架构

```
LLMProvider (Base)
    ↓
├── LiteLLMProvider
├── OpenAICodexProvider
└── CustomProvider
```

### 5.2 兼容性

通过 `litellm` 库支持多种 LLM：

- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Google (Gemini)
- 国内模型 (通义千问、文心一言等)
- Mistral
- Groq

---

## 六、配置管理

### 6.1 配置加载

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )
```

### 6.2 配置优先级

```
命令行参数 > 环境变量 > 配置文件 > 默认值
```

---

## 七、会话管理

### 7.1 会话存储

| 存储方式 | 位置 |
|----------|------|
| 持久化 | workspace/sessions/ |
| 格式 | JSONL |
| 结构 | 逐行存储消息对象 |

### 7.2 记忆系统

```python
class MemoryStore:
    """
    短期记忆：当前会话上下文
    长期记忆：跨会话的知识积累
    """
```

---

## 八、mini_nanobot 最小化实现

### 8.1 设计理念

**极简核心**：

```
┌────────────────────────────────────┐
│         mini_nanobot               │
│                                    │
│  CLI → Provider → Tools → Agent    │
│                                    │
│  ~500 行核心代码                    │
└────────────────────────────────────┘
```

### 8.2 核心组件对比

| 组件 | nanobot | mini_nanobot |
|------|---------|--------------|
| Provider | 多层抽象 | OpenAI 兼容接口 |
| Session | 复杂管理 | JSONL 文件 |
| Tools | 20+ 工具 | 4 个基础工具 |
| Channels | 10+ 通道 | 仅 CLI |
| Agent | 子代理、记忆 | 简单循环 |

### 8.3 使用示例

```bash
# 初始化
python3 -m mini_nanobot onboard

# 配置 API Key
python3 -m mini_nanobot set-key YOUR_API_KEY

# 交互模式
python3 -m mini_nanobot chat

# 单轮模式
python3 -m mini_nanobot chat -m "你好"
```

---

## 九、技术特点总结

### 9.1 优势

| 特性 | 说明 |
|------|------|
| 轻量级 | 核心代码量少，易于理解和修改 |
| 可扩展 | 插件化的工具和通道系统 |
| 多通道 | 支持主流即时通讯平台 |
| 标准化 | 遵循 OpenAI 函数调用规范 |
| 生产就绪 | 包含会话管理、错误处理、日志 |

### 9.2 适用场景

| 场景 | 说明 |
|------|------|
| 个人助手 | 集成到常用聊天工具 |
| 自动化 | 定时任务、文件操作 |
| 开发学习 | 理解 Agent 框架原理 |
| 快速原型 | 基于 mini_nanobot 快速验证想法 |

---

## 十、关键代码位置索引

| 功能 | 文件路径 | 行号 |
|------|----------|------|
| Agent 主循环 | nanobot/agent/loop.py | 35-600 |
| 工具调用循环 | mini_nanobot/agent.py | 36-96 |
| 技能加载 | nanobot/agent/skills.py | 13-229 |
| 飞书通道 | nanobot/channels/feishu.py | 全文 |
| 消息总线 | nanobot/bus/queue.py | 全文 |
| 会话管理 | nanobot/session/manager.py | 全文 |

---

**文档版本**: 1.0
**生成时间**: 2026-03-07
**分析对象**: nanobot v0.1.4.post3
