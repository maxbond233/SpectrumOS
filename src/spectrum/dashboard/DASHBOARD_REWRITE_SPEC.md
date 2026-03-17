# Dashboard HTML 重写规格

## 目标

重写 `dashboard.html`，从 Notion API 迁移到本地 SQLite API（`/api/dashboard/stats`），增加干预功能。

## 数据源

唯一数据接口：`GET /api/dashboard/stats`

返回结构：
```json
{
  "timestamp": "ISO datetime",
  "agents": [
    {"name": "棱镜", "key": "prism", "emoji": "🔮", "role": "总控", "role_en": "Orchestrator", "color": "#10b981", "active": true, "task_count": 3}
  ],
  "databases": {
    "projects":     { "total": 5, "primary": {"未开始":2,"进行中":3}, "secondary": {"domain":{...},"priority":{...}}, "review_needed": 1, "recent": [{"id":1,"name":"...","status":"...","title":"..."}] },
    "sources":      { "total": 10, "primary": {"Collected":5,...}, "secondary": {"domain":{...},"source_type":{...}}, ... },
    "wiki":         { "total": 8, "primary": {"Seed":3,"Growing":4,"Stable":1}, "secondary": {"domain":{...},"type":{...}}, ... },
    "outputs":      { "total": 2, "primary": {"未开始":1,"进行中":1}, "secondary": {"type":{...}}, ... },
    "tasks":        { "total": 15, "primary": {"Todo":5,"Doing":3,...}, "secondary": {"type":{...},"agent":{...}}, ... },
    "activity_log": { "total": 50, "primary": {"Create":20,"Update":30}, "secondary": {"actor":{...},"target_db":{...}}, ... }
  }
}
```

## 干预 API

| 动作 | 方法 | 端点 | Body |
|------|------|------|------|
| 触发代理 | POST | `/api/trigger` | `{"agent": "prism"}` |
| 添加素材 | POST | `/api/sources` | `{"title":"...", "url":"...", "source_type":"", "domain":"", "project_ref": null}` |
| 创建课题 | POST | `/api/projects` | `{"name":"...", "domain":"", "research_questions":"", "output_type":"综述", "priority":"P2"}` |
| 更新任务 | PATCH | `/api/tasks/{id}` | `{"status":"Done"}` 或 `{"review_needed": false}` |

## 保留的 CSS

保留现有文件中的全部 CSS 变量、暗色主题、ambient 动画、字体引用。以下 CSS class 保持不变：
- `.ambient`, `.container`, `.hero`, `.hero-badge`, `.hero h1`, `.hero p`, `.live-dot`, `.update-time`
- `.stats`, `.stat`, `.stat-label`, `.stat-value`, `.stat-sub`, `.stat-bar`, `.stat-bar-seg`
- `.section`, `.section-header`, `.db-grid`, `.db-card`, `.db-head`, `.db-icon`, `.db-name`, `.db-count`, `.db-breakdown`, `.db-chip`, `.db-bar`, `.db-bar-seg`, `.db-recent`, `.db-recent-title`, `.db-recent-item`
- `.agent-grid`, `.agent-card`, `.agent-emoji`, `.agent-name`, `.agent-role`, `.agent-tasks`, `.dot`, `.dot-on`, `.dot-off`
- `.flow-container`, `.flow-row`, `.flow-dot`, `.flow-name`, `.flow-line`, `.flow-desc`, `.flow-count`, `.flow-indent`, `.flow-arrow`
- `.rules-grid`, `.rule-card`, `.footer`, `.error-box`, `.loading`, `.spinner`
- 所有响应式 media query

## 需要修改的 CSS

### 新增样式

