# 光谱 OS 外部 AI 接入指南

本文档说明如何将 OpenClaw、Dify、Coze 或任何外部 AI 平台接入光谱 OS 代理系统。

光谱 OS 通过 REST API（默认端口 8078）暴露所有操作。外部 AI 只需要能发 HTTP 请求即可接入。

---

## 接入模式

```
外部 AI (OpenClaw / Dify / Coze / ...)
    │
    │  HTTP POST/GET
    ▼
光谱 OS API (:8078)
    │
    ├─→ 创建课题
    ├─→ 触发代理
    ├─→ 查询状态
    └─→ 查看日志
```

外部 AI 充当「消息入口」，接收用户指令后调用光谱 OS API，由本地系统执行实际的数据库操作和 LLM 推理。

---

## 1. 前置条件

确保光谱 OS 已启动：

```bash
# 安装
pip install -e ".[dev]"

# 配置 .env（填入 API keys）
cp .env.example .env

# 启动
spectrum run
```

服务启动后，API 可用于 `http://<服务器IP>:8078/api/`。

---

## 2. API 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，返回启用的代理列表 |
| POST | `/api/projects` | 创建研究课题 |
| GET | `/api/projects` | 列出所有课题 |
| POST | `/api/trigger` | 触发指定代理执行一次 tick |
| GET | `/api/tasks` | 查询任务列表（可按 status/agent 过滤） |
| GET | `/api/stats` | 系统统计数据 |

---

## 3. 核心工作流

### 3.1 创建课题

用户通过外部 AI 提出研究需求，AI 调用 API 创建课题：

```bash
curl -X POST http://localhost:8078/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "scVI 单细胞分析综述",
    "domain": "生物信息学",
    "research_questions": "scVI 的核心原理是什么？与传统方法相比有何优势？",
    "scope": "聚焦 scVI 框架及其在单细胞 RNA-seq 中的应用",
    "output_type": "综述",
    "priority": "P1"
  }'
```

响应：

```json
{
  "id": 1,
  "name": "scVI 单细胞分析综述",
  "status": "未开始",
  "domain": "生物信息学",
  "priority": "P1",
  "output_type": "综述"
}
```

### 3.2 触发棱镜拆解

课题创建后，触发棱镜代理将其拆解为任务链：

```bash
curl -X POST http://localhost:8078/api/trigger \
  -H "Content-Type: application/json" \
  -d '{"agent": "prism"}'
```

响应：

```json
{
  "agent": "prism",
  "events": ["project_started:1"]
}
```

棱镜会自动创建 3 个任务：
- 采集（聚光，Todo）
- 分析（色散，Waiting，依赖采集）
- 产出（衍射，Waiting，依赖分析）

### 3.3 逐步触发流水线

```bash
# 触发聚光采集素材
curl -X POST http://localhost:8078/api/trigger \
  -H "Content-Type: application/json" \
  -d '{"agent": "focus"}'

# 采集完成后，调度器自动解锁分析任务
# 触发色散分析
curl -X POST http://localhost:8078/api/trigger \
  -H "Content-Type: application/json" \
  -d '{"agent": "dispersion"}'

# 分析完成后，触发衍射产出
curl -X POST http://localhost:8078/api/trigger \
  -H "Content-Type: application/json" \
  -d '{"agent": "diffraction"}'
```

> 如果系统已在 `spectrum run` 模式运行，调度器每 30 秒自动执行一次 tick，会自动触发所有代理。手动触发适用于需要立即执行的场景。

### 3.4 查询进度

```bash
# 查看所有任务
curl http://localhost:8078/api/tasks

# 按状态过滤
curl "http://localhost:8078/api/tasks?status=Doing"

# 按代理过滤
curl "http://localhost:8078/api/tasks?agent=focus"

# 系统总览
curl http://localhost:8078/api/stats
```

---

## 4. OpenClaw 接入示例

OpenClaw 有 4 个独立 bot，每个对应一个代理。每个 bot 的 function calling / plugin 配置如下：

### 4.1 棱镜 bot

负责接收用户课题并启动流水线。

配置两个 function：

**create_project**
```json
{
  "name": "create_project",
  "description": "创建一个新的研究课题",
  "parameters": {
    "type": "object",
    "properties": {
      "name": { "type": "string", "description": "课题名称" },
      "domain": { "type": "string", "description": "研究领域" },
      "research_questions": { "type": "string", "description": "核心研究问题" },
      "output_type": {
        "type": "string",
        "enum": ["综述", "教程", "笔记", "报告", "论文草稿"],
        "description": "期望产出类型"
      },
      "priority": {
        "type": "string",
        "enum": ["P1", "P2", "P3"],
        "description": "优先级"
      }
    },
    "required": ["name"]
  }
}
```

function 执行逻辑（伪代码）：

```python
import httpx

SPECTRUM_API = "http://localhost:8078/api"

async def create_project(name, domain="", research_questions="", output_type="综述", priority="P2"):
    async with httpx.AsyncClient() as client:
        # 1. 创建课题
        resp = await client.post(f"{SPECTRUM_API}/projects", json={
            "name": name,
            "domain": domain,
            "research_questions": research_questions,
            "output_type": output_type,
            "priority": priority,
        })
        project = resp.json()

        # 2. 立即触发棱镜拆解
        await client.post(f"{SPECTRUM_API}/trigger", json={"agent": "prism"})

        return f"课题「{name}」已创建 (ID: {project['id']})，棱镜正在拆解任务。"
```

