# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/) 格式。

## [Unreleased]

## [0.4.0] - 2026-03-21

### 新增
- 知识层基础：层级标签、概念双链、FTS5 全文搜索
- 色散 agent 接入知识层：卡片创建后自动填充标签、双链、FTS 索引
- FTS 全文索引实时化（Source/Output 写入链路待补）

### 修复
- Dashboard Agent 统计键值不一致
- .env 环境变量未注入 os.environ 导致 LLM 连接失败
- FTS5 表损坏恢复 + Prism brief 生成错误日志增强
- SERPAPI_API_KEY 环境变量导出缺失

### 变更
- .env 加载改为通用方案，新增 API key 无需改代码
- 版本号统一为 0.4.0

## [0.3.3] - 2026-03-18

### 新增
- 截断修复 + 分批处理
- domain 传播机制
- PDF 导出功能

## [0.3.1] - 2026-03-18

### 新增
- 数据质量修复
- Pipeline 完善
- 搜索偏好控制

## [0.3.0] - 2026-03-18

### 新增
- Review 系统 + Output 发布 + 版本号集中管理
- 棱镜研究规划 + 三 agent 质量提升
- Explorer 深度管理界面：分页 API + 独立浏览页面
- 多源搜索 + 4 阶段采集流水线

### 变更
- 全面重写 README 反映 v0.3.0 功能现状

## [0.2.0] - 2026-03-18

### 新增
- 内容深度 + Pipeline 质量改进

### 修复
- tool loop 空响应问题
- 重试耗尽后将任务标记为 Failed
- 全链路错误处理增强：fallback 解析、空结果验证、自动重试
- 聚光 Agent JSON 解析失败

## [0.1.0] - 2026-03-17

### 新增
- 初始化光谱 OS 多智能体知识管线系统
- Dashboard + 一键部署
- 统一 LLM 调用为 OpenAI 兼容协议