```css
/* Stats 行改为 6 列 */
.stats { grid-template-columns: repeat(6, 1fr); }
@media(max-width:768px) { .stats { grid-template-columns: repeat(3, 1fr); } }
@media(max-width:480px) { .stats { grid-template-columns: repeat(2, 1fr); } }

/* Agent grid 改为 4 列 */
.agent-grid { grid-template-columns: repeat(4, 1fr); }
@media(max-width:768px) { .agent-grid { grid-template-columns: repeat(2, 1fr); } }

/* DB grid 改为 3 列 */
.db-grid { grid-template-columns: repeat(3, 1fr); }
@media(max-width:768px) { .db-grid { grid-template-columns: repeat(2, 1fr); } }
@media(max-width:480px) { .db-grid { grid-template-columns: 1fr; } }

/* Agent trigger button */
.agent-trigger { margin-top: .5rem; padding: 3px 10px; font-size: .6rem; font-family: var(--mono); background: none; border: 1px solid var(--bd); border-radius: 6px; color: var(--t2); cursor: pointer; transition: all .2s; }
.agent-trigger:hover { color: var(--t1); border-color: var(--bd2); background: var(--bg3); }

/* Task status toggle in recent items */
.task-status-btn { padding: 1px 6px; font-size: .55rem; border-radius: 8px; font-family: var(--mono); cursor: pointer; border: 1px solid; background: none; transition: all .2s; }
.task-status-btn:hover { opacity: .8; }

/* Intervention forms */
.intervention { margin-bottom: 2.5rem; }
.form-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.form-card { background: var(--bg2); border: 1px solid var(--bd); border-radius: var(--r); padding: 1.2rem 1.4rem; }
.form-card h3 { font-size: .82rem; font-weight: 500; margin-bottom: .8rem; }
.form-row { margin-bottom: .6rem; }
.form-row label { display: block; font-size: .6rem; font-family: var(--mono); color: var(--t3); text-transform: uppercase; letter-spacing: .5px; margin-bottom: .2rem; }
.form-row input, .form-row select, .form-row textarea { width: 100%; padding: 6px 10px; font-size: .75rem; font-family: var(--sans); background: var(--bg); border: 1px solid var(--bd); border-radius: var(--r-sm); color: var(--t1); outline: none; transition: border-color .2s; }
.form-row input:focus, .form-row select:focus, .form-row textarea:focus { border-color: var(--purple); }
.form-row select { appearance: none; }
.form-row textarea { resize: vertical; min-height: 50px; }
.form-submit { padding: 6px 16px; font-size: .72rem; font-family: var(--mono); background: var(--purple); color: #fff; border: none; border-radius: var(--r-sm); cursor: pointer; transition: opacity .2s; }
.form-submit:hover { opacity: .85; }
.form-submit:disabled { opacity: .4; cursor: not-allowed; }

/* Toast */
.toast-container { position: fixed; top: 1rem; right: 1rem; z-index: 1000; display: flex; flex-direction: column; gap: .5rem; }
.toast { padding: .6rem 1rem; border-radius: var(--r-sm); font-size: .75rem; font-family: var(--sans); animation: fadeUp .3s ease; max-width: 320px; }
.toast-success { background: rgba(16,185,129,.15); border: 1px solid rgba(16,185,129,.3); color: var(--green); }
.toast-error { background: rgba(239,68,68,.15); border: 1px solid rgba(239,68,68,.3); color: var(--red); }
```

## HTML 结构变更

### 1. 移除
- `<div class="notion-links" id="notion-links"></div>` — 整个 Notion 链接栏
- Footer 中的 "Powered by Notion" 行

### 2. Stats 行：4 列 → 6 列

```html
<div class="stats" id="stats-row">
  <div class="stat"><div class="stat-label">Projects</div><div class="stat-value" id="stat-projects" style="color:var(--green)">-</div><div class="stat-sub" id="stat-projects-sub">loading...</div><div class="stat-bar" id="stat-projects-bar"></div></div>
  <div class="stat"><div class="stat-label">Sources</div><div class="stat-value" id="stat-sources" style="color:var(--amber)">-</div><div class="stat-sub" id="stat-sources-sub">loading...</div><div class="stat-bar" id="stat-sources-bar"></div></div>
  <div class="stat"><div class="stat-label">Wiki</div><div class="stat-value" id="stat-wiki" style="color:var(--purple)">-</div><div class="stat-sub" id="stat-wiki-sub">loading...</div><div class="stat-bar" id="stat-wiki-bar"></div></div>
  <div class="stat"><div class="stat-label">Outputs</div><div class="stat-value" id="stat-outputs" style="color:var(--pink)">-</div><div class="stat-sub" id="stat-outputs-sub">loading...</div><div class="stat-bar" id="stat-outputs-bar"></div></div>
  <div class="stat"><div class="stat-label">Tasks</div><div class="stat-value" id="stat-tasks" style="color:var(--blue)">-</div><div class="stat-sub" id="stat-tasks-sub">loading...</div><div class="stat-bar" id="stat-tasks-bar"></div></div>
  <div class="stat"><div class="stat-label">Activity</div><div class="stat-value" id="stat-log" style="color:var(--cyan)">-</div><div class="stat-sub" id="stat-log-sub">loading...</div><div class="stat-bar" id="stat-log-bar"></div></div>
</div>
```

### 3. Agent 矩阵：5 → 4 个，加 Trigger 按钮

去掉准直（🔦），每个 agent card 底部加：
```html
<button class="agent-trigger" onclick="triggerAgent('prism')">▶ Trigger</button>
```

### 4. 数据库卡片：4 → 6 个

改 `<a>` 为 `<div>`（不再链接到 Notion），6 张卡片：

