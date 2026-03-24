# nanobot 项目理解笔记

这份笔记按中文、细节化的方式总结了这次对 `nanobot` 项目的梳理结果。重点覆盖：

- `gateway`、`AgentLoop`、`cron`、`heartbeat` 的关系
- 内置工具、外部 MCP 工具、skills 的区别
- prompt 的真实组成
- 消息历史如何进入上下文
- 自动归档、长期记忆、session 持久化的机制
- 以及我们这次为了调试加上的 `first_all_chat.json`

## 1. 项目的总运行模型

`nanobot gateway` 是整个系统的主进程。它启动后，不只是“起一个聊天机器人”，而是把多个内部组件一起拉起来：

- `ChannelManager`
  负责外部渠道，例如 Feishu、Telegram 等。
- `AgentLoop`
  负责和大模型对话、执行工具、多轮 function calling。
- `CronService`
  负责定时任务调度。
- `HeartbeatService`
  负责定期检查 `HEARTBEAT.md`，看有没有需要主动执行的事情。
- `MessageBus`
  负责在 channel 层和 agent 层之间传递入站/出站消息。
- `SessionManager`
  负责 session 文件的读写和缓存。

这些都是同一个 `gateway` 进程里的内部组件，不是默认分散成多个独立进程。

## 2. 你自己的 FastAPI/OpenAI 循环，和 nanobot 的本质关系

你自己写的那套逻辑本质上是：

1. 收到外部消息
2. 组织 `messages`
3. 把 `tools` 一起发给模型
4. 接收模型返回
5. 如果返回 tool call，就执行工具
6. 把工具结果 append 回 `messages`
7. 继续下一轮，直到模型输出最终文本

`nanobot` 做的也是这一套事情，只不过它把逻辑拆成了框架层：

- prompt 拼接由 `ContextBuilder` 负责
- 工具注册和分发由 `ToolRegistry` 负责
- 模型接口兼容由 provider 层负责
- 多轮 tool-calling 循环由 `AgentLoop._run_agent_loop()` 负责

所以理解它最好的方式不是把它当成“完全不同的系统”，而是把它看成“你自己那套 agent loop 的框架化版本”。

## 3. 每轮请求发给模型的内容，不只是 `messages`

这个项目每一轮调用模型时，实际是同时发送：

- `messages`
- `tools`
- `model`
- 其他生成参数（例如 temperature / max_tokens 等，由 provider 默认值控制）

也就是说，模型并不是只看到了 prompt 文本。它还看到了结构化的工具定义。

需要特别区分：

- `messages`
  是聊天消息数组，包含 system、user、assistant、tool 等角色。
- `tools`
  是函数调用 schema 列表，不混在 `messages` 纯文本里。

因此当你只检查 `messages` 时，会误以为“怎么没有工具信息”。实际上工具信息在单独的 `tools=` 参数里。

## 4. 内置工具和外部 MCP 工具的差别

### 4.1 内置工具

内置工具是项目代码里直接实现的 Python 类，通常具有：

- `name`
- `description`
- `parameters`
- `execute()`

启动 `AgentLoop` 时，这些工具会直接注册进 `ToolRegistry`。例如：

- `read_file`
- `write_file`
- `edit_file`
- `list_dir`
- `exec`
- `web_search`
- `web_fetch`
- `message`
- `spawn`
- `cron`

这些工具不是通过网络发现的，而是进程启动时就放进内存里。

### 4.2 外部 MCP 工具

外部 MCP 工具来自配置里的 `tools.mcp_servers`。流程是：

1. `AgentLoop` 按配置连接外部 MCP server
2. 调 `list_tools()`
3. 把每个远端工具包装成本地 `Tool` 对象
4. 注册进同一个 `ToolRegistry`

包装后名称会变成：

- `mcp_<server_name>_<tool_name>`

例如：

- 服务器名 `qqbot`
- 远端工具名 `send_group_message`

包装后工具名就是：

- `mcp_qqbot_send_group_message`

### 4.3 两者在 AgentLoop 看来是统一的

无论工具来源是：

