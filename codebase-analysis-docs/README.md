# nanobot 代码库文档导航

本目录包含 nanobot 代码库的完整知识文档，供开发者或 LLM 实现功能、修复 bug、安全重构时参考。

| 文档 | 内容 | 适用场景 |
|------|------|---------|
| [CODEBASE_KNOWLEDGE.md](./CODEBASE_KNOWLEDGE.md) | 项目概述、核心模块详解、开发指南、常见陷阱 | **首要参考**：理解项目全貌和各模块职责 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 分层架构图、消息总线、记忆压缩状态机、工具执行管道、安全模型 | 理解系统设计和数据流 |
| [API_REFERENCE.md](./API_REFERENCE.md) | 工具 JSON Schema、LLMProvider API、BaseChannel API、配置参考、Skill 格式 | 实现新工具、渠道、Provider 时查阅 |

## 快速索引

- **添加新渠道** → CODEBASE_KNOWLEDGE.md §5.1 + API_REFERENCE.md §3
- **添加新 LLM Provider** → CODEBASE_KNOWLEDGE.md §5.2 + API_REFERENCE.md §2
- **添加新工具** → CODEBASE_KNOWLEDGE.md §5.3 + API_REFERENCE.md §1
- **创建 Skill** → CODEBASE_KNOWLEDGE.md §5.4 + API_REFERENCE.md §6
- **理解记忆压缩** → CODEBASE_KNOWLEDGE.md §3.3 + ARCHITECTURE.md §4
- **调试并发问题** → CODEBASE_KNOWLEDGE.md §2.3 + ARCHITECTURE.md §2
- **配置参考** → API_REFERENCE.md §4

## 代码库信息

- **版本**：0.1.4.post5
- **主要入口**：`nanobot/cli/commands.py`（typer CLI）
- **核心引擎**：`nanobot/agent/loop.py`（AgentLoop）
- **测试**：`pytest`，433 个用例，asyncio_mode=auto
- **Lint**：`ruff check nanobot/`（100 字符行长，rules: E F I N W）
