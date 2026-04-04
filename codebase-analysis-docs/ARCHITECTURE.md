# ARCHITECTURE.md — 深度架构剖析

---

## 1. 分层架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLI Layer                                 │
│  nanobot agent (交互模式)   nanobot gateway (daemon 模式)        │
│  nanobot onboard  nanobot status  nanobot channels login          │
│  nanobot/cli/commands.py (typer, ~1221行)                        │
└────────────────────────────┬─────────────────────────────────────┘
                             │ asyncio.run()
┌────────────────────────────▼─────────────────────────────────────┐
│                      Channel Layer                                │
│  telegram.py  feishu.py  dingtalk.py  slack.py  discord.py       │
│  whatsapp.py  qq.py  matrix.py  email.py  wecom.py  mochat.py    │
│                                                                   │
│  BaseChannel: login() | start() | stop() | send()                │
│  ChannelManager: 生命周期管理（start_all / stop_all）            │
│  ChannelRegistry: auto-discovery (pkgutil + entry_points)         │
└────────────┬───────────────────────────────────────┬─────────────┘
             │ publish_inbound()                     │ consume_outbound()
┌────────────▼───────────────────────────────────────▼─────────────┐
│                       Message Bus                                 │
│  bus/queue.py  MessageBus (asyncio.Queue × 2)                    │
│  bus/events.py InboundMessage | OutboundMessage                  │
└────────────────────────────┬─────────────────────────────────────┘
                             │ consume_inbound()
┌────────────────────────────▼─────────────────────────────────────┐
│                      Agent Layer                                  │
│                                                                   │
│  AgentLoop (agent/loop.py)                                        │
│  ├── CommandRouter (command/router.py)  /stop /new /status        │
│  ├── ContextBuilder (agent/context.py)  system prompt 组装        │
│  ├── MemoryConsolidator (agent/memory.py)  按需压缩历史           │
│  ├── LLMProvider  chat_with_retry() / chat_stream_with_retry()    │
│  ├── ToolRegistry  register / execute (concurrent asyncio.gather) │
│  └── SubagentManager (agent/subagent.py)  后台子 agent 任务       │
│                                                                   │
│  Session 并发模型:                                                 │
│    _session_locks[key]: asyncio.Lock  (同 session 串行)           │
│    _concurrency_gate: asyncio.Semaphore  (全局并发上限)            │
└────────────┬────────────────────────────────────────┬────────────┘
             │                                        │
