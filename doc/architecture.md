# Nanobot 项目架构文档

## 1. 项目概述

**Nanobot** 是一个超轻量级的个人 AI 助手框架，核心代码仅约 4000 行，比传统 AI 助手框架小 99%。

### 核心特性
- **模块化设计**：高度可扩展，易于定制
- **多渠道支持**：支持 9+ 种聊天平台
- **灵活工具系统**：内置多种工具，支持自定义扩展
- **会话管理**：多用户、多渠道会话隔离
- **定时任务**：完整的 cron 定时任务系统
- **记忆系统**：基于 Markdown 的轻量级记忆管理

---

## 2. 项目结构

```
nanobot/
├── nanobot/                 # 核心 Python 包
│   ├── cli/                 # 命令行接口
│   │   └── commands.py      # CLI 命令实现
│   ├── agent/               # 代理核心
│   │   ├── loop.py          # 主循环
│   │   ├── context.py       # 上下文构建
│   │   ├── subagent.py      # 子代理管理
│   │   ├── memory.py        # 记忆管理
│   │   ├── skills.py        # 技能加载
│   │   ├── session.py       # 会话管理
│   │   └── tools/           # 工具实现
│   │       ├── base.py      # 工具基类
│   │       ├── registry.py  # 工具注册表
│   │       ├── filesystem.py
│   │       ├── shell.py
│   │       ├── web.py
│   │       ├── message.py
│   │       ├── spawn.py
│   │       └── cron.py
│   ├── bus/                 # 消息总线
│   │   └── queue.py         # 异步消息队列
│   ├── channels/            # 聊天渠道
│   │   ├── manager.py       # 渠道管理器
│   │   ├── whatsapp.py
│   │   ├── telegram.py
│   │   ├── feishu.py
│   │   ├── dingtalk.py
│   │   ├── discord.py
│   │   ├── email.py
│   │   ├── slack.py
│   │   ├── qq.py
│   │   └── mochat.py
│   ├── config/              # 配置系统
│   │   ├── schema.py        # Pydantic 配置模型
│   │   └── loader.py        # 配置加载
│   ├── providers/           # LLM 提供者
│   │   ├── base.py          # 提供者基类
│   │   ├── litellm_provider.py
│   │   └── registry.py
│   ├── cron/                # 定时任务
│   │   └── service.py
│   ├── heartbeat/           # 心跳服务
│   ├── session/             # 会话管理
│   │   └── manager.py
│   └── skills/              # 内置技能
│       ├── cron/
│       ├── github/
│       ├── memory/
│       ├── skill-creator/
│       ├── summarize/
│       ├── tmux/
│       └── weather/
├── bridge/                  # Node.js 桥接服务
├── tests/                   # 测试
├── doc/                     # 文档
├── workspace/               # 默认工作区模板
├── case/                    # 使用案例
├── pyproject.toml          # 项目配置
└── README.md
```

---

## 3. 主流程架构

### 3.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLI / Channels                              │
│  (WhatsApp, Telegram, Discord, Email, Feishu, DingTalk, Slack) │
└────────────┬────────────────────────────────────────────────────┘
             │
    ┌────────▼────────┐
    │   MessageBus    │ (Inbound/Outbound queues)
    └────────┬────────┘
             │
    ┌────────▼──────────┐
    │    AgentLoop      │ (Core processing engine)
    │  - ContextBuilder │ (System prompt + messages)
    │  - SessionManager │ (Conversation history)
    │  - ToolRegistry   │ (All available tools)
    │  - SubagentManager│ (Background task execution)
    └────────┬──────────┘
             │
    ┌────────▼──────────┐
    │    LLM Provider   │ (LiteLLM wrapper)
    │  (Claude, GPT-4,  │  supported)
    │   DeepSeek, etc.) │
    └────────┬──────────┘
             │
    ┌────────▼──────────┐
    │   Tool Execution  │ (Read, Write, Exec, Search, etc.)
    └────────────────────┘
```

### 3.2 消息处理流程

```
用户发送消息
    │
    ▼
