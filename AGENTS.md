# Repository Guidelines

## 项目目录

核心 Python 代码位于 `src/spectrum/`。v0.5.0 的 API 入口为 `api/research.py`，运行流程位于 `orchestrator/workflow.py`，运行服务与工作进程分别为 `orchestrator/service.py` 和 `orchestrator/worker.py`。数据库模型与会话位于 `db/research.py`、`db/runtime.py`；模型调用位于 `llm/research.py`；知识检索与对象存储位于 `tools/knowledge.py`、`tools/storage.py`。

Next.js、React、TypeScript 工作台位于 `frontend/`。Alembic 迁移位于 `migrations/`，真实服务集成检查位于 `checks/`。旧 `agents/`、调度器、静态 dashboard 和 `tests/` 保留为历史模块，新运行入口不使用旧调度机制。

新运行配置由 `runtime_config.py` 中的 `SPECTRUM_` 环境变量提供。密钥保存在 `.env`，不得提交。中间文件写入已忽略的 `.work/`。

## 安装、启动与检查

```bash
uv sync --extra dev --frozen
docker compose up -d postgres redis storage
uv run spectrum migrate
```

API、worker 和 beat 分别启动：`uv run spectrum run`、`uv run spectrum worker`、`uv run spectrum beat`。API 默认监听本机 8078 端口。前端执行 `npm ci --prefix frontend`、`npm run build --prefix frontend` 和 `npm run start --prefix frontend`，默认监听本机 3000 端口。

真实服务检查使用 `uv run pytest checks/ -v`，需要已启动 PostgreSQL、Redis、S3、API 和 worker。前端检查使用 `npm run typecheck --prefix frontend` 和 `npm run build --prefix frontend`。Python 使用 Ruff 检查；修改后的模块必须通过检查。完整验证边界见 `docs/v0.5.0-validation.md`。

## 架构

研究流程：简报 → 简报审核 → 采集与覆盖度评估 → 知识提炼 → 大纲 → 大纲审核 → 逐章节生成 → 审阅 → 文稿审核 → 产出。

- LangGraph 管理节点、条件分支和人工暂停，PostgreSQL 保存检查点。
- PostgreSQL 事务 outbox 与 Celery/Redis 分发研究运行，会话锁限制同一运行重复执行。
- 研究运行状态包括 `queued`、`running`、`waiting_review`、`completed`、`failed`、`cancelled`。同一课题同时只能存在一个活动运行。
- 人工审核必须携带当前 revision。确认内容保存独立版本，审核决定与阶段绑定。
- 模型调用在发送前预留预算，记录实际 Token、耗时和按配置单价计算的费用。结果未知的请求禁止自动重复发送。
- Tavily 负责搜索；Jina Reader 提取正文。材料进入对象存储及版本化片段表，使用本地 512 维嵌入模型、jieba 与 PostgreSQL 全文检索。
- 知识主张通过证据关系指向原文片段。引句必须完全匹配原文；文稿引用限定为本次运行的主张。
- Next.js 服务端代理注入 API 凭据，浏览器通过 SSE 读取进度。非本机 API 监听必须配置访问凭据。

## 数据库

`db/models.py` 保留课题、来源、知识卡、产出、旧任务、审计、标签和知识卡关系。`db/research.py` 增加研究运行、outbox、节点执行、原文版本、片段、主张、证据、文稿版本、审核和调用记录。

结构变更通过 Alembic 管理。SQLite 导入工具仅从原始文件读取数据，要求目标业务表为空，保留主键并检查数量与数据库约束。

## 约定

- 不硬删除研究记录，使用归档状态。
- 所有业务修改在事务内写入审计，调用 `db/runtime.py` 的 `audit()`；标题格式为 `动作｜目标库｜说明`。
- 状态或优先级修改设置审核标记；人工确认与系统执行分别记录操作者。
- 来源、知识卡、产出和运行保持课题关联；领域由课题输入传播。
- 人工修改保留版本，AI 输出不得覆盖已确认内容。
- Python 兼容 3.11+，使用 4 个空格、类型提示及 `snake_case` / `PascalCase` 命名，行宽目标 100。
- 直接导入依赖，错误在发生位置终止，不做静默降级。
- 验证连接真实服务并使用真实材料，不使用 mock 或虚构模型响应。

## 扩展运行流程

1. 在 `orchestrator/contracts.py` 定义经过校验的输入和模型输出。
2. 在 `orchestrator/workflow.py` 实现节点，纳入预算、幂等和证据约束。
3. 在 `build_graph()` 注册节点、分支与审核关系。
4. 结构变更增加迁移；配置变更更新 `.env.example` 与 README。
5. 使用真实服务核验失败、恢复、审核版本和审计行为。

## 贡献工作流

详细流程见 `CONTRIBUTING.md`。

- 所有变更通过 PR 合入 master，禁止直接 push。
- 分支前缀：`feat/`、`fix/`、`refactor/`、`docs/`、`test/`。
- 提交使用 Conventional Commits，描述使用中文，保持职责明确。
- 重大方向变更先提交 `docs/rfcs/` 下的 RFC。
- Bug 和架构改进通过 GitHub Issues 跟踪，演进方向通过 Milestones 管理。
- PR 说明用户可见变化、配置与迁移影响、验证结果和关联 Issue；界面修改提供实际截图。
