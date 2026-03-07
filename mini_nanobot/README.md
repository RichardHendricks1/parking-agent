# mini_nanobot

一个可运行的最小版 Agent 骨架，核心只有：

- CLI (`onboard/chat`)
- OpenAI 兼容接口 provider
- 3 个工具：`read_file` / `write_file` / `exec`
- 工具调用循环（tool-calling loop）
- JSONL 会话持久化

## 1. 初始化

```bash
cd /Users/starktony/Downloads/nanobot-main
python3 -m mini_nanobot onboard
```

会生成：

- `~/.mini_nanobot/config.json`
- `~/.mini_nanobot/workspace/`

## 2. 配置 API Key

两种方式任选一种：

```bash
python3 -m mini_nanobot set-key YOUR_API_KEY
```

或者手动编辑 `~/.mini_nanobot/config.json`：

```json
{
  "api_key": "YOUR_API_KEY",
  "api_base": "https://open.bigmodel.cn/api/paas/v4",
  "model": "glm-4-flash"
}
```

## 3. 运行

交互模式：

```bash
python3 -m mini_nanobot chat
```

单轮模式：

```bash
python3 -m mini_nanobot chat -m "你好，帮我创建 notes.txt 并写入 hello"
```

清空会话：

```bash
python3 -m mini_nanobot clear-session
```

## 目录说明

- `config.py`: 配置读写 + onboard
- `provider.py`: OpenAI 兼容 `/chat/completions` 调用
- `tools.py`: 工具定义与注册表
- `session.py`: JSONL 会话存储
- `agent.py`: tool-calling 主循环
- `cli.py`: 命令行入口