[聊天渠道] ──解析消息──▶ Message {
    channel: "telegram",
    chat_id: "123456",
    content: "你好",
    ...
}
    │
    ▼
[MessageBus.inbound.put(message)]
    │
    ▼
[AgentLoop.run()] ◀────轮询获取消息
    │
    ▼
[AgentLoop._process_message(message)]
    │
    ├─▶ 会话管理
    │   SessionManager.get_or_create(
    │       channel, chat_id
    │   )
    │
    ├─▶ 命令处理 (如 /reset)
    │
    ├─▶ 记忆整合 (如需要)
    │   MemoryStore.consolidate()
    │
    ├─▶ 构建上下文
    │   ContextBuilder.build(
    │       system_prompt,    # 系统提示
    │       messages,         # 历史消息
    │       tools             # 可用工具
    │   )
    │
    ├─▶ 调用 LLM
    │   LLMProvider.call(
    │       messages,
    │       tools
    │   )
    │
    ├─▶ 处理响应
    │   ├─ 普通消息 ──▶ 直接返回
    │   └─ 工具调用 ──▶ 执行工具
    │       │
    │       ▼
    │       [Tool.execute()]
    │       │
    │       ▼
    │       继续调用 LLM (带工具结果)
    │       (循环直到无新工具调用)
    │
    └─▶ 发送响应
        MessageBus.outbound.put(response)
            │
            ▼
        [聊天渠道] ──▶ 用户
```

### 3.3 上下文构建流程

```
ContextBuilder.build()
    │
    ├─▶ 构建系统提示
    │   build_system_prompt()
    │   │
    │   ├─▶ 核心身份
    │   │   "You are an AI assistant..."
    │   │   "Time: 2025-01-20 10:30:00"
    │   │   "Workspace: /path/to/workspace"
    │   │
    │   ├─▶ 引导文件 (如存在)
    │   │   AGENTS.md ──读取──▶ 代理指令
    │   │   SOUL.md ────读取──▶ 个性定义
    │   │   USER.md ────读取──▶ 用户信息
    │   │   TOOLS.md ───读取──▶ 工具说明
    │   │   IDENTITY.md ──读取──▶ 身份定义
    │   │
    │   ├─▶ 内存上下文 (如存在)
    │   │   MEMORY.md ──读取──▶ 长期记忆
    │   │
    │   └─▶ 技能信息
    │       列出所有可用技能
    │
    ├─▶ 构建消息列表
    │   build_messages()
    │   │
    │   ├─▶ 历史消息
    │   │   从 Session 加载历史 (限制 memory_window)
    │   │
    │   ├─▶ 当前用户消息
    │   │   处理文本 + 媒体附件 (图片等)
    │   │
    │   └─▶ 工具结果 (如有)
    │       添加工具执行结果到消息列表
    │
    └─▶ 构建工具定义
        build_tools()
        │
        └─▶ 从 ToolRegistry 获取所有工具定义
            转换为 OpenAI 函数调用格式
