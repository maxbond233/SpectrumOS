# 贡献指南

感谢参与光谱 OS 的开发！本文档定义了代码修改和协作的规范流程。

## 分支命名

所有开发在独立分支上进行，命名格式：

| 前缀 | 用途 | 示例 |
|------|------|------|
| `feat/` | 新功能 | `feat/human-in-the-loop` |
| `fix/` | Bug 修复 | `fix/fts-realtime-index` |
| `refactor/` | 重构 | `refactor/llm-provider` |
| `docs/` | 文档 | `docs/governance` |
| `test/` | 测试 | `test/agent-edge-cases` |

## Commit 消息格式

遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范，描述使用中文：

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

类型：
- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 文档变更
- `refactor:` 重构（不改变外部行为）
- `test:` 测试
- `chore:` 构建/工具链变更

示例：
```
feat(dispersion): 算法卡片生成模板
fix: 修复 Dashboard Agent 统计键值不一致
docs: 更新 roadmap 进度 — v0.4.0 知识层标记完成
```

关联 Issue 时在 footer 中使用 `Closes #N` 或 `Refs #N`。

## Pull Request 工作流

**所有变更必须通过 PR 合入 master，禁止直接 push。** 这条规则对所有贡献者（包括 bot）生效。

1. 从 master 创建功能分支
2. 在分支上开发并提交
3. 推送分支并创建 PR
4. PR 标题遵循 Conventional Commits 格式
5. PR 描述中说明：做了什么、为什么、影响范围
6. 关联 GitHub Issue（`Closes #N`）
7. 确认测试通过后 merge

PR 模板会自动加载，按模板填写即可。

## RFC 流程

以下变更需要先提交 RFC（Request for Comments）：

- 新增 Agent
- 数据模型重构（`db/models.py` 结构性变更）
- 新的演进方向
- 跨模块的架构变更

流程：

1. 复制 `docs/rfcs/000-template.md` 为 `docs/rfcs/NNN-标题.md`（编号递增）
2. 填写 RFC 内容
3. 提交 PR，标题格式：`docs(rfc): NNN 标题`
4. 在 PR 中讨论
5. RFC 合入后开始实施，实施 PR 关联 RFC 编号

## 开发环境

```bash
# 安装
pip install -e ".[dev]"

# 启动
spectrum run  # 或 python -m spectrum.main

# 测试
pytest -v
pytest tests/test_db/ -v              # 按模块
pytest tests/test_db/test_operations.py::test_create_and_get_project -v  # 单个

# 代码检查
ruff check src/ tests/
ruff format src/ tests/
```

## 版本发布

版本号在 `pyproject.toml` 中集中管理。每次 PR merge 后在 `CHANGELOG.md` 的 `[Unreleased]` section 追加变更记录，版本发布时归档到对应版本号下。
