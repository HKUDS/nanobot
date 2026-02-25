# 本地分支与 hk/main 的功能差异记录

> 用于追踪本地 origin/main 相对于上游 hk (HKUDS/nanobot) 的独有功能，方便后续合并冲突时判断取舍。
>
> 最后更新：2026-02-25，基于 merge commit `2bed323`

---

## 总体关系

本地 `main` 完全领先于 `hk/main`（hk 无独有 commit）。以下所有功能均为本地独有，合并 hk 时**应保留本地版本**。

---

## 独有功能一览

### 1. Anthropic Thinking / Effort 支持
**文件：** `nanobot/agent/loop.py`, `nanobot/config/schema.py`, `nanobot/providers/litellm_provider.py`, `providers/base.py`, `providers/custom_provider.py`, `providers/openai_codex_provider.py`

- `AgentDefaults` 新增 `effort: str | None` 和 `thinking: ThinkingConfig`（`enabled`, `budget_tokens`）
- `AgentLoop.__init__` 接收并存储这两个参数，在每次 `provider.chat()` 调用时透传
- `LiteLLMProvider.chat()` 在 anthropic 模型下将 `effort` 和 `thinking` 写入请求 kwargs
- 同时解析 Anthropic 返回的 `cache_creation_input_tokens` / `cache_read_input_tokens` 并记录缓存命中率

**冲突时：** 保留本地，hk 不含此功能。

---

### 2. HTTP 状态 API（M5Stack 外接显示屏）
**文件：** `nanobot/api/__init__.py`, `nanobot/api/log_watcher.py`, `nanobot/api/server.py`

- `LogWatcher`：每 500ms tail 日志文件，解析工具调用/LLM 请求/入站消息，维护 100 条 ring buffer，暴露 `get_status(cursor)` 返回 `{cursor, status, detail, logs}`
- 状态机：`thinking` → `tool_call` → `listening` → `idle`（30s 超时）
- `StatusServer`：aiohttp 封装，两个路由 `GET /api/status?cursor=xxx` 和 `GET /health`
- `cli/commands.py` 中 `agent` 命令启动时挂载此服务

**冲突时：** hk 无此模块，保留本地全部文件。

---

### 3. 消息总线：同会话消息缓冲（Message Buffer）
**文件：** `nanobot/bus/queue.py`

- 处理中的 session（`_active_inbound_session`）收到同 session 新消息时，暂存到 `_inbound_collect_buffer` 而非入队
- `complete_inbound_turn()` 刷新缓冲：多条消息合并为单条（`[sender_id] content` 格式，`\n\n` 分隔），原始消息存入 `metadata["collected_messages"]`
- 防止同一会话并发处理导致的混乱

**冲突时：** 保留本地逻辑，hk 版本无此缓冲机制。

---

### 4. Telegram 频道大幅增强
**文件：** `nanobot/channels/telegram.py`

| 功能 | 说明 |
|------|------|
| `/reset` 命令 | 清空当前会话历史，`session_manager` 作为可选构造参数注入 |
| Sticker 支持 | 收发贴纸，`webp`/`webm` MIME 支持 |
| 媒体组发送 | 多图片用 `send_media_group`，单图用 `send_photo` |
| Reactions | `_send_reaction()` 使用 `set_message_reaction` + `ReactionTypeEmoji` |
| 回复上下文 | `_extract_reply_metadata()` 提取 `reply_to_message`/`external_reply`/`quote`，格式化为 `[reply_to: name, text: ...]` 前缀 |
| 群聊发送者上下文 | `_build_sender_context()` 在群消息前追加 `[from: @user, group: Title, msg_id: N]` |
| `msg_type` 路由 | `"progress"` → 发送 typing action；`"silent"` → 跳过发送 |
| 重构 `send()` | 拆分为 `_send_text()` / `_send_with_media()` / `_send_reaction()` / `_send_sticker()` |
| `_resolve_reply_to_message_id()` | 只使用显式 `OutboundMessage.reply_to`，不自动注入 metadata |