```

---

## 4. 核心类详解

### 4.1 AgentLoop

**文件**: `nanobot/agent/loop.py`

**职责**: 核心处理引擎，负责消息处理、上下文构建、LLM 调用、工具执行。

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `run()` | 启动主循环，持续消费消息总线中的消息 |
| `_process_message()` | 处理单个消息，包括会话管理、命令处理、内存整合 |
| `_process_system_message()` | 处理系统消息（如子代理完成通知） |
| `_consolidate_memory()` | 当会话过长时，总结对话历史到 MEMORY.md |
| `process_direct()` | 直接处理消息（用于 CLI 和 cron 任务） |

**工具注册** (`_register_default_tools()`):
- 文件系统工具: `ReadFileTool`, `WriteFileTool`, `EditFileTool`, `ListDirTool`
- Shell 工具: `ExecTool`
- 网络工具: `WebSearchTool`, `WebFetchTool`
- 消息工具: `MessageTool`
- 子代理工具: `SpawnTool`
- 定时任务工具: `CronTool`

### 4.2 ContextBuilder

**文件**: `nanobot/agent/context.py`

**职责**: 构建 LLM 的完整上下文，包括系统提示、历史消息、工具定义。

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `build_system_prompt()` | 构建系统提示，包括核心身份、引导文件、内存上下文、技能信息 |
| `build_messages()` | 构建消息列表，包括历史记录、当前消息、工具结果 |
| `_build_user_content()` | 处理用户消息和媒体附件（支持图片） |
| `add_tool_result()` | 向消息列表添加工具执行结果 |
| `add_assistant_message()` | 添加助手消息，支持工具调用和推理内容 |

**引导文件** (按优先级排序):
1. `AGENTS.md` - 代理指令
2. `SOUL.md` - 个性定义
3. `USER.md` - 用户信息
4. `TOOLS.md` - 工具说明
5. `IDENTITY.md` - 身份定义

### 4.3 SubagentManager

**文件**: `nanobot/agent/subagent.py`

**职责**: 管理后台子代理执行，用于处理复杂任务。

**特点**:
- 轻量级代理实例，后台运行
- 共享 LLM 提供者，独立上下文
- 专注特定任务的系统提示
- 最大迭代次数限制（默认 15 次）

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `spawn()` | 生成新的子代理任务，返回任务ID |
| `_run_subagent()` | 执行子代理循环，包括工具调用和结果收集 |
| `_announce_result()` | 通过消息总线向主代理宣布结果 |
| `_build_subagent_prompt()` | 构建子代理特定的系统提示 |

**工具限制**: 子代理只能访问有限工具集（无消息工具和生成子代理工具）

### 4.4 ToolRegistry

**文件**: `nanobot/agent/tools/registry.py`

**职责**: 动态注册和管理工具，支持参数验证和执行。

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `register()` | 注册工具实例 |
| `get_tool()` | 获取工具实例 |
| `get_tool_definitions()` | 获取所有工具定义（OpenAI 格式） |
| `validate_params()` | 验证工具参数 |
| `execute()` | 执行工具调用 |

### 4.5 SessionManager

**文件**: `nanobot/session/manager.py`

**职责**: 管理用户会话，支持持久化和多会话隔离。

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `get_or_create()` | 获取或创建会话 |
| `load()` | 从磁盘加载会话 |
| `save()` | 保存会话到磁盘 |
| `reset()` | 重置会话历史 |

**会话键格式**: `{channel}:{chat_id}`

---

## 5. 启动流程详解

### 5.1 Gateway 模式启动流程

```
nanobot gateway
    │
    ▼
[commands.gateway()]
    │
    ├─▶ 加载配置
    │   ConfigLoader.load()
    │       ├─ 读取 ~/.nanobot/config.json
    │       └─ 合并环境变量
    │
    ├─▶ 初始化消息总线
    │   MessageBus()
    │       ├─ inbound queue
    │       └─ outbound queue
    │
    ├─▶ 创建 LLM 提供者
    │   ProviderRegistry.create(config)
    │       └─ 根据配置实例化提供者
    │
    ├─▶ 初始化会话管理器
    │   SessionManager(workspace)
    │
    ├─▶ 初始化定时任务服务
    │   CronService(bus, config)
    │
    ├─▶ 创建 AgentLoop 实例
    │   AgentLoop(config, bus, provider, session_manager)
    │       ├─ 初始化 ToolRegistry
    │       │   └─ _register_default_tools()
    │       └─ 初始化 SubagentManager
    │
    ├─▶ 初始化心跳服务
    │   HeartbeatService()
    │
    ├─▶ 初始化渠道管理器
    │   ChannelManager(config, bus)
    │       └─ 初始化所有启用的渠道
    │
    └─▶ 启动所有服务
        ├─ cron_service.start()
        ├─ heartbeat_service.start()
        ├─ agent.run()  (后台任务)
        └─ channels.start_all()  (阻塞)
```

### 5.2 Agent 模式启动流程

```
nanobot agent
    │
    ▼
