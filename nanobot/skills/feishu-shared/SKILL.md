---
name: feishu-shared
description: 飞书文档编排共享子技能模块。被 feishu-doc-orchestrator 和 feishu-wiki-orchestrator 共同引用，不直接使用。
metadata: {"nanobot": {"hidden": true}}
---

# 飞书共享子技能

本目录包含 `feishu-doc-orchestrator` 和 `feishu-wiki-orchestrator` 共用的子技能：

- `feishu-md-parser` — Markdown 解析为飞书块格式
- `feishu-block-adder` — 批量添加内容块到文档
- `feishu-doc-creator-with-permission` — 创建文档 + 权限管理
- `feishu-doc-verifier` — Playwright 文档验证
- `feishu-logger` — 创建日志记录

不要直接调用此技能，请使用 `feishu-doc-orchestrator` 或 `feishu-wiki-orchestrator`。
