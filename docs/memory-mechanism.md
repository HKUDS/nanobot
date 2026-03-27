# nanobot Memory 机制深度分析

## 一、总体架构——"双层记忆 + Token 驱动的自动归档"

nanobot 的记忆系统由 3 个协作层构成：

```
┌─────────────────────────────────────────────────────────────┐
│  Session（短期/工作记忆）                                    │
│  workspace/sessions/<channel_chat_id>.jsonl                  │
│  ● append-only 的完整消息流（user/assistant/tool）            │
│  ● 字段 last_consolidated 标记归档水位线                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ 超过 token 预算时触发归档
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  MemoryStore（长期记忆）                                     │
│  workspace/memory/MEMORY.md  — 长期事实（始终注入 system prompt）│
│  workspace/memory/HISTORY.md — 时间线日志（按需 grep 搜索）    │
└─────────────────────────────────────────────────────────────┘
```

辅助层：

```
┌─────────────────────────────────────────────────────────────┐
│  Heartbeat（主动唤醒记忆）                                   │
│  workspace/HEARTBEAT.md — 定期任务清单，agent 自己检查        │
└─────────────────────────────────────────────────────────────┘
```

## 二、Session 层——工作记忆

### 2.1 数据结构

`Session`（`nanobot/session/manager.py`）是一个 dataclass，核心字段：

- `key: str` — 形如 `"telegram:123456"` 的会话标识
- `messages: list[dict]` — append-only 的完整消息历史
- `last_consolidated: int = 0` — 已归档的消息数量（索引偏移）

### 2.2 持久化格式

JSONL 文件，第一行是元数据行（含 `last_consolidated`），后续每行是一条消息：

```json
{"_type":"metadata","key":"telegram:123456","last_consolidated":42,...}
{"role":"user","content":"你好","timestamp":"2026-03-25T10:00:00"}
{"role":"assistant","content":"你好！","timestamp":"2026-03-25T10:00:01"}
```

### 2.3 获取历史时的"合法边界"对齐

`get_history()` 不会原样返回全部消息，而是做 3 步裁剪：

1. **跳过已归档部分**：`self.messages[self.last_consolidated:]`
2. **找到第一个 user 消息作为起点**：避免从 assistant/tool 消息开头
3. **`_find_legal_start()`**：确保没有"孤儿 tool result"（即找不到对应 assistant tool_call 的 tool 消息）。某些 LLM provider 遇到孤儿 tool result 会直接报错。

这个设计的关键意义：**消息列表是 append-only 的，归档不会删消息，只移动 `last_consolidated` 指针**。这样做是为了 LLM prompt cache 效率——如果每次都改消息列表头部，provider 的 KV cache 就会失效。

## 三、MemoryStore 层——长期记忆的双文件系统

### 3.1 MEMORY.md（长期事实）

- **路径**：`workspace/memory/MEMORY.md`
- **内容**：markdown 格式的事实集合（用户偏好、项目上下文、人物关系等）
- **读取时机**：每次构建 system prompt 时必读
- **注入方式**：在 `ContextBuilder.build_system_prompt()` 中，MEMORY.md 的全部内容被注入到 system prompt 的 `# Memory` 段落

也就是说，**MEMORY.md 的全部内容，每一轮对话都会被注入 system prompt**。这是模型"记住你是谁、你在做什么"的核心机制。

### 3.2 HISTORY.md（时间线日志）

- **路径**：`workspace/memory/HISTORY.md`
- **内容**：append-only 的事件摘要，格式为 `[YYYY-MM-DD HH:MM] 摘要内容`
- **不注入 system prompt**——太大了。agent 需要时通过 `exec` 工具做 `grep` 搜索

这个设计把"始终可见的关键事实"和"按需检索的流水账"分开，控制了 prompt token 开销。

## 四、MemoryConsolidator——自动归档的核心引擎

位于 `nanobot/agent/memory.py` 的 `MemoryConsolidator` 类。

### 4.1 触发时机

归档在每条消息处理前后都可能触发（`AgentLoop._process_message()`）：

- **处理前**：如果已经超预算，先归档再推理
- **处理后**：后台异步再检查一次（通过 `_schedule_background()`）
- **`/new` 命令**：开新 session 时对残留消息执行 `archive_messages()`

### 4.2 Token 预算计算

```
budget = context_window_tokens - max_completion_tokens - SAFETY_BUFFER(1024)
target = budget // 2
```

例如，`context_window_tokens=65536`，`max_completion_tokens=8192`：
- `budget = 65536 - 8192 - 1024 = 56320`
- `target = 28160`

当估算的 prompt token 超过 `budget` 时开始归档，归档到 `target` 以下停止。
这里的 `target = budget // 2` 设计留出了充分余量，避免频繁归档。

### 4.3 Token 估算链

估算优先级（`estimate_prompt_tokens_chain()`）：

1. **Provider 自带的 counter**（如果 provider 实现了 `estimate_prompt_tokens`）
2. **tiktoken 回退**：用 `cl100k_base` 编码计算
3. **字符除 4 回退**：tiktoken 也失败时的粗估

估算范围包括：message content、tool_calls JSON、reasoning_content、tool_call_id、name，加上每条消息 4 token 的 framing 开销。

### 4.4 归档边界选择

`pick_consolidation_boundary()` 不会随意截断消息，而是找到一个 user 消息开头的"对话轮"边界。逐条累加 token 数直到满足需要移除的量，且只在 `role == "user"` 的位置记录可选边界。