- 内置工具
- 外部 MCP server

对 `AgentLoop` 来说最终都是：

1. 出现在 `tools` schema 列表里
2. 通过 `ToolRegistry.execute(name, args)` 执行

所以对 agent 主循环来说，调用内置 `cron` 和调用外部 `mcp_qqbot_send_group_message` 是同一套分发机制。

## 5. 工具 schema 是怎么生成的

你的自定义代码里是手动做了一层：

```python
{
    "type": "function",
    "function": {
        "name": ...,
        "description": ...,
        "parameters": ...
    }
}
```

`nanobot` 也是这样，只不过方式不同：

- 每个工具对象自己提供：
  - `name`
  - `description`
  - `parameters`
- 然后统一通过 `Tool.to_schema()` 转换成 OpenAI tool schema

所以本质上和你那个 `convert_mcp_tool_to_openai()` 的思路一致，只是项目里把这件事做成了统一的工具基类能力，而不是一段散落的转换函数。

## 6. Skills 和 tools 是两套系统

这一点非常重要，也是很多第一次读这个项目时最容易混淆的地方。

### 6.1 Tools 是“能调用什么”

`tools` 提供给模型的是：

- 工具名
- 工具描述
- 参数结构

它回答的问题是：

- 有哪些函数可以调用？
- 每个函数接收什么参数？

### 6.2 Skills 是“什么时候用、怎么用”

`skills` 是 `SKILL.md` 文档体系，用来给模型补充工具使用策略，例如：

- 什么时候应该先读 skill
- 什么时候用 `cron`
- 什么时候应该改 `HEARTBEAT.md`
- 某类工具的最佳实践和例子

它回答的问题是：

- 什么时候该用这个工具？
- 这个工具应不应该先查文档？
- 参数应该怎么组织更合适？
- 某个任务是该走 cron 还是走 heartbeat？

### 6.3 结论

可以把两者理解成：

- tools：接口定义
- skills：使用说明书

## 7. Skills 是如何被发现和注入的

skills 的发现顺序是：

1. 先扫 workspace 下的 `skills/<name>/SKILL.md`
2. 再扫项目内置的 `nanobot/skills/<name>/SKILL.md`

规则：

- workspace skill 优先级更高
- 如果 workspace 里已经有同名 skill，内置同名 skill 不会再加入

项目会把每个 skill 的摘要放进 system prompt，摘要里包括：

- 名字
- 描述
- 是否可用
- 路径
- 缺失依赖（如果不可用）

这就是为什么模型知道 `cron` 的 skill 文件到底在哪。不是它自己猜路径，而是 system prompt 明确告诉了它：

```xml
<skill available="true">
  <name>cron</name>
  <description>Schedule reminders and recurring tasks.</description>
  <location>E:\...\nanobot\skills\cron\SKILL.md</location>
</skill>
```

## 8. 为什么模型会先去读 `cron/SKILL.md`

模型一开始就同时得到了两类信息：

第一类是 `tools`：

- 它知道有个工具叫 `cron`
- 也知道 `cron` 接收 `action`、`message`、`at`、`every_seconds` 等参数

第二类是 system prompt：

- `AGENTS.md` 告诉它，调 reminder 前先看 skill 指引
- `TOOLS.md` 告诉它，`cron` 的非显然规则去看 skill
- `Skills` 摘要告诉它，`cron` skill 的绝对路径是什么

因此模型会自然做这两步：

1. `read_file(<cron skill path>)`
2. 再调用 `cron(...)`

这也是你日志里看到的真实行为。

## 9. prompt 的完整组成，不只是几个 `.md`

系统提示词实际由 5 大块拼出来：

### 9.1 代码里动态生成的身份和运行时信息

包括：

- `# nanobot`
- Runtime，例如 `Windows AMD64, Python 3.11.15`
- Workspace 路径
- Platform Policy
- nanobot Guidelines

这些都不是文件内容，而是代码拼出来的。

### 9.2 workspace 里的 bootstrap 文件