[commands.agent()]
    │
    ├─▶ 加载配置
    │
    ├─▶ 创建 LLM 提供者
    │
    ├─▶ 创建 AgentLoop 实例 (direct_mode=True)
    │
    └─▶ 进入交互循环
        while True:
            ├─▶ 读取用户输入
            ├─▶ 检查退出命令 (exit/quit)
            ├─▶ 调用 AgentLoop.process_direct()
            └─▶ 显示响应
```

---

## 6. 关键设计模式

### 6.1 消息驱动架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Source    │────▶│  MessageBus  │────▶│   Handler   │
│ (Channels)  │     │  (Queues)    │     │(AgentLoop)  │
└─────────────┘     └──────────────┘     └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Subscribers │
                     │(Outbound Msgs)│
                     └──────────────┘
```

**优点**:
- 解耦消息生产者和消费者
- 支持异步处理
- 便于扩展和测试

### 6.2 会话隔离

```
Session Key: {channel}:{chat_id}

Example Sessions:
  - telegram:123456
  - whatsapp:654321
  - discord:999888

每个会话独立存储:
  - 会话历史 (JSON)
  - 工作区目录
  - 记忆文件 (MEMORY.md)
```

### 6.3 内存整合机制

```
当会话历史超过阈值 (默认 50 条):
    │
    ▼
调用 LLM 总结对话:
    Prompt: "Summarize this conversation..."
    │
    ▼
更新 MEMORY.md:
    追加总结内容
    │
    ▼
更新 HISTORY.md:
    记录整合历史
    │
    ▼
重置会话历史:
    保留最近 N 条
```

### 6.4 工具系统架构

```
┌──────────────────────────────────────┐
│          ToolRegistry                │
│  ┌──────────────────────────────┐    │
│  │      Tool Definitions        │    │
│  │  (OpenAI Function Schema)    │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │      Tool Instances          │    │
│  │  (ReadFile, WriteFile, etc.) │    │
│  └──────────────────────────────┘    │
└──────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │    BaseTool         │
    │  (Abstract Class)   │
    │  - name: str        │
    │  - description: str │
    │  - parameters: dict │
    │  - execute()        │
    └─────────────────────┘
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
┌───────┐ ┌───────┐ ┌───────┐
│ Read  │ │ Write │ │ Exec  │
└───────┘ └───────┘ └───────┘
```

---

## 7. 核心类详解

### 7.1 AgentLoop

**文件**: `nanobot/agent/loop.py`

**职责**: 核心处理引擎，负责消息处理、上下文构建、LLM 调用、工具执行。

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `run()` | 启动主循环，持续消费消息总线中的消息 |
| `_process_message()` | 处理单个消息，包括会话管理、命令处理、内存整合 |
| `_process_system_message()` | 处理系统消息（如子代理完成通知） |
| `_consolidate_memory()` | 当会话过长时，总结对话历史到 MEMORY.md |
| `process_direct()` | 直接处理消息（用于 CLI 和 cron 任务） |

**工具注册** (`_register_default_tools()`):
- 文件系统工具: `ReadFileTool`, `WriteFileTool`, `EditFileTool`, `ListDirTool`
- Shell 工具: `ExecTool`
- 网络工具: `WebSearchTool`, `WebFetchTool`
- 消息工具: `MessageTool`
- 子代理工具: `SpawnTool`
- 定时任务工具: `CronTool`

### 7.2 ContextBuilder

**文件**: `nanobot/agent/context.py`

**职责**: 构建 LLM 的完整上下文，包括系统提示、历史消息、工具定义。

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `build_system_prompt()` | 构建系统提示，包括核心身份、引导文件、内存上下文、技能信息 |
| `build_messages()` | 构建消息列表，包括历史记录、当前消息、工具结果 |
| `_build_user_content()` | 处理用户消息和媒体附件（支持图片） |
| `add_tool_result()` | 向消息列表添加工具执行结果 |
| `add_assistant_message()` | 添加助手消息，支持工具调用和推理内容 |