| key | 图标 | 名称 | primary 分组字段 | secondary 分组 |
|-----|------|------|-----------------|---------------|
| projects | 🔬 | Research Projects | status | domain, priority |
| sources | 📚 | Sources | status | domain, source_type |
| wiki | 🧠 | Wiki | maturity | domain, type |
| outputs | 📄 | Outputs | status | type |
| tasks | 📋 | Tasks | status | type, agent |
| activity_log | 📝 | Activity Log | action_type | actor, target_db |

Tasks 卡片的 recent items 中，每条加一个状态切换按钮：
```html
<button class="task-status-btn" onclick="updateTaskStatus(ID, 'Done')" style="color:${sc};border-color:${sc}30">→Done</button>
```

### 5. 干预区（新增 section，放在数据库卡片之后）

```html
<div class="section intervention">
  <div class="section-header">
    <h2>🎛️ 干预</h2>
    <span class="tag">Intervention</span>
  </div>
  <div class="form-grid">
    <!-- 添加素材 -->
    <div class="form-card">
      <h3>📚 添加素材</h3>
      <div class="form-row"><label>标题 *</label><input id="src-title" placeholder="文章/论文标题"></div>
      <div class="form-row"><label>URL</label><input id="src-url" placeholder="https://..."></div>
      <div class="form-row"><label>类型</label><select id="src-type"><option value="">--</option><option>论文</option><option>文章</option><option>视频</option><option>书籍</option><option>工具</option></select></div>
      <div class="form-row"><label>领域</label><select id="src-domain"><option value="">--</option><option>生物信息</option><option>AI</option><option>编程</option><option>数学</option><option>英语</option><option>科研方法</option></select></div>
      <div class="form-row"><label>关联课题</label><select id="src-project"></select></div>
      <button class="form-submit" onclick="submitSource()">提交素材</button>
    </div>
    <!-- 创建课题 -->
    <div class="form-card">
      <h3>🔬 创建课题</h3>
      <div class="form-row"><label>名称 *</label><input id="proj-name" placeholder="课题名称"></div>
      <div class="form-row"><label>领域</label><select id="proj-domain"><option value="">--</option><option>生物信息</option><option>AI</option><option>编程</option><option>数学</option><option>英语</option><option>科研方法</option></select></div>
      <div class="form-row"><label>研究问题</label><textarea id="proj-questions" placeholder="核心问题，每行一个"></textarea></div>
      <div class="form-row"><label>产出类型</label><select id="proj-output"><option>综述</option><option>教程</option><option>笔记</option><option>报告</option><option>论文草稿</option></select></div>
      <div class="form-row"><label>优先级</label><select id="proj-priority"><option>P2</option><option>P1</option><option>P3</option></select></div>
      <button class="form-submit" onclick="submitProject()">创建课题</button>
    </div>
  </div>
</div>
```

### 6. 数据流更新

```html
<div class="flow-row"><div class="flow-dot" style="background:var(--green)"></div><span class="flow-name">🔬 Projects</span><div class="flow-line"></div><span class="flow-desc">课题拆解 → 任务分配</span><span class="flow-count" style="color:var(--green)">${db.projects.total}</span></div>
<div class="flow-row flow-indent"><span class="flow-arrow">↳</span><div class="flow-dot" style="background:var(--amber)"></div><span class="flow-name">📚 Sources</span><div class="flow-line"></div><span class="flow-desc">采集 → 摘要</span><span class="flow-count" style="color:var(--amber)">${db.sources.total}</span></div>
<div class="flow-row flow-indent"><span class="flow-arrow" style="padding-left:1.5rem">↳</span><div class="flow-dot" style="background:var(--purple)"></div><span class="flow-name">🧠 Wiki</span><div class="flow-line"></div><span class="flow-desc">概念提炼</span><span class="flow-count" style="color:var(--purple)">${db.wiki.total}</span></div>
<div class="flow-row flow-indent"><span class="flow-arrow" style="padding-left:3rem">↳</span><div class="flow-dot" style="background:var(--pink)"></div><span class="flow-name">📄 Outputs</span><div class="flow-line"></div><span class="flow-desc">综合产出 → 审核</span><span class="flow-count" style="color:var(--pink)">${db.outputs.total}</span></div>
```

### 7. Footer

```html
<div class="footer">
  <p>光谱 OS · Spectrum Operating System · Built with 🔮 棱镜</p>
</div>
```

### 8. Toast 容器

在 `<body>` 开头加：
```html
<div class="toast-container" id="toast-container"></div>
```

## JavaScript 重写

### 颜色映射

保留现有 `STATUS_COLORS` 和 `DOMAIN_COLORS`，不变。

### 保留的工具函数