固定会尝试加载：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`

如果文件存在，就按顺序塞入系统提示词。

### 9.3 `memory/MEMORY.md`

这是长期记忆，会被自动加载到系统提示词里。

注意：

- `MEMORY.md` 是“永远进 prompt”的
- `HISTORY.md` 默认不进 prompt，只作为归档日志，必要时才靠工具搜索

### 9.4 Active Skills

如果某个 skill 被标记为 `always`，它的正文会直接被塞进 system prompt，而不仅是摘要。

你实际看到 `memory` skill 正文出现在 prompt 里，就是这个机制。

### 9.5 Skills 摘要

这是所有发现到的 skill 的清单，带：

- 名字
- 描述
- 路径
- 可用性

模型靠这个摘要知道“有哪些 skill 可以读”。

## 10. 用户消息是怎么封装的

真正进模型前，user 消息会先加一段 runtime context，例如：

- 当前时间
- 当前 channel
- 当前 chat ID

然后才拼上用户真实消息文本。

例如：

```text
[Runtime Context - metadata only, not instructions]
Current Time: 2026-03-23 11:10 (Monday) (CST)
Channel: feishu
Chat ID: ou_xxx

提醒我五分钟后喝水
```

这段不是系统提示词，而是 user message 的内容前缀。

## 11. `cron` 在这个项目里到底是什么

`cron` 不是外部 MCP 服务，也不是一个独立的脚本 server。

它由两部分组成：

- `CronTool`
  面向模型暴露的工具接口
- `CronService`
  进程内常驻的调度器

也就是说：

- 模型调用的是 `CronTool`
- 真正保存任务、定时触发的是 `CronService`

## 12. `cron` 的完整生命周期

在 `gateway` 启动时：

1. 创建 `CronService`
2. 创建 `AgentLoop`
3. 把 `CronTool(self.cron_service)` 注册到工具表
4. 调 `cron.start()`

之后当模型返回：

```json
{"name":"cron","arguments":{"action":"add", ...}}
```

流程是：

1. `AgentLoop` 收到 tool call
2. 交给 `ToolRegistry.execute("cron", args)`
3. `ToolRegistry` 找到 `CronTool`
4. `CronTool.execute()` 根据 `action` 分发
5. `CronTool._add_job()` 调 `CronService.add_job(...)`
6. `CronService` 写入 `jobs.json` 并重新挂定时器

## 13. “提醒我五分钟后喝水”的完整链路

这件事分成两个阶段。

### 13.1 第一阶段：创建任务

1. Feishu 收到用户消息
2. 通道层包装成 `InboundMessage`
3. `AgentLoop` 构造 `messages + tools`
4. 模型先读 `cron` skill
5. 模型调用 `cron(add, ...)`
6. `CronService` 创建 job，写进 `jobs.json`
7. 模型再生成“已帮你设置提醒”的确认文本

### 13.2 第二阶段：到点触发

到时间后，不是简单把原文字直接推回用户，而是：

1. `CronService` 检查到 job 到点
2. 调用 `gateway()` 里注册的 `on_cron_job`
3. `on_cron_job` 构造一条新的任务消息：

```text
[Scheduled Task] Timer finished.