这保证了归档的切割点一定落在"一个完整对话轮结束、下一轮 user 消息开始"的位置，不会把一次 tool 调用链切成两半。

### 4.5 归档循环

`maybe_consolidate_by_tokens()` 最多循环 5 轮（`_MAX_CONSOLIDATION_ROUNDS = 5`），每轮：

1. 估算当前 prompt token
2. 如果 <= target，停止
3. 选择边界，取出 `session.messages[last_consolidated:boundary]` 这个 chunk
4. 调用 `consolidate_messages(chunk)`（让 LLM 总结）
5. 更新 `session.last_consolidated = boundary`
6. 保存 session 到磁盘
7. 重新估算，下一轮

### 4.6 LLM 驱动的归档过程

`MemoryStore.consolidate()` 的工作方式——它本身就是一次 LLM 调用：

1. 把待归档的消息格式化成文本
2. 把当前 MEMORY.md 内容也给 LLM
3. 要求 LLM 调用 `save_memory` 工具，产出两个字段：
   - `history_entry`：一段事件摘要（追加到 HISTORY.md）
   - `memory_update`：更新后的完整 MEMORY.md（保留旧事实 + 新事实）

使用 `tool_choice` forced 模式确保 LLM 必定调用 `save_memory` 工具，保证结构化输出。
如果 provider 不支持 forced tool_choice，自动降级为 `auto` 模式重试。

### 4.7 降级容错——3 次失败后 raw dump

如果 LLM 归档连续失败 3 次（模型没调用工具、参数格式错、异常等），系统不会丢数据，而是直接把原始消息 dump 到 HISTORY.md，格式为 `[时间] [RAW] N messages`。

这是一个"宁可记录粗糙也不丢信息"的安全网。

## 五、并发安全

每个 session 有独立的 consolidation lock（`weakref.WeakValueDictionary` 管理，自动回收）：

```python
def get_lock(self, session_key: str) -> asyncio.Lock:
    return self._locks.setdefault(session_key, asyncio.Lock())
```

同一 session 的归档操作串行执行；不同 session 的归档完全并行。

## 六、Memory 的注入路径图

```
用户消息到达
     │
     ▼
[1] 加载 session（从 .jsonl）
[2] maybe_consolidate_by_tokens()  ← 处理前先检查 token 是否超限
[3] session.get_history()          ← 返回 last_consolidated 之后、对齐到合法边界的消息
[4] ContextBuilder.build_messages()
     │
     ├── build_system_prompt()
     │     ├── _get_identity()         → 基础身份 + workspace 路径
     │     ├── _load_bootstrap_files() → AGENTS.md / SOUL.md / USER.md / TOOLS.md
     │     ├── memory.get_memory_context() → 读取 MEMORY.md 全文注入
     │     └── skills                  → always=true 的技能
     │
     └── [system_prompt, ...history, user_message]
              │
              ▼
     [5] _run_agent_loop()  → LLM 推理 + 工具调用循环
              │
              ▼
     [6] _save_turn()  → 新消息 append 到 session
     [7] sessions.save()
     [8] 后台 maybe_consolidate_by_tokens()  ← 处理后再检查
```

## 七、与 Heartbeat 的协作

Heartbeat 是"定时主动唤醒"机制，与 memory 的交互点：

1. Heartbeat 执行完一次任务后，会裁剪 heartbeat session 到最近 N 条（`retain_recent_legal_suffix()`），避免 heartbeat 专用 session 无限膨胀。
2. `retain_recent_legal_suffix()` 跟 `get_history()` 使用相同的边界对齐规则，保证裁剪后不出现孤儿 tool result。

## 八、Memory Skill

`nanobot/skills/memory/SKILL.md` 被标记为 `always: true`，其内容始终注入 system prompt，告诉模型：

- MEMORY.md 是事实库，重要信息要主动写入
- HISTORY.md 是日志，用 grep 搜索
- 自动归档会自己发生，不需要模型操心

## 九、设计特点总结

| 特性 | 实现方式 |
|---|---|
| **双层分离** | MEMORY.md（始终可见事实）vs HISTORY.md（按需检索日志） |
| **Token 驱动归档** | 超过 context_window 预算时自动触发，归到一半停止 |
| **LLM 驱动总结** | 归档由一次独立的 LLM 调用完成，通过 forced tool_choice 保证结构化输出 |
| **append-only session** | 消息只追加不删除，用指针标记归档水位，利于 LLM prompt cache |
| **合法边界对齐** | 归档和历史裁剪都对齐到 user-turn 边界，避免切断 tool call 链 |
| **3 次失败降级** | 连续 3 次 LLM 归档失败后 raw dump 原始消息，不丢数据 |
| **并发安全** | 每个 session 一个 asyncio.Lock，跨 session 完全并行 |
| **agent 可主动写 MEMORY.md** | 模型可以随时用 write_file/edit_file 工具直接更新长期记忆 |

## 相关源文件

- `nanobot/agent/memory.py` — MemoryStore + MemoryConsolidator
- `nanobot/agent/context.py` — ContextBuilder（system prompt 注入 MEMORY.md）
- `nanobot/session/manager.py` — Session + SessionManager
- `nanobot/agent/loop.py` — AgentLoop（触发归档的调用点）
- `nanobot/utils/helpers.py` — Token 估算函数
- `nanobot/command/builtin.py` — /new 命令触发归档
- `nanobot/heartbeat/service.py` — Heartbeat 服务
- `nanobot/skills/memory/SKILL.md` — Memory skill（always=true）
