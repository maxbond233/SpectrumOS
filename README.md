# 光谱 OS · Spectrum OS

> v0.3.0 — SQLite-backed multi-agent knowledge pipeline

4 个 AI 代理按「课题 → 采集 → 分析 → 产出」流水线协作，通过 Agent Board 异步交接任务，所有操作记录到 Activity Log。内置 Dashboard 总控台与 Explorer 数据浏览器。

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
| 💠 聚光 | 采集器 | 多源联网搜索 → 提取正文 → 创建 Sources 记录 |
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

## 功能亮点

- **Dashboard 总控台** — 代理状态、6 库统计、最近活动，一屏总览（`/`）
- **Explorer 数据浏览器** — 分页浏览 Sources / Wiki Cards / Outputs / Tasks / Logs，支持筛选与详情查看（`/explorer`）
- **Review 审批系统** — AI 变更自动标记 `review_needed`，统一审批队列 `/api/reviews`
- **Output 发布** — Markdown 下载 + HTML 渲染预览，支持打印样式
- **多源搜索** — 4 个搜索 provider 并发执行，URL 去重 + 分数加权，Jina Reader 正文提取
- **人工干预** — 所有核心表支持 PATCH 端点，手动修正状态/优先级

## 技术栈

- Python 3.11+, asyncio
- SQLite + SQLAlchemy 2.x async + aiosqlite
- OpenAI 兼容接口 (Claude / DeepSeek / Qwen)
- FastAPI + Uvicorn (API + Web UI, 端口 8078)
- Typer (CLI)
- 搜索: Tavily / SerpAPI / Semantic Scholar / Perplexity
- 正文提取: Jina Reader API + regex fallback
- Markdown 渲染: `markdown` (tables, fenced_code, toc)
- httpx, pydantic-settings, tenacity, PyYAML

## 项目结构

```
src/spectrum/
├── main.py                # 入口：调度器 + FastAPI 并行启动
├── cli.py                 # CLI: run / trigger / status / create-project / logs
├── config.py              # Pydantic Settings (YAML + .env)
├── _version.py            # 版本号 (importlib.metadata)
│
├── db/                    # 数据层 (SQLite)
│   ├── engine.py          # 异步引擎 + session 工厂
│   ├── models.py          # 6 张表的 ORM 模型
│   ├── operations.py      # CRUD（无 delete — 铁律）
│   └── activity_log.py    # 审计日志记录器 + @logged 装饰器
│
├── llm/                   # LLM 集成
│   ├── provider.py        # ABC + OpenAICompatProvider
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
│   ├── web_search.py      # 多源搜索协调器 (URL 去重 + 分数加权)
│   ├── search_providers.py # Tavily / SerpAPI / Semantic Scholar / Perplexity
│   └── content_extractor.py # Jina Reader + regex fallback
│
├── orchestrator/
│   ├── scheduler.py       # 轮询调度 + tick 循环
│   ├── event_bus.py       # 进程内异步事件总线
│   └── pipeline.py        # 流水线阶段定义
│
├── dashboard/
│   ├── dashboard.html     # 总控台 SPA (/)
│   ├── explorer.html      # 数据浏览器 SPA (/explorer)
│   └── spectrum-os.service # systemd 服务文件
│
└── api/
    ├── app.py             # FastAPI 应用工厂 + 静态页面路由
    ├── routes.py          # 全部 API 端点
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
CLAUDE_API_KEY=sk-xxx              # Claude via OpenAI-compatible
CLAUDE_BASE_URL=https://...        # 兼容接口地址
DEEPSEEK_API_KEY=sk-xxx            # DeepSeek (可选)
DEEPSEEK_BASE_URL=https://...      # DeepSeek 接口地址 (可选)
TAVILY_API_KEY=tvly-xxx            # 聚光搜索 — Tavily
```

代理模型配置在 `config/settings.yaml`，可为每个代理指定不同的 provider/model/temperature。

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

## API 端点

所有端点挂载在 `/api` 前缀下。

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，返回已注册代理列表 |
| POST | `/api/trigger` | 触发代理 `{"agent": "prism"}` |
| GET | `/api/stats` | 系统统计（各表计数 + 状态分布） |
| GET | `/api/dashboard/stats` | Dashboard 聚合数据（代理状态、6 库统计、最近记录） |

### 课题 (Projects)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 课题列表 |
| POST | `/api/projects` | 创建课题 |
| GET | `/api/projects/{id}` | 课题详情 |
| PATCH | `/api/projects/{id}` | 更新课题（status / priority / review_needed） |

### 任务 (Tasks)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 任务列表（可选 `?status=&agent=`） |
| GET | `/api/tasks/browse` | 分页浏览任务（支持 status / agent / type / project_ref 筛选） |
| PATCH | `/api/tasks/{id}` | 更新任务（status / review_needed） |

### 素材 (Sources)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sources` | 手动添加素材 |
| GET | `/api/sources/list` | 分页浏览素材（支持 status / domain / project_ref 筛选） |
| GET | `/api/sources/{id}` | 素材详情 |
| PATCH | `/api/sources/{id}` | 更新素材（status / priority / review_needed） |

### 知识卡 (Wiki Cards)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/wiki-cards` | 分页浏览知识卡（支持 type / domain / maturity / project_ref 筛选） |
| GET | `/api/wiki-cards/{id}` | 知识卡详情 |
| PATCH | `/api/wiki-cards/{id}` | 更新知识卡（maturity / needs_review） |

### 产出 (Outputs)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/outputs` | 分页浏览产出（支持 status / type / project_ref 筛选） |
| GET | `/api/outputs/{id}` | 产出详情 |
| PATCH | `/api/outputs/{id}` | 更新产出（status / review_needed） |
| GET | `/api/outputs/{id}/markdown` | 下载 Markdown 文件 |
| GET | `/api/outputs/{id}/html` | HTML 渲染预览 |

### 审批 & 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/reviews` | 统一审批队列（跨 5 张表汇总 review_needed 记录） |
| GET | `/api/logs` | 分页浏览活动日志（支持 actor / action_type / target_db 筛选） |

## Web 界面

启动后浏览器访问 `http://localhost:8078`：

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | Dashboard 总控台 | 代理运行状态、6 库数据统计、最近活动一屏总览 |
| `/explorer` | Explorer 数据浏览器 | 分页浏览所有数据表，支持筛选、详情查看、Markdown 渲染 |

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

```
路径: /opt/spectrum-os/agents/
端口: 8078 (API + Dashboard + Explorer)
服务: systemd spectrum-os.service
```
