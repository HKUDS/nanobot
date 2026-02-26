# CLAUDE.md

## 项目简介

nanobot — 超轻量个人 AI 助手框架，核心代码约 3,500 行。Python 3.11+，MIT 协议。

配置文件：`~/.nanobot/config.json`，工作区：`~/.nanobot/workspace/`

## 全局命令

- 每次功能变更、bug 修复、代码合并等都采用 SDD，在 `specs/` 下新增/维护对应规格文档，命名统一为 `YYYY-MM-DD_描述`。

## 常用命令

```bash
# 安装
pip install -e .
pip install -e ".[dev]"

# 运行
nanobot agent -m "..."     # 单条消息
nanobot agent              # 交互式对话
nanobot gateway            # 启动所有渠道
nanobot status             # 查看配置状态

# 测试 & 检查
pytest
ruff check nanobot/
ruff format nanobot/
```

## 代码规范

- 全异步：所有 I/O 使用 `async`/`await`
- Tool 返回错误字符串，不抛异常
- 日志用 `loguru`（`from loguru import logger`）
- Ruff：line-length 100, target py311, select E/F/I/N/W, ignore E501
- pytest：`asyncio_mode = "auto"`
- 构建系统：hatchling

## 核心架构

```
Channel → InboundMessage → MessageBus → AgentLoop → LLM + Tools 循环 → OutboundMessage → Channel
```

关键模块：
- `agent/loop.py` — 主循环，接收消息、构建上下文、调用 LLM、执行工具
- `agent/context.py` — 组装 system prompt（身份 → bootstrap 文件 → 记忆 → 技能）
- `agent/memory.py` — 记忆管理，日记在 `memory/daily/YYYY-MM-DD.md`，长期记忆在 `MEMORY.md`
- `agent/skills.py` — 技能发现与加载（内置 `nanobot/skills/` + 用户 `~/.nanobot/workspace/skills/`）
- `agent/tools/` — 工具系统，继承 `Tool` 基类，实现 `name`/`description`/`parameters`/`execute()`
- `channels/` — 渠道适配，继承 `BaseChannel`，实现 `start()`/`stop()`/`send()`
- `providers/` — LLM 提供商，基于 LiteLLM，`ProviderSpec` 自动路由
- `config/schema.py` — Pydantic v2 配置模型

## 扩展方式

- **添加工具**：创建 `agent/tools/xxx.py` 继承 `Tool`，在 `AgentLoop._register_default_tools()` 注册
- **添加技能**：创建 `nanobot/skills/xxx/SKILL.md`（YAML frontmatter + markdown 指令）
- **添加渠道**：创建 `channels/xxx.py` 继承 `BaseChannel`，在 `config/schema.py` 加配置
- **添加提供商**：在 `providers/registry.py` 加 `ProviderSpec`，在 `config/schema.py` 加配置
