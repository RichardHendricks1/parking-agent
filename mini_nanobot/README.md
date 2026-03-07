# mini_nanobot

一个可运行的最小版 Agent 骨架，核心只有：

- CLI (`onboard/chat`)
- OpenAI 兼容接口 provider
- 5 个工具：`read_file` / `write_file` / `exec` / `analyze_parking` / `analyze_planning_log`
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
  "post_tool_analysis_rounds": 2
}
```

`post_tool_analysis_rounds` 表示工具返回后，大模型会做几轮复核总结再给最终结论（默认 2 轮，可调大）。

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

输出包含：
- `summary`, `risk_level`, `score_0_to_100`
- `key_metrics`（周期、抖动、重规划、轨迹几何指标等）
- `top_anomalies`（含证据行）
- `report_path`（JSON 报告）
- `dashboard_path`（GUI 图表 HTML）

## 目录说明

- `config.py`: 配置读写 + onboard
- `provider.py`: OpenAI 兼容 `/chat/completions` 调用
- `tools.py`: 工具定义与注册表
- `session.py`: JSONL 会话存储
- `agent.py`: tool-calling 主循环
- `cli.py`: 命令行入口