`makeBar(counts, total, colorMap)`、`makeChips(counts, colorMap)` — 不变。

### 修改 `makeRecent(items)`

去掉 `<a href="${item.url}">` 链接，改为 `<span>`（不再有 Notion URL）。

### 修改 `loadData()`

```javascript
async function loadData() {
  try {
    document.getElementById('update-time').innerHTML = '<span class="live-dot"></span>fetching...';
    const resp = await fetch('/api/dashboard/stats');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    renderStats(data);
    renderAgents(data);
    renderDatabases(data);
    renderFlow(data);
    populateProjectDropdown(data);

    const ts = new Date(data.timestamp);
    document.getElementById('update-time').innerHTML =
      `<span class="live-dot"></span>Last updated: ${ts.toLocaleString('zh-CN')}`;
  } catch (err) {
    console.error(err);
    document.getElementById('update-time').innerHTML =
      `<span style="color:var(--red)">⚠ ${err.message}</span>`;
    document.getElementById('db-grid').innerHTML =
      `<div class="error-box" style="grid-column:1/-1">连接失败: ${err.message}</div>`;
  }
}
```

### 修改 `renderStats(data)`

适配 6 列，数据从 `data.databases.projects/sources/wiki/outputs/tasks/activity_log` 读取。每个 stat 的 sub 文本显示 primary 分组中前 2-3 个值 + review_needed 数。

### 修改 `renderAgents(data)`

从 `data.agents` 读取（已是 AgentInfo 数组），不再从 `data.databases.tasks.agent` 取 task count。每个卡片加 Trigger 按钮。不再 `onclick` 打开 Notion。

### 修改 `renderDatabases(data)`

6 张卡片，`<div>` 而非 `<a>`。每张卡片：
- bar 用 `primary` 字段
- chips 用 `primary` + 第一个 `secondary` 字段
- recent 用 `recent` 数组
- tasks 卡片的 recent 条目加状态切换按钮

### 删除 `renderLinks(data)`

不再需要。

### 新增 `populateProjectDropdown(data)`

用 `data.databases.projects.recent` 填充 `#src-project` 下拉框（`<option value="">无</option>` + 每个 project 的 `<option value="${id}">${name}</option>`）。

### 新增 `triggerAgent(key)`

```javascript
async function triggerAgent(key) {
  try {
    const resp = await fetch('/api/trigger', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({agent: key})
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed');
    showToast(`${key} triggered: ${data.events.length} events`, 'success');
    loadData();
  } catch (err) {
    showToast(err.message, 'error');
  }
}
```

### 新增 `submitSource()`

```javascript
async function submitSource() {
  const title = document.getElementById('src-title').value.trim();
  if (!title) return showToast('标题不能为空', 'error');
  const body = {
    title,
    url: document.getElementById('src-url').value.trim(),
    source_type: document.getElementById('src-type').value,
    domain: document.getElementById('src-domain').value,
    project_ref: document.getElementById('src-project').value ? parseInt(document.getElementById('src-project').value) : null,
  };
  try {
    const resp = await fetch('/api/sources', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    if (!resp.ok) throw new Error('Failed');
    showToast(`素材已添加: ${title}`, 'success');
    document.getElementById('src-title').value = '';
    document.getElementById('src-url').value = '';
    loadData();
  } catch (err) {
    showToast(err.message, 'error');
  }
}
```

### 新增 `submitProject()`

```javascript
async function submitProject() {
  const name = document.getElementById('proj-name').value.trim();
  if (!name) return showToast('名称不能为空', 'error');
  const body = {
    name,
    domain: document.getElementById('proj-domain').value,
    research_questions: document.getElementById('proj-questions').value.trim(),
    output_type: document.getElementById('proj-output').value,
    priority: document.getElementById('proj-priority').value,
  };
  try {
    const resp = await fetch('/api/projects', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    if (!resp.ok) throw new Error('Failed');
    showToast(`课题已创建: ${name}`, 'success');
    document.getElementById('proj-name').value = '';
    document.getElementById('proj-questions').value = '';
    loadData();
  } catch (err) {
    showToast(err.message, 'error');
  }
}
```

### 新增 `updateTaskStatus(taskId, newStatus)`

```javascript
async function updateTaskStatus(taskId, newStatus) {
  try {
    const resp = await fetch(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status: newStatus})
    });
    if (!resp.ok) throw new Error('Failed');
    showToast(`任务 #${taskId} → ${newStatus}`, 'success');
    loadData();
  } catch (err) {
    showToast(err.message, 'error');
  }
}
```

### 新增 `showToast(message, type)`

```javascript
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}
```

### 自动刷新

保持 `loadData()` + `setInterval(loadData, 60000)`。