**冲突时：** hk 的 telegram.py 为精简版，本地为模块化增强版，合并时保留本地。

---

### 5. OutboundMessage 扩展字段
**文件：** `nanobot/bus/events.py`

- 新增 `reaction: str | None` — emoji reaction（配合 `metadata["reaction_to_message_id"]`）
- 新增 `msg_type: str = "final"` — `"final"` / `"progress"` / `"silent"` 三态控制发送行为
- 新增 `InboundMessage.session_key_override: str | None` — 允许覆盖默认 session key

**冲突时：** 保留本地所有新字段。

---

### 6. DingTalk `msg_type` 支持
**文件：** `nanobot/channels/dingtalk.py`

- `send()` 对 `msg_type == "progress"` 静默跳过（仅 log），对 `msg_type == "silent"` 完全跳过

**冲突时：** 保留本地。

---

### 7. Session 历史重写
**文件：** `nanobot/session/manager.py`

- `get_history()` 重写：从 `last_consolidated` 游标切片，过滤 24h 以前的消息（`max_age_hours=24.0`），取最近 `max_messages` 条，丢弃开头非 user 消息
- 保留 `tool_calls`、`tool_call_id`、`name` 等元数据
- hk 版本的 `get_history()` 不含时效过滤，且使用不同的历史压缩逻辑

**冲突时：** 保留本地版本（含 `last_consolidated` 切片 + `max_age_hours` 过滤）。

---

### 9. AgentLoop 关键修复
**文件：** `nanobot/agent/loop.py`

- `run()` 的 `finally` 块必须调用 `await self.bus.complete_inbound_turn(msg)`，否则 buffer 永远不清空，所有后续消息被积压
- `__init__` 新增 `history_max_age_hours: float = 24.0` 参数，两处 `get_history()` 调用均需透传 `max_age_hours=self.history_max_age_hours`
- `/new` 和 `/help` 命令匹配需用 `cmd.split("@")[0]`，兼容 Telegram 群组的 `/cmd@botname` 格式
- `[SILENT]` 输出需转换为 `msg_type="silent"` 的 OutboundMessage，不能直接发送文本
- `_save_turn()` 末尾需推进 `last_consolidated`：`if len(session.messages) - session.last_consolidated > self.memory_window: session.last_consolidated = len(session.messages) - self.memory_window`
- `_run_agent_loop()` 中 LLM 无 tool call 时，final response 必须用 `add_assistant_message()` 写入 messages，否则不会存入 session

**冲突时：** 以上所有逻辑均为本地独有修复，hk 版本不含，合并后必须手动补回。

---

### 10. Heartbeat 间隔
**文件：** `nanobot/config/schema.py`

- `HeartbeatConfig.interval_s` 默认值改为 `24 * 60 * 60`（24小时），hk 默认为 `30 * 60`（30分钟）

**冲突时：** 保留本地 24h 值。

---
**文件：** `nanobot/cli/commands.py`

- `agent` 命令启动时自动写日志到 `{workspace}/logs/nanobot.log`（10MB rotation，保留 7 天）

**冲突时：** 保留本地。

---

## 合并冲突处理原则

1. **以上所有文件，本地版本优先**（`git merge -X ours` 或手动选择）
2. **hk 带来的新功能**（新渠道如 Slack 线程隔离、Heartbeat 幂等改进、Discord 断连修复等）直接接受，不与本地独有功能重叠
3. **`session/manager.py`** 冲突时保留本地版本（`last_consolidated` 切片 + `max_age_hours` 过滤）
4. **`bus/events.py`** 合并时确保本地新增字段（`reaction`, `msg_type`, `session_key_override`）不被 hk 版本覆盖丢失
5. **`agent/loop.py`** 合并后必须检查第 9 条所有修复点是否完整，尤其是 `complete_inbound_turn` 和 `history_max_age_hours`