┌────────────▼─────────┐              ┌───────────────▼────────────┐
│    Provider Layer     │              │      Tools Layer            │
│  providers/           │              │  agent/tools/               │
│  ├── litellm_provider │              │  ├── filesystem.py          │
│  ├── azure_openai     │              │  ├── shell.py               │
│  ├── custom_provider  │              │  ├── web.py                 │
│  └── registry.py      │              │  ├── mcp.py                 │
│                       │              │  ├── spawn.py               │
│  LLMResponse:         │              │  ├── cron.py                │
│    content            │              │  ├── message.py             │
│    tool_calls         │              │  └── registry.py            │
│    reasoning_content  │              └────────────────────────────┘
│    thinking_blocks    │
└───────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────────────┐
│                    Persistence Layer                               │
│  session/manager.py  SessionManager  → {workspace}/sessions/*.jsonl│
│  agent/memory.py     MemoryStore     → {workspace}/memory/         │
│                        MEMORY.md (长期事实)                        │
│                        HISTORY.md  (时间戳日志)                    │
│  config/loader.py    Config         → ~/.nanobot/config.json       │
└───────────────────────────────────────────────────────────────────┘
```

---

## 2. 消息总线事件模型

### InboundMessage

```python
@dataclass
class InboundMessage:
    channel: str           # "telegram" | "feishu" | "slack" | ...
    sender_id: str         # 发送者 ID
    chat_id: str           # 会话 ID（群组/私聊）
    content: str           # 消息文本
    timestamp: datetime    # 默认 now()
    media: list[str]       # 媒体文件路径（图片、音频等）
    metadata: dict         # 渠道专属数据
    session_key_override: str | None  # 用于线程级 session（如 Slack 线程）

    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{self.chat_id}"
```

### OutboundMessage 特殊 metadata 标志

| 标志 | 含义 |
|------|------|
| `_wants_stream: True` | 请求流式输出 |
| `_stream_delta: str` | 流式内容片段 |
| `_stream_end: True` | 流式结束信号 |
| `_progress: True` | 工具思考/进度消息 |
| `_tool_hint: True` | 工具调用提示 |
| `_streamed: True` | 该响应已流式传输 |
| `render_as: "text"` | 渠道渲染格式提示 |
| `_resuming: True` | 流式恢复信号（重连后） |

---

## 3. 提供商匹配算法

`Config._match_provider(model)` 按优先级顺序：

```
1. explicit：config.agent.provider != "auto"
   └── 直接返回指定 provider

2. model prefix：model 字符串中包含 "/"
   └── 前缀匹配 ProviderSpec.litellm_prefix
   └── 示例: "deepseek/deepseek-chat" → deepseek provider

3. keyword match：遍历 PROVIDERS 元组
   └── 检查 ProviderSpec.keywords 是否匹配 model 字符串
   └── 示例: model 含 "claude" → anthropic provider

4. local fallback：ProviderSpec.is_local = True
   └── 用于 Ollama、vLLM 等本地服务
   └── 仅当有 api_key 或 api_base 时生效

5. gateway fallback：ProviderSpec.is_gateway = True
   └── OpenRouter、AiHubMix 等聚合网关
   └── OAuth 类 provider（is_oauth=True）不参与此 fallback
```

**注意**：`find_gateway()` 在存在 API key 时优先选择已配置的 gateway provider。

---

## 4. 记忆压缩状态机

```
session.messages = [m0, m1, m2, m3, m4, m5, m6, m7, m8]
                            ↑
               last_consolidated = 4

get_history() 返回:  [m4, m5, m6, m7, m8]
                     ↑ (最多 500 条)

触发压缩条件:
  estimate_tokens([m4..m8]) > (context_window - max_tokens - 1024) / 2

压缩过程:
  1. pick_consolidation_boundary()
     └── 找到从 m4 开始的最早 user-turn 边界
     └── 确保移除足够 token 后还剩 < budget/2

  2. consolidate(messages[4:boundary], provider, model)
     └── 强制调 LLM save_memory 工具
     └── 写入 MEMORY.md（更新长期知识）
     └── 写入 HISTORY.md（追加时间戳日志）

  3. session.last_consolidated = boundary
     └── 下次 get_history() 从 boundary 开始

  4. messages 数组不变（append-only 保持）

最多循环 5 轮，3 次连续失败降级 raw archive:
  格式: "[YYYY-MM-DD HH:MM] [RAW] N messages\n<原始消息文本>"
```

---

## 5. 工具执行管道

```
_run_agent_loop() 中的一次迭代:

1. build tool definitions
   └── registry.get_definitions()
   └── 返回 OpenAI function calling 格式的 JSON Schema 列表

2. call LLM
   └── provider.chat_with_retry(messages, tools=defs, model=..., max_tokens=...)
   └── 返回 LLMResponse

3. 提取 tool_calls
   └── response.tool_calls: list[ToolCallRequest]
     ├── id: str (9 字符短 ID)
     ├── name: str (工具名)
     └── arguments: dict (已解析 JSON)

4. 添加 assistant 消息（含 tool_calls）到 messages

5. 并发执行所有工具
   └── asyncio.gather(*[registry.execute(tc.name, tc.arguments) for tc in tool_calls],
                      return_exceptions=True)
   └── 部分失败不阻塞其他工具

6. 添加 tool 结果消息到 messages（保持顺序）

7. 若 finish_reason == "tool_calls" → 回步骤 2
   若 finish_reason == "stop" → 退出循环，返回最终内容
```

---

## 6. EditFileTool 模糊匹配算法

`_find_match(file_content, old_text)` 两阶段匹配：

```python
# 阶段1: 精确匹配
if old_text in file_content:
    return exact_match_position

# 阶段2: 去首尾空格的滑窗匹配
# 将 file_content 和 old_text 按行分割
# 对 old_text 的每一行去 strip()，生成模式
# 在 file_content 中找连续 len(pattern) 行，每行 strip() 后与模式匹配
# 匹配成功时，用原始 file 行（保留缩进）构成实际替换范围
```

**场景**：处理 LLM 生成代码时的空白字符差异（tab vs space、行末空格等）。

---

## 7. SubagentManager 工作流

```
主 Agent 调用 spawn 工具
    │
    ▼
SpawnTool.execute(task="...", label="...")
    │
    ▼
SubagentManager.spawn(task, label, origin_channel, origin_chat_id, session_key)
    │
    ├── 生成 UUID task_id (8字符)
    ├── 注册到 _tasks[session_key]
    └── asyncio.create_task(_run_subagent(...))  # 立即返回

    └── 主 Agent 继续处理（不阻塞）

_run_subagent() 异步执行：
    ├── 构建精简工具集（无 Message/Spawn/Cron/MCP）
    ├── 简化系统提示词（子 agent 身份）
    ├── 运行最多 15 次迭代
    └── 完成后向 origin_channel:origin_chat_id 发送 system 类型消息
        └── 主 Agent 收到后以普通系统消息展示给用户

取消：
    /stop 命令 → CommandRouter → cancel_by_session(key)
    → asyncio.Task.cancel() for all tasks in session
```

---

## 8. WhatsApp Bridge 架构

`bridge/` 为独立 TypeScript 服务：

```
Python nanobot process
    │
    │ WebSocket
    │
    ▼
bridge/src/server.ts (Socket.IO + HTTP)
    │
    ├── server.ts: 接受 Python nanobot 连接
    │              转发 Python 发出的消息到 WhatsApp
    │              转发 WhatsApp 收到的消息到 Python
    │
    └── whatsapp.ts: Baileys 库封装
                     WA Web 协议
                     QR 码认证
                     消息收发
```

Python 侧 `channels/whatsapp.py` 通过 `websockets` 连接 bridge，按照约定协议收发 JSON。

---

## 9. 命令路由三级架构

```
InboundMessage 到达 _dispatch()
    │
    ├── [1] dispatch_priority()  ← 在 session lock 外处理
    │       /stop  → 取消当前 session 所有任务
    │       /restart → os.execv() 重启进程
    │
    ├── [2] dispatch()  ← 在 session lock 内处理
    │   ├── exact match: /new /status /help
    │   ├── prefix match (最长前缀优先): /agent xxx
    │   └── interceptors: 谓词函数 fallback
    │
    └── [未匹配] → 进入正常 AgentLoop 处理
```

**CommandContext** 传递给所有命令处理器：
```python
@dataclass
class CommandContext:
    msg: InboundMessage
    session: Session | None
    key: str         # session key
    raw: str         # 原始命令文本
    args: str        # prefix 命令的参数部分
    loop: AgentLoop  # 引用 AgentLoop 进行操作
```

---

## 10. 安全模型

### 渠道访问控制
- `BaseChannel.is_allowed(sender_id)` 检查 `config.channels.allow_from`
- `[]` = 拒绝所有；`["*"]` = 允许所有；其他 = 白名单

### Shell 工具防护
危险命令正则拦截（`ExecTool`）：
```python
DANGEROUS_PATTERNS = [
    r"\brm\s+(-[^\s]*[rf][^\s]*\s+|--recursive\s+|--force\s+)",
    r"\bdel\s+/[fq]",      # Windows
    r"\bformat\b",
    r"\bmkfs\b",
    r"\bdd\b.*\bof=",
    r"\bshutdown\b",
    r":\(\)\{:\|:&\};:",    # fork bomb
    # ...
]
```
可通过 `config.tools.exec.deny_patterns` 追加，`allow_patterns` 设置白名单覆盖。

### Web 工具 SSRF 防护
`validate_url_target()` 阻止访问私有 IP 段和 localhost，所有外部内容添加信任警告横幅。

### 工作空间限制
`config.tools.restrict_to_workspace = True` 将文件系统工具限制在 workspace 目录内。