**引导文件** (按优先级排序):
1. `AGENTS.md` - 代理指令
2. `SOUL.md` - 个性定义
3. `USER.md` - 用户信息
4. `TOOLS.md` - 工具说明
5. `IDENTITY.md` - 身份定义

### 7.3 SubagentManager

**文件**: `nanobot/agent/subagent.py`

**职责**: 管理后台子代理执行，用于处理复杂任务。

**特点**:
- 轻量级代理实例，后台运行
- 共享 LLM 提供者，独立上下文
- 专注特定任务的系统提示
- 最大迭代次数限制（默认 15 次）

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `spawn()` | 生成新的子代理任务，返回任务ID |
| `_run_subagent()` | 执行子代理循环，包括工具调用和结果收集 |
| `_announce_result()` | 通过消息总线向主代理宣布结果 |
| `_build_subagent_prompt()` | 构建子代理特定的系统提示 |

**工具限制**: 子代理只能访问有限工具集（无消息工具和生成子代理工具）

### 7.4 ToolRegistry

**文件**: `nanobot/agent/tools/registry.py`

**职责**: 动态注册和管理工具，支持参数验证和执行。

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `register()` | 注册工具实例 |
| `get_tool()` | 获取工具实例 |
| `get_tool_definitions()` | 获取所有工具定义（OpenAI 格式） |
| `validate_params()` | 验证工具参数 |
| `execute()` | 执行工具调用 |

### 7.5 SessionManager

**文件**: `nanobot/session/manager.py`

**职责**: 管理用户会话，支持持久化和多会话隔离。

**主要方法**:

| 方法 | 说明 |
|-----|------|
| `get_or_create()` | 获取或创建会话 |
| `load()` | 从磁盘加载会话 |
| `save()` | 保存会话到磁盘 |
| `reset()` | 重置会话历史 |

**会话键格式**: `{channel}:{chat_id}`

---

## 8. 启动流程详解

### 8.1 Gateway 模式启动流程

```
nanobot gateway
    │
    ▼
[commands.gateway()]
    │
    ├─▶ 加载配置
    │   ConfigLoader.load()
    │       ├─ 读取 ~/.nanobot/config.json
    │       └─ 合并环境变量
    │
    ├─▶ 初始化消息总线
    │   MessageBus()
    │       ├─ inbound queue
    │       └─ outbound queue
    │
    ├─▶ 创建 LLM 提供者
    │   ProviderRegistry.create(config)
    │       └─ 根据配置实例化提供者
    │
    ├─▶ 初始化会话管理器
    │   SessionManager(workspace)
    │
    ├─▶ 初始化定时任务服务
    │   CronService(bus, config)
    │
    ├─▶ 创建 AgentLoop 实例
    │   AgentLoop(config, bus, provider, session_manager)
    │       ├─ 初始化 ToolRegistry
    │       │   └─ _register_default_tools()
    │       └─ 初始化 SubagentManager
    │
    ├─▶ 初始化心跳服务
    │   HeartbeatService()
    │
    ├─▶ 初始化渠道管理器
    │   ChannelManager(config, bus)
    │       └─ 初始化所有启用的渠道
    │
    └─▶ 启动所有服务
        ├─ cron_service.start()
        ├─ heartbeat_service.start()
        ├─ agent.run()  (后台任务)
        └─ channels.start_all()  (阻塞)
```

### 8.2 Agent 模式启动流程

```
nanobot agent
    │
    ▼
[commands.agent()]
    │
    ├─▶ 加载配置
    │
    ├─▶ 创建 LLM 提供者
    │
    ├─▶ 创建 AgentLoop 实例 (direct_mode=True)
    │
    └─▶ 进入交互循环
        while True:
            ├─▶ 读取用户输入
            ├─▶ 检查退出命令 (exit/quit)
            ├─▶ 调用 AgentLoop.process_direct()
            └─▶ 显示响应
```

---

## 9. 关键设计模式