Task '提醒你喝水' has been triggered.
Scheduled instruction: 提醒你喝水
```

4. 再把这条消息送回 `agent.process_direct(...)`
5. Agent 像处理普通消息一样调用模型
6. 模型输出最终提醒内容，例如“提醒你喝水”
7. 系统决定是否要真正通知用户
8. 如果需要，再发回 Feishu

## 14. `cron` 触发时为什么 session 是隔离的

定时任务触发时，会使用单独的 session key：

- `cron:<job_id>`

所以：

- 这次触发过程不会混入原来的日常聊天 session
- 定时任务执行的上下文和普通对话上下文是隔开的

这也是为什么日志里看到的是类似：

- `cron:2a16b9a2`

而不是原来的 `feishu:<open_id>`

## 15. session 历史到底每次发多少

这个项目主流程里并不是“固定只带最近 20 条 / 100 条”。

它的主逻辑是：

- 取所有“尚未归档”的历史消息

即：

- 从 `session.last_consolidated` 开始，到当前为止的全部消息

这意味着：

- 平时不是按消息条数硬截断
- 真正的限制来自 token 窗口，而不是固定 N 条

## 16. 自动归档什么时候触发

自动归档不是按时间，也不是按消息条数，而是按 **token 估算值**。

流程是：

1. 先估算“如果把当前历史和工具定义一起发给模型，大约有多少 token”
2. 如果还没接近上限，不归档
3. 如果达到或超过 `context_window_tokens`，触发归档

默认配置里这个上限通常是：

- `65536`

一旦超过，它会尽量把上下文压到一半左右，也就是大约：

- `32768`

## 17. 自动归档具体怎么做

归档步骤不是“直接删除旧消息”，而是：

1. 选择一段较老的消息块
2. 这段消息块尽量在安全的用户回合边界截断
3. 再让大模型做一次“记忆整理”
4. 让模型通过 `save_memory` 工具返回两部分：
   - `history_entry`
   - `memory_update`
5. `history_entry` 追加到 `memory/HISTORY.md`
6. `memory_update` 覆盖更新 `memory/MEMORY.md`
7. 然后把 `session.last_consolidated` 往前推进

推进以后：

- `sessions/*.jsonl` 原始消息还在
- 但这段旧消息不再进入正常 prompt
- 模型将主要通过 `MEMORY.md` 获取压缩后的长期事实

## 18. `sessions/*.jsonl`、`MEMORY.md`、`HISTORY.md` 的角色差别

### 18.1 `sessions/*.jsonl`

这是逐 session 的完整对话原始记录。

特点：

- 按 session 分文件
- 原始消息基本都保留
- 适合作为事实来源和调试依据

### 18.2 `memory/MEMORY.md`

这是长期记忆。

特点：

- 会自动进入 prompt
- 里面应该是用户偏好、项目上下文、长期有效信息

### 18.3 `memory/HISTORY.md`

这是归档历史日志。

特点：

- 默认不自动进入 prompt
- 主要给后续检索、grep、定位历史事件用

## 19. `HISTORY.md` 默认是否带 session/channel 标识

默认不带。

当前实现写进 `HISTORY.md` 的归档内容，默认不会自动包含：

- `session.key`
- channel 名
- chat ID
- sender ID

归档阶段看到的历史文本通常只有：

- 时间
- 角色
- 内容
- 可选工具使用信息

因此，如果多个 channel 共用同一个 workspace，就会出现下面这个性质：

- session 文件彼此分开
- 但长期记忆层是共用的
- `MEMORY.md` 和 `HISTORY.md` 可能会混入不同 channel 的事实

## 20. 为什么 runtime context 最终不会进入归档历史

虽然 user 消息在发给模型前会带 runtime context：

- `Current Time`
- `Channel`
- `Chat ID`

但保存回 session 时，项目会把这段 runtime context 前缀剥掉，只保留真正用户输入的正文。

所以到了归档阶段，系统通常已经看不到显式的：

- `Channel: feishu`
- `Chat ID: ...`

这也是为什么 `HISTORY.md` 默认不会自动区分不同渠道。

## 21. 为什么你看到的真实 prompt 比预期大很多

你原本以为 prompt 主要来自：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`

但真实情况是还会额外拼上：

- 代码生成的 identity/runtime 文本
- `MEMORY.md`
- always skills 的正文
- 全部 skills 摘要

所以你看到的 prompt 很长，是正常现象，不是额外哪里又偷偷拼了一份。

## 22. 你这次加的调试钩子做了什么

我们这次为了调试，在真正调用模型前加了一个很小的落盘逻辑，把完整请求写到：

- `E:\pycharm_project\Fast_mcp\nanobot-main\first_all_chat.json`

这份 JSON 里包含：

- `model`
- `messages`
- `tools`
- `tool_choice`

所以现在你可以直接看到“最终送给模型的完整载荷”，而不是只凭日志猜。

## 23. 对这个项目最实用的心智模型

如果以后你再看这个项目，最实用的理解方式是：

### 23.1 对话主循环

1. 从 channel 收消息
2. 包装成 `InboundMessage`
3. 找 session
4. 做 token 检查，必要时归档
5. 构造 system prompt + user message
6. 取工具 schema
7. 调模型
8. 如果模型要调工具，就执行工具、追加 tool result
9. 重复直到得到最终文本
10. 保存 session
11. 把回复发回 channel

### 23.2 工具层

- 内置工具：代码里直接实现
- MCP 工具：远端连接后包装成本地工具
- 两者最终都走同一个 registry

### 23.3 记忆层

- 短期对话：`sessions/*.jsonl`
- 长期事实：`MEMORY.md`
- 归档日志：`HISTORY.md`

### 23.4 策略层

- tool schema 告诉模型“能做什么”
- skills 告诉模型“什么时候做、怎么做”

## 24. 一句话版总结

`nanobot` 的核心并不神秘：

- 本质上还是一个“messages + tools -> tool calls -> execute -> append -> loop”的 agent
- 只是它把你的手写逻辑框架化了
- 并额外叠加了：
  - skills 体系
  - session 持久化
  - 自动归档
  - 长期记忆
  - 多 channel 适配
  - 定时任务和 heartbeat

如果以后忘了，优先记这四件事：

1. `tools` 和 `messages` 是分开发给模型的
2. `skills` 不是工具，是工具使用说明
3. `cron` 是内置工具 + 内部调度器，不是外部 MCP server
4. `MEMORY.md/HISTORY.md` 是 workspace 共享层，不是按 channel 隔离的

## 25. 源码导航

下面只列“去哪里看”，不重复贴代码。

### 25.1 启动入口与总装配

- `gateway` 启动入口：
  - `nanobot/cli/commands.py:463`
- `cron` 触发后回调 agent：
  - `nanobot/cli/commands.py:516`
- heartbeat 选路与执行/通知回调：
  - `nanobot/cli/commands.py:564`
  - `nanobot/cli/commands.py:581`
  - `nanobot/cli/commands.py:596`

### 25.2 Agent 主循环

- `AgentLoop` 类入口：
  - `nanobot/agent/loop.py:37`
- 注册默认工具：
  - `nanobot/agent/loop.py:117`
- 连接外部 MCP：
  - `nanobot/agent/loop.py:137`
- 多轮 tool-calling 主循环：
  - `nanobot/agent/loop.py:200`
- 单条消息处理：
  - `nanobot/agent/loop.py:374`
- 保存对话回合：
  - `nanobot/agent/loop.py:479`
- 直接处理一条内部消息（cron/CLI 常用）：
  - `nanobot/agent/loop.py:516`

### 25.3 Prompt 组装

- `ContextBuilder` 类：
  - `nanobot/agent/context.py:16`
- 构造 system prompt：
  - `nanobot/agent/context.py:27`
- 代码生成的 identity/runtime 文本：
  - `nanobot/agent/context.py:56`
- 读取 workspace bootstrap 文件：
  - `nanobot/agent/context.py:108`
- 最终拼 `messages`：
  - `nanobot/agent/context.py:120`

### 25.4 Skills 发现与摘要

- `SkillsLoader` 类：
  - `nanobot/agent/skills.py:13`
- 扫描 workspace / 内置 skills：
  - `nanobot/agent/skills.py:26`
- 生成 `<skills>...</skills>` 摘要：
  - `nanobot/agent/skills.py:101`
- 取 always skills：
  - `nanobot/agent/skills.py:193`

### 25.5 Tool 系统

- Tool 抽象基类：
  - `nanobot/agent/tools/base.py:7`
- Tool 转 OpenAI schema：
  - `nanobot/agent/tools/base.py:172`
- ToolRegistry 类：
  - `nanobot/agent/tools/registry.py:8`
- 收集全部 tool schema：
  - `nanobot/agent/tools/registry.py:34`
- 按名称执行工具：
  - `nanobot/agent/tools/registry.py:38`

### 25.6 内置 `cron` 工具

- `CronTool` 类：
  - `nanobot/agent/tools/cron.py:12`
- `cron` 的 `execute()`：
  - `nanobot/agent/tools/cron.py:74`
- 添加任务 `_add_job()`：
  - `nanobot/agent/tools/cron.py:95`

### 25.7 `cron` 调度服务

- `CronService` 类：
  - `nanobot/cron/service.py:63`
- 启动定时服务：
  - `nanobot/cron/service.py:175`
- 挂下一次 timer：
  - `nanobot/cron/service.py:208`
- timer 到点后的处理：
  - `nanobot/cron/service.py:227`
- 执行单个任务：
  - `nanobot/cron/service.py:245`
- 添加 job：
  - `nanobot/cron/service.py:286`

### 25.8 Heartbeat 服务

- `HeartbeatService` 类：
  - `nanobot/heartbeat/service.py:40`
- 启动 heartbeat：
  - `nanobot/heartbeat/service.py:111`
- 单次 heartbeat 检查：
  - `nanobot/heartbeat/service.py:143`

### 25.9 MCP 外部工具接入

- `MCPToolWrapper` 类：
  - `nanobot/agent/tools/mcp.py:14`
- MCP wrapper 的 `execute()`：
  - `nanobot/agent/tools/mcp.py:37`
- 连接并注册 MCP servers：
  - `nanobot/agent/tools/mcp.py:74`

### 25.10 Session 与历史

- `Session` 类：
  - `nanobot/session/manager.py:17`
- 取历史 `get_history()`：
  - `nanobot/session/manager.py:69`
- `SessionManager` 类：
  - `nanobot/session/manager.py:102`
- 落盘保存 session：
  - `nanobot/session/manager.py:192`

### 25.11 Memory / 自动归档

- `MemoryStore` 类：
  - `nanobot/agent/memory.py:75`
- 追加 `HISTORY.md`：
  - `nanobot/agent/memory.py:94`
- 把消息格式化成归档输入：
  - `nanobot/agent/memory.py:103`
- LLM 归档主流程：
  - `nanobot/agent/memory.py:114`
- raw archive 降级写法：
  - `nanobot/agent/memory.py:210`
- `MemoryConsolidator` 类：
  - `nanobot/agent/memory.py:222`
- 估算 session prompt token：
  - `nanobot/agent/memory.py:276`
- 自动归档触发逻辑：
  - `nanobot/agent/memory.py:302`

### 25.12 MessageBus 与消息对象

- `MessageBus`：
  - `nanobot/bus/queue.py:8`
- `InboundMessage`：
  - `nanobot/bus/events.py:9`
- `OutboundMessage`：
  - `nanobot/bus/events.py:28`

### 25.13 通道管理

- `ChannelManager` 类：
  - `nanobot/channels/manager.py:15`
- 初始化启用的 channels：
  - `nanobot/channels/manager.py:33`
- 启动全部 channels：
  - `nanobot/channels/manager.py:75`
- 出站消息分发：
  - `nanobot/channels/manager.py:113`
- 自动发现 channel：
  - `nanobot/channels/registry.py:54`

### 25.14 Feishu 这一条链路

- Feishu 启动：
  - `nanobot/channels/feishu.py:289`
- Feishu 发消息：
  - `nanobot/channels/feishu.py:935`
- Feishu 收消息：
  - `nanobot/channels/feishu.py:1040`

### 25.15 配置、时间、workspace 模板

- `tools.mcp_servers` 所在配置结构：
  - `nanobot/config/schema.py:144`
- 当前时间字符串格式：
  - `nanobot/utils/helpers.py:37`
- 同步 workspace 模板文件：
  - `nanobot/utils/helpers.py:181`

### 25.16 Provider 与统一响应结构

- `ToolCallRequest`：
  - `nanobot/providers/base.py:13`
- `chat_with_retry()`：
  - `nanobot/providers/base.py:226`

### 25.17 这次新增的调试落盘位置

- 调用模型前把完整 payload 写到 `first_all_chat.json` 的逻辑：
  - `nanobot/agent/loop.py`
- 调试输出文件：
  - `E:\pycharm_project\Fast_mcp\nanobot-main\first_all_chat.json`
