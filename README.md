# mini_nanobot

`mini_nanobot` 现在是 `Parking Judge` 的兼容包名，保留原有 agent 入口，同时增加了 deterministic log analysis 模式。

核心能力：

- CLI (`onboard/chat`)
- OpenAI 兼容接口 provider
- 5 个工具：`read_file` / `write_file` / `exec` / `analyze_parking` / `analyze_planning_log`
- deterministic 命令：`analyze-log` / `batch-analyze-logs`
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
  "model": "glm-4-flash",
  "post_tool_analysis_rounds": 2,
  "strict_planning_json_output": true,
  "planning_json_retry_limit": 2
}
```

`post_tool_analysis_rounds` 表示工具返回后，大模型会做几轮复核总结再给最终结论（默认 2 轮，可调大）。
`strict_planning_json_output` 和 `planning_json_retry_limit` 用于约束 `analyze_planning_log` 后续输出为严格 JSON，并在格式偏离时自动纠偏重试。

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

## 使用本地模型（Ollama / llama.cpp）

如果你想让 mini_nanobot 调本地小模型，可以一键切换：

```bash
python3 -m mini_nanobot use-local --model llama3.2:1b
```

这条命令会：
- 用 `ollama pull` 下载模型（可用 `--skip-pull` 跳过）
- 把配置切到本地 API：`http://127.0.0.1:11434/v1`
- 将 model 设置为你指定的本地模型

然后直接运行：

```bash
python3 -m mini_nanobot chat -m "你好，用本地模型回复"
```

说明：
- 当 `api_base` 是本地地址（localhost/127.0.0.1）时，可以不依赖远端 API key。
- 如果你使用的不是 Ollama，也可以用 `--api-base` 指向任意本地 OpenAI 兼容服务。

如果你已经有 `GGUF` 模型，也可以直接一键拉起本地 `llama.cpp` 服务（会自动写入 mini_nanobot 配置）：

```bash
python3 -m mini_nanobot start-local-server \
  --model-path /Users/starktony/Downloads/nanobot-main/models/gguf/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 18080
```

查看运行状态：

```bash
python3 -m mini_nanobot local-server-status
```

停止服务：

```bash
python3 -m mini_nanobot stop-local-server
```

可选参数（`start-local-server`）：
- `--ctx-size`：上下文窗口（默认 `2048`）
- `--n-gpu-layers`：下沉到 GPU 的层数（默认 `0`）
- `--binary`：`llama-server` 可执行文件名或绝对路径
- `--no-configure-agent`：只启动服务，不改 `~/.mini_nanobot/config.json`

切回远端 API（一键）：

```bash
python3 -m mini_nanobot use-remote \
  --api-base https://open.bigmodel.cn/api/paas/v4 \
  --model glm-4-flash \
  --api-key YOUR_API_KEY
```

如果不想覆盖已保存的 key，可省略 `--api-key`，会保留当前配置里的 key。

## 泊车分析示例

你可以直接在 chat 中让 agent 调用 `analyze_parking`：

```bash
python3 -m mini_nanobot chat -m "请分析这个泊车场景风险：车位宽2.5m长5.2m，车宽1.86m车长4.75m，左0.28m右0.36m前0.42m后0.35m，速度2.5km/h，摄像头遮挡0.2，传感器置信度0.9。"
```

如果你想强制结构化输入，也可以这样说：

```text
调用 analyze_parking，scenario={
  "slot_width_m": 2.5,
  "slot_length_m": 5.2,
  "vehicle_width_m": 1.86,
  "vehicle_length_m": 4.75,
  "left_clearance_m": 0.28,
  "right_clearance_m": 0.36,
  "front_clearance_m": 0.42,
  "rear_clearance_m": 0.35,
  "speed_kmh": 2.5,
  "sensor_confidence": 0.9,
  "camera_occlusion_ratio": 0.2,
  "obstacles": [{"name": "pillar", "distance_m": 0.31, "relative_direction": "left-rear"}]
}
```

工具会输出：
- 是否可停 (`fit_feasible`)
- 风险等级与风险分 (`risk_level`, `risk_score_0_to_100`)
- 空间/操作/感知子评分
- 关键余量和最近障碍物
- 可执行建议动作

## 泊车规划 Log 分析（含 GUI 图表）

`analyze_planning_log` 支持直接分析绝对路径日志（例如 J6B `planning.log.*`），会返回结构化诊断并生成 GUI 仪表盘 HTML。

```bash
python3 -m mini_nanobot chat -m "请分析这个日志：/Users/starktony/Downloads/J6B_LOG/planning.log.20260304164149，重点看规划稳定性和安全风险。"
```

显式工具调用示例：

```text
调用 analyze_planning_log，参数：
{
  "log_path": "/Users/starktony/Downloads/J6B_LOG/planning.log.20260304164149",
  "focus": "comprehensive",
  "save_report": true,
  "generate_dashboard": true,
  "report_dir": "reports",
  "max_lines": 200000,
  "evidence_limit": 8
}
```

不传 `report_dir` 时，默认输出到 `<log_path所在目录>/reports/`。

输出包含：
- `summary`, `risk_level`, `score_0_to_100`
- `key_metrics`（周期、抖动、重规划、轨迹几何指标等）
- `top_anomalies`（含证据行）
- `report_path`（JSON 报告）
- `dashboard_path`（单页 GUI 图表 HTML，含 Diagnosis / Planning Process Replay / Planner Inputs GridMap）
- `visualizations`（process replay / gridmap 状态、帧数、字段覆盖、CSV 探测结果）

### deterministic 单文件分析

```bash
python3 -m mini_nanobot analyze-log \
  --log-path /Users/starktony/Downloads/J6B_LOG/planning.log.20260304164149 \
  --profile j6b_default
```

多 log 合并成一次分析：

```bash
python3 -m mini_nanobot analyze-log \
  --log-path /Users/starktony/Downloads/J6B_LOG/planning.log.20260305110616 /Users/starktony/Downloads/J6B_LOG/planning.log.20260305110632
```

增强可视化参数：

```bash
python3 -m mini_nanobot analyze-log \
  --log-path /Users/starktony/Downloads/J6B_LOG/planning.log.20260304164149 \
  --planner-inputs-csv /Users/starktony/Downloads/J6B_LOG/planner_inputs.csv \
  --viz-backend matplotlib-svg
```

如果不传 `--planner-inputs-csv`，会自动探测 `<log_path目录>/planner_inputs.csv`。
默认后端是 `matplotlib-svg`。如果当前 Python 环境没有 `matplotlib`，会自动回退到 `canvas`。

可选关闭某一块图：
- `--no-process-replay`
- `--no-gridmap-view`

### deterministic 批量分析

```bash
python3 -m mini_nanobot batch-analyze-logs \
  --log-dir /Users/starktony/Downloads/J6B_LOG \
  --pattern 'planning.log*' \
  --recursive
```

批量模式同样支持：
- `--planner-inputs-csv`
- `--no-process-replay`
- `--no-gridmap-view`

支持 profile：
- `j6b_default`
- `conservative`
- `lenient`

也支持 `--profile-path /absolute/path/to/profile.json` 用 JSON 覆盖阈值。

## 目录说明

- `config.py`: 配置读写 + onboard
- `provider.py`: OpenAI 兼容 `/chat/completions` 调用
- `tools.py`: 工具定义与注册表
- `planning/`: planning log parser / profile / analyzer / dashboard
- `session.py`: JSONL 会话存储
- `agent.py`: tool-calling 主循环
- `cli.py`: 命令行入口