### 9.1 消息驱动架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Source    │────▶│  MessageBus  │────▶│   Handler   │
│ (Channels)  │     │  (Queues)    │     │(AgentLoop)  │
└─────────────┘     └──────────────┘     └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Subscribers │
                     │(Outbound Msgs)│
                     └──────────────┘
```

**优点**:
- 解耦消息生产者和消费者
- 支持异步处理
- 便于扩展和测试

### 9.2 会话隔离

```
Session Key: {channel}:{chat_id}

Example Sessions:
  - telegram:123456
  - whatsapp:654321
  - discord:999888

每个会话独立存储:
  - 会话历史 (JSON)
  - 工作区目录
  - 记忆文件 (MEMORY.md)
```

### 9.3 内存整合机制

```
当会话历史超过阈值 (默认 50 条):
    │
    ▼
调用 LLM 总结对话:
    Prompt: "Summarize this conversation..."
    │
    ▼
更新 MEMORY.md:
    追加总结内容
    │
    ▼
更新 HISTORY.md:
    记录整合历史
    │
    ▼
重置会话历史:
    保留最近 N 条
```

### 9.4 工具系统架构

```
┌──────────────────────────────────────┐
│          ToolRegistry                │
│  ┌──────────────────────────────┐    │
│  │      Tool Definitions        │    │
│  │  (OpenAI Function Schema)    │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │      Tool Instances          │    │
│  │  (ReadFile, WriteFile, etc.) │    │
│  └──────────────────────────────┘    │
└──────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │    BaseTool         │
    │  (Abstract Class)   │
    │  - name: str        │
    │  - description: str │
    │  - parameters: dict │
    │  - execute()        │
    └─────────────────────┘
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
┌───────┐ ┌───────┐ ┌───────┐
│ Read  │ │ Write │ │ Exec  │
└───────┘ └───────┘ └───────┘
```

---

## 10. 扩展开发指南

### 10.1 添加新工具

```python
# nanobot/agent/tools/my_tool.py
from .base import Tool

class MyTool(Tool):
    name = "my_tool"
    description = "Description of what my tool does"
    parameters = {
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "Description of param1"
            }
        },
        "required": ["param1"]
    }

    async def execute(self, param1: str) -> dict:
        # 实现工具逻辑
        result = do_something(param1)
        return {
            "content": result,
            "is_error": False
        }
```

在 `AgentLoop._register_default_tools()` 中注册:

```python
self.tools.register(MyTool())
```

### 10.2 添加新渠道

```python
# nanobot/channels/my_channel.py
from .base import Channel

class MyChannel(Channel):
    def __init__(self, config: dict, bus: MessageBus):
        self.config = config
        self.bus = bus

    async def start(self):
        # 启动渠道连接
        # 监听消息并转发到总线

    async def stop(self):
        # 停止渠道连接

    async def send(self, message: Message):
        # 发送消息到用户
```

在配置中启用:

```json
{
  "channels": {
    "my_channel": {
      "enabled": true,
      "api_key": "..."
    }
  }
}
```

### 10.3 添加新 LLM 提供者

```python
# nanobot/providers/my_provider.py
from .base import LLMProvider

class MyProvider(LLMProvider):
    def __init__(self, config: dict):
        self.api_key = config.get("api_key")

    async def call(self, messages: list, tools: list = None, **kwargs):
        # 调用 LLM API
        response = await call_llm_api(
            messages=messages,
            tools=tools,
            api_key=self.api_key
        )
        return parse_response(response)
```

在 `ProviderRegistry` 中注册:

```python
registry.register("my_provider", MyProvider)
```

---

## 11. 总结

Nanobot 项目采用模块化、消息驱动的架构设计，具有以下核心特点：

1. **轻量级**: 核心代码仅约 4000 行，但功能完整
2. **可扩展**: 支持多种渠道、工具和 LLM 提供者的插件式扩展
3. **会话隔离**: 多渠道、多用户的独立会话管理
4. **记忆系统**: 自动整合长对话，维护长期记忆
5. **子代理**: 支持后台任务处理和并行执行

项目架构清晰，职责分明，易于理解和扩展，适合作为个人 AI 助手框架的基础。
