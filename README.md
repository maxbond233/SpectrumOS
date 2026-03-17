# 光谱 OS · Spectrum OS

基于 SQLite 的多智能体知识管线系统。4 个 AI 代理按「课题 → 采集 → 分析 → 产出」流水线协作，通过 Agent Board 异步交接任务，所有操作记录到 Activity Log。

## 架构

```
Kuro ──→ Research Projects ──→ 🔮 棱镜（拆解+调度）
                                   │
                         ┌─────────┼─────────┐
                         ▼         ▼         ▼
                      Sources    Wiki     Outputs
                      💠 聚光   🌈 色散   🌊 衍射
                       采集       分析       产出
                         │         │         │
                         └─────────┼─────────┘
                                   ▼
                            Agent Board
                          （任务调度+交接）
                                   │
                                   ▼
                           Activity Log
                           （全程审计）
```

### 代理职责

| 代理 | 角色 | 说明 |
|------|------|------|
| 🔮 棱镜 | 协调器 | 扫描新课题 → 拆解为任务链 → 监控流水线进度 |
| 💠 聚光 | 采集器 | 联网搜索素材 → 提取摘要 → 创建 Sources 记录 |
| 🌈 色散 | 分析器 | 读取素材 → 提炼概念 → 创建 Wiki 知识卡 |
| 🌊 衍射 | 产出器 | 读取知识卡 → 合成文稿 → 创建 Outputs 记录 |

### 任务依赖链

棱镜创建任务时自动建立链式依赖：

```
Task A (采集, 聚光, Status=Todo)
Task B (分析, 色散, Status=Waiting, Depends On=A)
Task C (产出, 衍射, Status=Waiting, Depends On=B)
```

调度器每个 tick（30s）检查：若依赖任务全部 Done，则 Waiting → Todo。

## 技术栈

- Python 3.11+, asyncio
- SQLite + SQLAlchemy async + aiosqlite
- Anthropic SDK (Claude) + OpenAI 兼容接口 (DeepSeek/Qwen)
- FastAPI + Uvicorn (API, 端口 8078)
- Typer (CLI)
- Tavily / SerpAPI (聚光联网搜索)

## 项目结构

```
src/spectrum/
├── main.py                # 入口：调度器 + FastAPI 并行启动
├── cli.py                 # CLI: run / trigger / status / create-project / logs
├── config.py              # Pydantic Settings (YAML + .env)
│
├── db/                    # 数据层 (SQLite)
│   ├── engine.py          # 异步引擎 + session 工厂
│   ├── models.py          # 6 张表的 ORM 模型
│   ├── operations.py      # CRUD（无 delete — 铁律）
│   └── activity_log.py    # 审计日志记录器 + @logged 装饰器
│
├── llm/                   # LLM 集成
│   ├── provider.py        # ABC + AnthropicProvider + OpenAICompatProvider
│   ├── client.py          # 统一客户端（按代理选 provider）
│   └── prompts.py         # 各代理系统提示词
│
├── agents/                # 代理实现
│   ├── base.py            # AgentBase — tick/process_task 生命周期
│   ├── prism.py           # 🔮 棱镜
│   ├── focus.py           # 💠 聚光
│   ├── dispersion.py      # 🌈 色散
│   └── diffraction.py     # 🌊 衍射
│
├── tools/
│   └── web_search.py      # Tavily/SerpAPI 封装
│
├── orchestrator/
│   ├── scheduler.py       # 轮询调度 + tick 循环
│   ├── event_bus.py       # 进程内异步事件总线
│   └── pipeline.py        # 流水线阶段定义
│
└── api/
    ├── app.py             # FastAPI 应用工厂
    ├── routes.py          # 端点: /health, /trigger, /projects, /tasks, /stats
    └── schemas.py         # 请求/响应模型
```

## 快速开始

### 1. 安装

```bash
pip install -e ".[dev]"
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 API keys
```

`.env` 需要的密钥：

```
ANTHROPIC_API_KEY=sk-ant-xxx        # Claude API
OPENAI_COMPAT_API_KEY=sk-xxx        # DeepSeek/Qwen (可选)
OPENAI_COMPAT_BASE_URL=https://...  # 兼容接口地址 (可选)
TAVILY_API_KEY=tvly-xxx             # 聚光联网搜索
```

代理模型配置在 `config/settings.yaml`，可为每个代理指定不同的 provider/model。

### 3. 启动

```bash
# 启动调度器 + API 服务
spectrum run

# 或直接
python -m spectrum.main
```

### 4. 使用

```bash
# 创建课题
spectrum create-project "scVI 单细胞分析" --domain "生物信息学" --priority P1

# 手动触发代理
spectrum trigger prism

# 查看状态
spectrum status

# 查看日志
spectrum logs
```

### API 端点

```
GET  /api/health              # 健康检查
POST /api/trigger             # 触发代理 {"agent": "prism"}
GET  /api/projects            # 课题列表
POST /api/projects            # 创建课题
GET  /api/tasks?status=&agent= # 任务列表
GET  /api/stats               # 系统统计
```

## 运行测试

```bash
pytest -v
```

## 系统铁律

- **AI 不直接删除** — 只能新建、补充、标记、建议归档
- **字段写入隔离** — AI 字段与人工字段分离
- **高风险需审核** — 状态/优先级变更标记 Review Needed
- **全程留痕** — 所有操作写入 Activity Log
- **课题驱动** — 所有采集、分析、产出必须关联 Research Project

## 部署

与现有 Dashboard（端口 8077）并行部署：

```
路径: /opt/spectrum-os/agents/
端口: 8078
服务: systemd spectrum-agents
```

OpenClaw 的 4 个 bot 通过 `POST /api/trigger` 触发对应代理执行。