**check_status**
```json
{
  "name": "check_status",
  "description": "查看系统状态和课题进度",
  "parameters": {
    "type": "object",
    "properties": {}
  }
}
```

```python
async def check_status():
    async with httpx.AsyncClient() as client:
        stats = (await client.get(f"{SPECTRUM_API}/stats")).json()
        projects = (await client.get(f"{SPECTRUM_API}/projects")).json()
        tasks = (await client.get(f"{SPECTRUM_API}/tasks")).json()

        lines = ["📊 系统状态:"]
        lines.append(f"  课题: {sum(stats['projects'].values())} 个")
        for s, c in stats['projects'].items():
            lines.append(f"    {s}: {c}")
        lines.append(f"  素材: {stats['sources']} | 知识卡: {stats['wiki_cards']} | 产出: {stats['outputs']}")

        if tasks:
            lines.append("\n📋 当前任务:")
            for t in tasks[:10]:
                lines.append(f"  [{t['status']}] {t['name']} → {t['assigned_agent']}")

        return "\n".join(lines)
```

### 4.2 聚光 / 色散 / 衍射 bot

这三个 bot 通常不需要用户直接交互，由调度器自动驱动。但如果需要手动触发：

```python
async def trigger_self(agent_name: str):
    """每个 bot 触发自己对应的代理"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{SPECTRUM_API}/trigger", json={"agent": agent_name})
        result = resp.json()
        events = result.get("events", [])
        if events:
            return f"执行完成，产生 {len(events)} 个事件: {', '.join(events)}"
        return "当前没有待处理的任务。"
```

---

## 5. Dify / Coze 接入

这些平台支持 HTTP 工具调用，配置方式类似：

### Dify

在工作流中添加「HTTP 请求」节点：

1. **创建课题节点**
   - 方法: POST
   - URL: `http://<服务器IP>:8078/api/projects`
   - Body: 从上游变量构建 JSON

2. **触发代理节点**
   - 方法: POST
   - URL: `http://<服务器IP>:8078/api/trigger`
   - Body: `{"agent": "prism"}`

3. **查询状态节点**
   - 方法: GET
   - URL: `http://<服务器IP>:8078/api/stats`

### Coze

在 Bot 中添加 Plugin，配置 API 端点：

```yaml
openapi: 3.0.0
info:
  title: 光谱 OS API
  version: 0.1.0
servers:
  - url: http://<服务器IP>:8078/api
paths:
  /projects:
    post:
      operationId: createProject
      summary: 创建研究课题
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [name]
              properties:
                name: { type: string }
                domain: { type: string }
                research_questions: { type: string }
                output_type: { type: string }
                priority: { type: string }
  /trigger:
    post:
      operationId: triggerAgent
      summary: 触发代理执行
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [agent]
              properties:
                agent: { type: string, enum: [prism, focus, dispersion, diffraction] }
  /stats:
    get:
      operationId: getStats
      summary: 获取系统统计
  /tasks:
    get:
      operationId: listTasks
      summary: 查询任务列表
      parameters:
        - name: status
          in: query
          schema: { type: string }
        - name: agent
          in: query
          schema: { type: string }
```

---

## 6. 自定义 AI 接入（通用 Python）

任何能发 HTTP 请求的 AI 框架都可以接入：

```python
import httpx

class SpectrumClient:
    """光谱 OS API 客户端"""

    def __init__(self, base_url: str = "http://localhost:8078/api"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=60)

    async def health(self) -> dict:
        return (await self.client.get("/health")).json()

    async def create_project(self, name: str, **kwargs) -> dict:
        return (await self.client.post("/projects", json={"name": name, **kwargs})).json()

    async def trigger(self, agent: str) -> dict:
        return (await self.client.post("/trigger", json={"agent": agent})).json()

    async def list_tasks(self, status: str = None, agent: str = None) -> list:
        params = {}
        if status: params["status"] = status
        if agent: params["agent"] = agent
        return (await self.client.get("/tasks", params=params)).json()

    async def stats(self) -> dict:
        return (await self.client.get("/stats")).json()

    async def run_full_pipeline(self, name: str, **project_kwargs) -> dict:
        """创建课题并触发完整流水线"""
        project = await self.create_project(name, **project_kwargs)
        await self.trigger("prism")
        return project

    async def close(self):
        await self.client.aclose()
```

使用示例：

```python
async def main():
    client = SpectrumClient("http://your-server:8078/api")

    # 创建课题 + 启动流水线
    project = await client.run_full_pipeline(
        "Transformer 架构演进",
        domain="深度学习",
        research_questions="从 Attention Is All You Need 到 GPT-4 的关键演进节点",
        output_type="综述",
        priority="P1",
    )
    print(f"课题已创建: {project['id']}")

    # 查看进度
    stats = await client.stats()
    print(stats)

    await client.close()
```

---

## 7. 生产环境注意事项

**网络安全**：API 默认监听 `0.0.0.0:8078`，生产环境建议：
- 通过 nginx 反向代理，限制来源 IP
- 或修改 `config/settings.yaml` 中 `api.host` 为 `127.0.0.1`，仅允许本机访问

**超时设置**：聚光代理的采集任务涉及联网搜索 + LLM 推理，单次 trigger 可能耗时 30-60 秒。外部 AI 调用时建议设置 `timeout=120`。

**自动 vs 手动**：`spectrum run` 启动后调度器每 30 秒自动 tick。如果只想手动控制，可以不启动调度器，仅用 API trigger 端点按需触发。
