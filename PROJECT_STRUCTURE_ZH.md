# nanobot_zh 项目结构与文件功能详解

## 1. 项目定位

`nanobot_zh` 是一个轻量级 AI Agent 框架，核心能力是：
- 通过统一 Agent 循环处理消息与工具调用。
- 连接多种聊天渠道（Telegram、Discord、飞书、钉钉、Slack、QQ、Email、Matrix、WhatsApp 等）。
- 通过 Provider 抽象接入不同 LLM（LiteLLM、Azure OpenAI、OpenAI Codex、自定义 OpenAI 兼容接口）。
- 支持定时任务（Cron）、心跳唤醒（Heartbeat）、技能（Skills）、子代理（Subagent）和持久会话记忆。

## 2. 顶层目录说明

```text
nanobot_zh/
├─ nanobot/          # Python 主程序
├─ bridge/           # Node.js WhatsApp 桥接服务
├─ tests/            # 测试用例
├─ case/             # 演示动图资源
├─ README.md         # 使用说明
├─ pyproject.toml    # Python 包配置与依赖
├─ docker-compose.yml / Dockerfile
└─ SECURITY.md / LICENSE / COMMUNICATION.md
```

## 3. 启动与运行主链路

1. 入口：`python -m nanobot` 或 `nanobot` 命令。
2. CLI 层解析参数与交互输入（`nanobot/cli/commands.py`）。
3. 配置加载（`nanobot/config/loader.py`）并构建运行路径（`nanobot/config/paths.py`）。
4. 渠道管理器启动已启用渠道（`nanobot/channels/manager.py`）。
5. 渠道消息进入消息总线（`nanobot/bus/queue.py`）。
6. Agent 循环消费消息并调用 Provider 与工具（`nanobot/agent/loop.py`）。
7. 会话与记忆系统更新（`nanobot/session/manager.py`、`nanobot/agent/memory.py`）。
8. 结果经消息总线输出到具体渠道。

## 4. `nanobot/` 主包详解

## 4.1 入口与基础
- `nanobot/__main__.py`：模块运行入口。
- `nanobot/__init__.py`：包元信息。

## 4.2 Agent 核心（`nanobot/agent/`）
- `context.py`：构建系统提示词上下文（运行信息、技能、用户约束等）。
- `loop.py`：核心事件循环，处理消息、工具调用、取消任务、保存轮次。
- `memory.py`：短期/长期记忆归档与压缩逻辑。
- `skills.py`：技能发现、加载、解析与描述汇总。
- `subagent.py`：子代理的后台执行与结果回传。

## 4.3 工具系统（`nanobot/agent/tools/`）
- `base.py`：工具基类、参数校验、Schema 转换。
- `registry.py`：工具注册与检索。
- `filesystem.py`：读写改查文件目录（Read/Write/Edit/List）。
- `shell.py`：执行命令行工具。
- `web.py`：网页检索与抓取。
- `message.py`：主动发消息给用户。
- `cron.py`：创建/管理定时任务。
- `spawn.py`：创建后台子代理。
- `mcp.py`：连接 MCP 服务器并把外部工具包装成内部工具。

## 4.4 消息总线（`nanobot/bus/`）
- `events.py`：入站/出站事件定义。
- `queue.py`：异步消息队列，解耦渠道与 Agent。

## 4.5 渠道适配层（`nanobot/channels/`）
- `base.py`：渠道统一接口。
- `manager.py`：渠道生命周期管理。
- 具体渠道文件：
- `telegram.py`、`discord.py`、`slack.py`、`feishu.py`、`dingtalk.py`、`qq.py`、`matrix.py`、`email.py`、`mochat.py`、`whatsapp.py`
- 每个文件负责该平台的鉴权、收发消息、消息格式转换、平台特有行为处理。

## 4.6 配置系统（`nanobot/config/`）
- `schema.py`：Pydantic 配置模型（各渠道与 Provider 配置）。
- `loader.py`：配置加载、保存、迁移。
- `paths.py`：运行目录/工作区/日志/媒体等路径解析。

## 4.7 定时与心跳
- `cron/types.py`：Cron 数据模型。
- `cron/service.py`：任务调度与执行。
- `heartbeat/service.py`：周期唤醒 Agent 检查待办任务。

## 4.8 Provider 抽象（`nanobot/providers/`）
- `base.py`：Provider 接口、标准响应结构。
- `litellm_provider.py`：LiteLLM 多模型网关实现。
- `azure_openai_provider.py`：Azure OpenAI 实现。
- `openai_codex_provider.py`：OpenAI Codex Responses 接口实现。
- `custom_provider.py`：OpenAI 兼容 API 的直连实现。
- `transcription.py`：语音转写（Groq）能力。
- `registry.py`：Provider 元数据注册中心。

## 4.9 会话与工具函数
- `session/manager.py`：会话历史、消息归档、会话状态。
- `utils/helpers.py`：文件名安全化、token 估算、消息拆分、时间戳等通用函数。

## 4.10 模板与技能资源
- `templates/`：系统提示模板（AGENTS、SOUL、TOOLS、USER、HEARTBEAT、MEMORY）。
- `skills/`：内置技能文档与脚本。
- `skills/skill-creator/scripts/`：技能初始化、打包、快速校验脚本。

## 5. `bridge/`（Node.js WhatsApp Bridge）

- `bridge/src/index.ts`：Bridge 启动入口，处理进程退出信号。
- `bridge/src/server.ts`：本地 WebSocket 服务，连接 Python 与 WhatsApp 客户端，支持可选 token 鉴权。
- `bridge/src/whatsapp.ts`：基于 Baileys 的 WhatsApp 客户端封装，负责扫码登录、收发消息、媒体下载、自动重连。
- `bridge/src/types.d.ts`：类型声明补充。
- `package.json`：Node 侧依赖与构建脚本。

## 6. 测试目录（`tests/`）覆盖说明

测试以模块职责拆分，主要包括：
- Provider：`test_azure_openai_provider.py`、`test_provider_retry.py`
- 渠道：`test_*_channel.py`（钉钉、飞书、Slack、Telegram、QQ、Email、Matrix 等）
- Agent/Memory：`test_consolidate_offset.py`、`test_memory_consolidation_types.py`、`test_loop_*`
- 工具：`test_mcp_tool.py`、`test_message_tool*.py`、`test_tool_validation.py`
- 配置与 CLI：`test_config_*`、`test_commands.py`、`test_cli_input.py`
- 子功能：`test_task_cancel.py`、`test_heartbeat_service.py`、`test_cron_service.py`

## 7. 关键配置文件

- `pyproject.toml`
- 定义包名、版本、依赖、可选依赖（如 Matrix）、CLI 入口、打包策略、Ruff 与 Pytest 配置。
- `docker-compose.yml` / `Dockerfile`
- 容器化部署入口，便于网关服务运行。

## 8. 扩展建议（按当前架构）

1. 新增渠道：在 `nanobot/channels/` 新建实现并注册到管理器。
2. 新增工具：继承 `Tool` 并在 `ToolRegistry` 注册。
3. 新增模型提供方：在 `providers/` 增加 Provider 并更新 `registry.py`。
4. 新增技能：在 `nanobot/skills/` 新建 `SKILL.md`，可复用 `skill-creator` 脚本。

---
