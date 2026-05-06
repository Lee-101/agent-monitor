# Agent Monitor

设备运行状态与智能体框架监测系统。实时追踪硬件指标（CPU、GPU、内存、磁盘、网络、温度）以及 AI 智能体框架（Claude Code、Hermes Agent、Codex、Open Claw）的运行状态，通过 Web 仪表板展示。

## 快速开始

```bash
# 安装（开发模式）
git clone https://github.com/Lee-101/agent-monitor.git
cd agent-monitor
pip install -e .

# 启动服务
agent-monitor
# 或
python -c "from agent_monitor.main import main; main()"

# 浏览器访问
# http://127.0.0.1:8501
```

### 可选参数

```bash
agent-monitor --port 9000 --host 0.0.0.0 --debug
agent-monitor -c /path/to/config.yaml
```

### 可选依赖

```bash
# NVIDIA GPU 监控
pip install -e ".[nvidia]"

# 桌面通知
pip install -e ".[alerting]"
```

## 项目结构

```
agent-monitor/
├── pyproject.toml              # 项目配置与依赖
├── agent-monitor.yaml          # 主配置文件（服务器、采集器、存储、告警）
├── alert_rules.yaml            # 告警规则
├── data/                       # 运行时数据（SQLite、日志）
├── src/agent_monitor/
│   ├── main.py                 # 入口：CLI + 服务启动
│   ├── config.py               # YAML 配置加载
│   ├── collectors/             # 数据采集层（插件架构）
│   │   ├── base.py             # 抽象基类：MetricPoint, CollectorResult, BaseCollector
│   │   ├── registry.py         # 采集器注册中心与调度
│   │   ├── system.py           # CPU/内存/磁盘/网络/温度
│   │   ├── gpu.py              # NVIDIA GPU (nvidia-smi)
│   │   ├── process.py          # 进程级监控
│   │   ├── hermes.py           # Hermes Agent 采集器
│   │   ├── claude_code.py      # Claude Code 采集器
│   │   ├── codex.py            # Codex 采集器
│   │   ├── openclaw.py         # Open Claw 采集器（桩）
│   │   └── log_analyzer.py     # 日志尾随 + 模式匹配
│   ├── storage/
│   │   ├── sqlite_store.py     # SQLite 存储（WAL 模式）
│   │   ├── schema.sql          # 数据库 Schema
│   │   └── retention.py        # 数据保留策略
│   ├── api/
│   │   ├── server.py           # FastAPI 应用
│   │   ├── websocket.py        # WebSocket 实时推送
│   │   └── routes/             # REST API 路由
│   ├── alerting/
│   │   ├── engine.py           # 规则评估引擎
│   │   ├── rules.py            # 告警规则解析
│   │   └── notifiers.py        # 通知器（桌面/日志/Webhook）
│   └── dashboard/
│       ├── templates/          # Jinja2 HTML 模板
│       └── static/             # 静态资源
└── tests/
```

## 仪表板

三栏布局的赛博朋克风格 Web 仪表板：

- **左栏（380px）** — 系统状态仪表盘（CPU/内存/GPU/温度弧形仪表）、详细指标、网络/磁盘 I/O、告警
- **中栏** — 智能体状态卡片（Claude Code、Hermes、Codex、Open Claw），显示运行状态、会话、Token、费用
- **右栏（340px）** — 智能体资源堆叠条、磁盘使用率、实时事件日志流

智能体详情页（`/agents/{name}`）提供仪表盘式指标展示、Token 消耗分析、模型配置、会话信息和趋势图。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/current` | 最新系统指标 |
| GET | `/api/gpu/current` | 最新 GPU 指标 |
| GET | `/api/agents` | 所有智能体状态 |
| GET | `/api/agents/{name}` | 智能体详情 |
| GET | `/api/agents/{name}/history` | 智能体历史 |
| GET | `/api/alerts` | 告警列表 |
| POST | `/api/alerts/{id}/acknowledge` | 确认告警 |
| WS | `/ws/live` | 实时指标流（2秒间隔） |

## 采集器架构

所有采集器继承 `BaseCollector` 抽象基类，通过 `CollectorRegistry` 注册和调度：

- `is_available()` 返回 False 的采集器自动跳过（如 Open Claw 未安装时）
- 每个采集器在独立 asyncio 任务中运行，间隔可配置
- 采集结果通过回调写入 SQLite 并通过 WebSocket 广播

## 告警

规则定义在 `alert_rules.yaml`，支持条件表达式、持续时间、严重级别。内置 8 条规则覆盖 CPU/内存/GPU 温度/磁盘/智能体状态。

## 配置

`agent-monitor.yaml` 支持配置：

- `server` — host、port、debug
- `collectors` — 每个采集器的启用状态和采集间隔
- `storage` — 数据库路径、保留天数、聚合开关
- `alerting` — 启用状态、规则文件、通知器
- `dashboard` — 标题、刷新间隔

环境变量覆盖：`AGENT_MONITOR_PORT`、`AGENT_MONITOR_HOST`、`AGENT_MONITOR_DB`。
