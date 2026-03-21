> # 光谱 OS · 系统演进路线 — Agent 参考文档
>
> > 本文档供光谱 OS 各 Agent 及开发者参考，描述 v0.4.0 → v0.6.0+ 的演进方向、数据模型变更、接口变更和行为变更。
> >
> > 更新日期：2026-03-21 基于：ChatGPT 代码审计反馈 + Claude 架构讨论综合整理
> > 最近更新：2026-03-21 v0.4.0 知识层 + 色散 agent 接入完成
>
> ------
>
> ## 0 阅读指引
>
> 本文档分为三部分：
>
> 1. **现状问题清单**（第 1 节）— 已确认需要修复的 bug 和架构缺陷
> 2. **六大演进方向**（第 2 节）— 按依赖关系排列的功能演进设计
> 3. **版本路线与排期**（第 3 节）— 各方向落入哪个版本
>
> 与人类可读的路线图文档不同，本文档侧重：数据模型变更、Agent 行为变更、新增接口契约、配置项变更。
>
> ------
>
> ## 1 已确认问题清单
>
> ### 1.1 P0 — 必须修复
>
> | ID      | 问题                           | 影响范围                           | 修复方案                                                     |
> | ------- | ------------------------------ | ---------------------------------- | ------------------------------------------------------------ |
> | BUG-001 | Dashboard Agent 统计键值不一致 | `api/routes.py` dashboard 聚合逻辑 | 任务统计按 `assigned_agent` 英文 key 计数，回填 `AgentInfo` 时也用英文 key 查找，统一为 agent key |
> | BUG-002 | FTS 索引非实时                 | `db/operations.py` 写入链路        | ✅ 色散 agent 已在卡片创建时调用 `upsert_fts_entry()`；Source / Output 写入链路待补 |
> | BUG-003 | 配置与文档版本漂移             | `README.md` vs `pyproject.toml`    | ✅ 版本号已统一为 0.4.0；清理无实际使用逻辑的配置项待处理 |
>
> ### 1.2 P1 — 应尽快修复
>
> | ID       | 问题                        | 影响范围                         | 修复方案                                                     |
> | -------- | --------------------------- | -------------------------------- | ------------------------------------------------------------ |
> | ARCH-001 | 引用完整性依赖应用层        | `db/models.py` 全部 `*_ref` 字段 | 开启 `PRAGMA foreign_keys=ON`（在 `engine.py` 连接事件中设置），模型层补 `ForeignKey` 约束 |
> | ARCH-002 | Activity Log 约束不够系统级 | `db/operations.py` 全部写操作    | 方案 A：让 `@logged` 装饰器成为主写入路径；方案 B：在 `DatabaseOps` 基类的写方法中强制调用 `activity_logger.log()` |
> | ARCH-003 | Agent 异常路径覆盖不足      | `agents/*.py`                    | 补充集成测试：LLM 返回空 / 返回非 JSON / 截断 / 搜索全部失败 / Source 为空等边缘路径 |
>
> ------
>
> ## 2 六大演进方向
>
> ### 2.1 Human-in-the-Loop 改造
>
> **版本目标：v0.4.1**
>
> #### 2.1.1 AgentTask 状态机扩展
>
> 当前状态流：
>
> ```
> Waiting → Todo → InProgress → Done / Failed
> ```
>
> 新增 `Pending` 状态：
>
> ```
> Waiting → Todo → Pending（等人确认）→ InProgress → Done / Failed
>                     ↑
>                     └── 不需要确认的任务直接跳过 Pending
> ```
>
> **数据模型变更：**
>
> ```python
> # db/models.py — AgentTask
> class TaskStatus(str, Enum):
>     WAITING = "Waiting"
>     TODO = "Todo"
>     PENDING = "Pending"      # 新增
>     IN_PROGRESS = "InProgress"
>     DONE = "Done"
>     FAILED = "Failed"
> ```
>
> **Scheduler 行为变更：**
>
> ```python
> # orchestrator/scheduler.py — tick() 内
> # 现有逻辑：捡起所有 status=Todo 的任务交给 Agent
> # 新增逻辑：如果任务需要 checkpoint 确认，Agent 执行完 checkpoint 阶段后
> #           将 status 设为 Pending，scheduler 跳过 Pending 任务
> if task.status == TaskStatus.PENDING:
>     continue  # 等待人工确认
> ```
>
> #### 2.1.2 Checkpoint 机制
>
> **数据模型变更：**
>
> ```python
> # db/models.py — AgentTask 新增字段
> checkpoint = Column(JSON, nullable=True)  # Agent 写入中间产物
> checkpoint_type = Column(String, nullable=True)  # "research_brief" | "task_decomposition" | "outline" | "completion_review"
> ```
>
> **Agent 行为变更：**
>
> Agent 在关键节点产出中间结果后，不直接继续执行，而是：
>
> 1. 将中间产物写入 `task.checkpoint`
> 2. 设置 `task.checkpoint_type`
> 3. 将 `task.status` 设为 `Pending`
> 4. 返回，等待下一个 tick
>
> 人工确认后（通过 API），task.status 被推进到 `InProgress`，Agent 在下一个 tick 读取 checkpoint 继续执行。
>
> **四个卡点及其 checkpoint 内容：**
>
> | checkpoint_type      | 产出 Agent  | checkpoint 内容                                              | 人可编辑的字段       |
> | -------------------- | ----------- | ------------------------------------------------------------ | -------------------- |
> | `research_brief`     | Prism       | `{"core_questions": [...], "subtopics": [...], "expected_depth": "...", "quality_criteria": [...], "key_terms": [...]}` | 全部可编辑           |
> | `task_decomposition` | Prism       | `{"tasks": [{"name": "...", "type": "...", "agent": "...", "depends_on": [...], "message": "..."}]}` | 可删除/修改/新增任务 |
> | `outline`            | Diffraction | `{"sections": [{"title": "...", "depth": "概述/详述", "card_ids": [...]}]}` | 可调整顺序/深度/删除 |
> | `completion_review`  | Prism       | `{"coverage_score": N, "covered": [...], "gaps": [...], "recommendation": "..."}` | 决定接受/补充/调整   |
>
> **配置项变更：**
>
> ```yaml
> # config/settings.yaml 新增
> checkpoints:
>   research_brief: true        # brief 生成后暂停
>   task_decomposition: true    # 任务拆解后暂停
>   outline: true               # 衍射大纲后暂停
>   completion_review: true     # 完成审核暂停
> ```
>
> 每个卡点可单独开关。设为 `false` 时 Agent 跳过 Pending 直接继续。
>
> #### 2.1.3 新增 API 端点
>
> ```
> # 获取待确认任务列表
> GET /api/pending
> → 返回所有 status=Pending 的任务，含 checkpoint 内容
> 
> # 确认并推进任务（可附带修改后的 checkpoint）
> POST /api/pending/{task_id}/confirm
> Body: {"checkpoint": {...}}   # 可选，人工修改后的 checkpoint
> → 将 task.checkpoint 更新为提交内容，task.status 设为 InProgress
> 
> # 拒绝 / 要求重做
> POST /api/pending/{task_id}/reject
> Body: {"reason": "..."}
> → task.status 设为 Todo，Agent 重新执行该阶段
> 
> # 直接创建项目（Dashboard 操作化）
> POST /api/projects  # 已存在，确保 Dashboard 有对应表单
> 
> # 手动创建任务
> POST /api/tasks
> Body: {"name": "...", "type": "采集", "assigned_agent": "focus", "project_ref": 1, "message": "..."}
> 
> # 暂停/恢复项目自动调度
> PATCH /api/projects/{id}
> Body: {"paused": true}  # 新增 paused 字段
> ```
>
> #### 2.1.4 Dashboard 变更
>
> 新增页面/组件：
>
> - **「待我确认」队列视图**：区别于事后 review queue，这是事前决策队列
> - **Checkpoint 确认界面**：根据 checkpoint_type 渲染不同的编辑/确认 UI
>   - Brief 编辑器：可编辑 core_questions / subtopics / depth
>   - 任务链编辑器：可视化依赖关系，支持拖拽排序、删除、新增
>   - 大纲编辑器：章节列表，可调整顺序和深度标记
> - **项目创建表单**：直接在 Dashboard 创建项目
> - **项目暂停/恢复按钮**
>
> ------
>
> ### 2.2 算法知识收纳能力
>
> **版本目标：v0.4.1**
>
> #### 2.2.1 WikiCard Schema 扩展
>
> **数据模型变更：**
>
> ```python
> # db/models.py — WikiCard 新增字段
> extra = Column(JSON, nullable=True)  # 不同 type 的扩展信息
> ```
>
> **算法卡（type="方法" 或 "算法"）的 extra schema：**
>
> ```json
> {
>   "core_idea": "核心思路（一段文字）",
>   "formulas": "关键公式或伪代码",
>   "io_spec": "输入输出规格",
>   "complexity": "计算复杂度",
>   "applicable_scenarios": "适用场景与已知局限",
>   "paper_url": "论文引用 URL",
>   "repo_url": "代码仓库地址",
>   "dependencies": ["依赖的前置方法名称"],
>   "code_snippets": "核心代码片段"
> }
> ```
>
> **设计原则：** extra 字段保持通用性。未来 Dataset、Benchmark 等概念也可以作为特殊 type 的 WikiCard 存在，各自定义不同的 extra schema，不需要建专用表。
>
> #### 2.2.2 Dispersion Agent 变更
>
> **`llm/prompts.py` 变更：**
>
> 新增算法/方法类型卡片的生成 prompt 模板。当 Dispersion 判断 Source 内容为算法相关时，切换到算法卡模板，产出带 `extra` 结构化字段的卡片。
>
> **`agents/dispersion.py` 变更：**
>
> - 概念规划阶段：LLM 对每个概念标注 `card_type`（概念 / 方法 / 工具 / 算法）
> - 批量生成阶段：根据 `card_type` 选择不同的 prompt 模板
> - 算法卡生成时，prompt 明确要求输出 `extra` JSON 中的各字段
>
> **`agents/_parsing.py` 变更：**
>
> - `normalize_field()` 增加对 `extra` 字段的解析和校验
> - 如果 `extra` 解析失败，降级为普通卡片（不带 extra），不阻塞整个流程
>
> ------
>
> ### 2.3 手动输入通路（Manual Intake）
>
> **版本目标：v0.4.1**
>
> #### 2.3.1 新增 API 端点
>
> ```
> POST /api/intake
> Body: {
>   "input_type": "paper_url" | "repo_url" | "algorithm_name",
>   "value": "https://arxiv.org/abs/...",
>   "project_ref": 1,          // 可选，关联到某个课题
>   "notes": "人工备注"         // 可选
> }
> → 创建 AgentTask(type="intake", assigned_agent="focus", message=序列化的输入信息)
> → 返回 task_id
> ```
>
> #### 2.3.2 AgentTask 变更
>
> ```python
> # type 枚举新增
> "intake"  # 或 "手动采集"
> ```
>
> #### 2.3.3 Focus Agent 变更
>
> **`agents/focus.py` 新增 `process_intake_task()` 方法：**
>
> 根据 `input_type` 走不同提取路径：
>
> | input_type       | 提取流程                                                    | 产出                                |
> | ---------------- | ----------------------------------------------------------- | ----------------------------------- |
> | `paper_url`      | Jina/content_extractor 抓取正文 → 结构化提取                | Source (source_type="paper")        |
> | `repo_url`       | GitHub API 抓取 README + 核心模块 docstring + 依赖信息      | Source (source_type="repository")   |
> | `algorithm_name` | Focus 做一轮定向搜索（论文 + 代码仓库），找到后走上面两条路 | Source (source_type 视搜索结果而定) |
>
> **关键设计：** 手动输入最终都汇入同一条 Source → WikiCard 管线，不建第二套处理逻辑。Intake 任务完成后，如果有 project_ref，自动创建关联的 Dispersion 分析任务。
>
> #### 2.3.4 新增 GitHub 提取器
>
> **`tools/github_extractor.py`（新文件）：**
>
> ```python
> class GitHubExtractor:
>     """通过 GitHub API 提取仓库信息"""
> 
>     async def extract(self, repo_url: str) -> dict:
>         """
>         提取内容：
>         - README.md 全文
>         - 核心模块的 docstring（顶层 __init__.py 或 main 模块）
>         - pyproject.toml / setup.py / requirements.txt 的依赖信息
>         - repo 元信息（stars, language, license, last_updated）
>         返回结构化 dict，供 Focus 创建 Source 使用
>         """
> ```
>
> ------
>
> ### 2.4 衍射能力重构
>
> **版本目标：v0.5.0**
>
> #### 2.4.1 Section-as-Unit 架构（解决截断问题）
>
> **当前问题：** 每个 section 的 LLM 调用带前文上下文，文档越长留给当前 section 的输出空间越小，截断几乎必然。
>
> **重构方案：**
>
> ```
> 阶段 1：生成大纲（现有）
>     → 新增：为每个 section 分配 token 预算（根据 depth 按比例分）
>     → 新增：checkpoint 暂停，等人确认大纲（如果 checkpoints.outline=true）
> 
> 阶段 2：逐节展开（重构）
>     当前：每个 section 注入前文全文 + dedup context
>     改为：每个 section 独立生成，只注入：
>       - 该 section 需要的 WikiCard 子集（根据大纲中的 card_ids）
>       - 全局摘要（由大纲阶段生成，固定长度，不随文档增长）
>       - 上一节的最后 200 字（保持衔接，不变）
>     每个 section 独立存储（Output 新增 sections JSON 字段或子记录）
>     单个 section 失败只重试该 section
> 
> 阶段 3：组装
>     当前：section 内容已拼接在一起
>     改为：组装步骤只生成衔接过渡句，不重新生成内容
> ```
>
> **数据模型变更：**
>
> ```python
> # db/models.py — Output 新增字段（可选方案）
> sections = Column(JSON, nullable=True)
> # 结构：[{"title": "...", "content": "...", "word_count": N, "status": "done/failed"}]
> ```
>
> #### 2.4.2 多产出类型
>
> **AgentTask message 变更：**
>
> ```json
> {
>   "output_format": "review" | "comparison_table" | "quick_reference" | "domain_map" | "gap_analysis" | "research_proposal",
>   "...其他现有字段"
> }
> ```
>
> **Diffraction Agent 行为变更：**
>
> 根据 `output_format` 分流到不同的生成流程：
>
> | output_format       | 生成流程                                            | 预期长度 | 截断风险     |
> | ------------------- | --------------------------------------------------- | -------- | ------------ |
> | `review`            | 现有综述流程（section-as-unit 重构后）              | 长       | 低（重构后） |
> | `comparison_table`  | 单次 LLM 调用，输入多张算法卡，输出结构化对比表     | 短       | 无           |
> | `quick_reference`   | 单次 LLM 调用，输入单张算法卡 extra，压缩为一页速查 | 短       | 无           |
> | `domain_map`        | 输入 CardLink 关系数据，输出方法谱系描述            | 中       | 低           |
> | `gap_analysis`      | 输入知识池概况，分析覆盖度和空白                    | 中       | 低           |
> | `research_proposal` | 输入算法卡摘要 + CardLink，识别新方向               | 中       | 低           |
>
> **`llm/prompts.py` 变更：** 为每种 output_format 新增对应的 system prompt 模板。
>
> #### 2.4.3 输入来源扩展
>
> Diffraction 当前只读取 WikiCard。扩展后可读取：
>
> | 数据源                         | 用途                     | 查询方式                                  |
> | ------------------------------ | ------------------------ | ----------------------------------------- |
> | WikiCard                       | 知识卡片（现有）         | `project_ref` 或 `domain` 过滤            |
> | Source                         | 原始材料引用             | `project_ref` 过滤                        |
> | Output                         | 已有产出（综合报告输入） | `project_ref` 过滤                        |
> | ResearchProject.research_brief | 质量锚点                 | `project_id` 直接读取                     |
> | CardLink                       | 卡片间关系               | `source_card_id` 或 `target_card_id` 查询 |
>
> ------
>
> ### 2.5 知识累积与领域隔离
>
> **版本目标：v0.5.0**
>
> #### 2.5.1 领域知识池
>
> **核心概念：** WikiCard 拥有双重归属——既属于产生它的项目（`project_ref`），也属于某个领域知识池（`domain`）。项目有生命周期，知识池持续生长。
>
> **无数据模型变更。** `WikiCard.domain` 和 `ResearchProject.domain` 字段已存在，只需在 Agent 逻辑中启用。
>
> #### 2.5.2 Agent 知识池集成
>
> **Focus Agent 变更 — 搜索前预检：**
>
> ```python
> # agents/focus.py — plan 阶段新增
> async def _knowledge_pool_precheck(self, project: ResearchProject) -> str:
>     """查询同 domain 下已有知识，生成摘要注入搜索规划 prompt"""
>     existing_sources = await db_ops.list_sources(domain=project.domain, limit=50)
>     existing_cards = await db_ops.list_wiki_cards(domain=project.domain, limit=50)
>     # 生成摘要：已有 N 个 Source，覆盖子话题 [...], N 张 WikiCard，覆盖概念 [...]
>     # 注入到搜索规划 prompt，让 LLM 决定哪些方向可以跳过、哪些需要深挖
> ```
>
> **Dispersion Agent 变更 — 去重与增量更新：**
>
> ```python
> # agents/dispersion.py — 生成卡片前
> async def _check_existing_card(self, concept: str, domain: str) -> Optional[WikiCard]:
>     """按 concept + domain 查是否已有卡片"""
>     # 如果已有：走更新流程（补充新信息），不重复创建
>     # 如果没有：正常创建
> ```
>
> **Prism Agent 变更 — Brief 注入知识池概况：**
>
> ```python
> # agents/prism.py — research_brief 生成时
> # 在 prompt 中注入：
> # "该领域现有 {N} 张卡片，覆盖了这些子话题：[...]，尚未覆盖的方向有：[...]"
> # 让 brief 的质量随知识积累提升
> ```
>
> **Diffraction Agent 变更 — 跨项目引用：**
>
> ```python
> # agents/diffraction.py — 查询 WikiCard 时
> # 当前：只查 project_ref = current_project
> # 改为：查 project_ref = current_project 的卡片 + domain = current_domain 的卡片
> # 跨项目引用的卡片在产出中标注来源项目
> ```
>
> #### 2.5.3 Domain 一致性
>
> **新增 Domain 词典机制：**
>
> ```python
> # db/operations.py 新增
> async def get_existing_domains() -> List[str]:
>     """返回已有的所有 domain 值"""
> 
> async def match_domain(candidate: str, existing: List[str]) -> str:
>     """将候选 domain 与已有列表匹配，避免同义不同名"""
>     # 可以用 LLM 做语义匹配，或者简单的字符串相似度
> ```
>
> **Prism Agent 变更：** domain 推断后，先调用 `match_domain()` 与已有 domain 列表匹配，优先复用已有 domain 名，不每次自由生成。
>
> ------
>
> ### 2.6 研究构想自动生成
>
> **版本目标：v0.6.0+**
>
> **前置条件：** 2.2（算法知识收纳）+ 2.3（手动输入）+ 2.5（知识累积）充分落地，且已积累足够密度的高质量算法卡片和 CardLink 关系。
>
> #### 2.6.1 触发条件
>
> | 触发方式   | 条件                                       | 实现位置                                                     |
> | ---------- | ------------------------------------------ | ------------------------------------------------------------ |
> | 定期触发   | 某 domain 新增 N 张算法/方法类 WikiCard 后 | Prism tick() 中检查                                          |
> | 手动触发   | Dashboard 按钮 / API 调用                  | `POST /api/trigger {"agent": "diffraction", "task_type": "research_proposal", "domain": "..."}` |
> | 课题完成时 | Project 状态变为"完成"                     | Prism completion_review 之后                                 |
>
> #### 2.6.2 生成逻辑
>
> **输入：**
>
> - 该 domain 所有算法/方法类 WikiCard 的结构化摘要（concept + extra.core_idea + extra.applicable_scenarios + extra.dependencies）
> - CardLink 关系图
> - 已有的 gap_analysis 报告（如果有）
>
> **LLM 任务：**
>
> - 识别解决类似问题但用了不同假设的方法
> - 识别有互补优缺点可以组合的方法
> - 识别已知局限目前没有方法在处理的方向
> - 识别新数据模态还没有对应方法的空白
>
> **产出：**
>
> ```json
> // Output, type="research_proposal"
> {
>   "proposals": [
>     {
>       "direction": "构想方向名称",
>       "motivation": "基于哪些现有知识",
>       "hypothesis": "核心假设",
>       "method_path": "预期方法路径",
>       "validation": "潜在验证方案",
>       "related_cards": [card_id_1, card_id_2]
>     }
>   ]
> }
> ```
>
> 每条构想标记 `review_needed=True`。
>
> ------
>
> ## 3 版本路线
>
> ```
> v0.4.0 — 知识层基础 ✅ 已完成
> ├── ✅ DB schema: 层级标签 (tags) + 概念双链 (card_links) + FTS5 全文搜索 (fts_index)
> ├── ✅ CRUD: create_tag / tag_card / create_card_link / find_tag_by_name / upsert_fts_entry
> ├── ✅ 色散 agent 接入知识层：卡片创建后自动填充标签、双链、FTS 索引
> ├── ✅ BUG-002 部分修复：WikiCard 写入时实时索引 FTS
> ├── ✅ BUG-003 部分修复：版本号统一为 0.4.0
> ├── 🔲 BUG-001 修复：Dashboard Agent 统计键值
> ├── 🔲 ARCH-001 修复：FK 约束
> └── 🔲 ARCH-002 修复：Activity Log 强制化
>
> v0.4.1 — Human-in-the-Loop + 知识收纳
> ├── AgentTask 状态机：+Pending 状态 + checkpoint 字段
> ├── Research Brief 卡点（第一个可干预节点）
> ├── Dashboard 操作化：项目创建 + checkpoint 确认 + 待确认队列
> ├── WikiCard +extra JSON 字段
> ├── Dispersion 算法卡生成模板
> ├── POST /api/intake 端点
> ├── Focus process_intake_task()
> ├── GitHub 仓库提取器 (tools/github_extractor.py)
> └── ARCH-003 修复：Agent 异常路径测试
>
> v0.5.0 — 知识累积层
> ├── 领域知识池逻辑（domain 维度检索 + 去重）
> ├── Agent 知识池集成（Focus 预检 / Dispersion 去重 / Prism brief 注入 / Diffraction 跨项目引用）
> ├── Domain 词典维护机制
> ├── 衍射重构：section-as-unit 架构
> ├── 衍射：多产出类型（comparison_table / quick_reference / gap_analysis）
> └── 衍射：大纲卡点 + 输入来源扩展
>
> v0.6.0+ — 研究构想层
> ├── 研究构想自动生成
> ├── 知识图谱深化（方法谱系可视化）
> └── 具体范围视 v0.5.0 知识积累情况而定
> ```
>
> ------
>
> ## 4 贯穿性约束
>
> 以下原则适用于所有版本的所有变更：
>
> 1. **铁律不变** — 不删除、字段隔离、高风险审核、全程留痕。新功能必须遵守这四条。
> 2. **保持通用性** — 不将领域语义硬编码进数据模型。算法、数据集、Benchmark 都作为特殊类型的 WikiCard 存在。
> 3. **向后兼容** — 数据模型变更通过 `engine.py:_migrate_schema()` 处理，新增字段必须 `nullable=True` 或有默认值。
> 4. **可降级** — checkpoint 可通过配置关闭，知识池集成失败不阻塞主流程，新产出类型可回退到综述模式。
> 5. **全程留痕** — 新增的所有写操作（intake、checkpoint confirm/reject、domain 匹配）必须写 Activity Log。
>
> ------
>
> *— End of Document —*
