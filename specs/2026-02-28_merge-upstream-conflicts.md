# Merge Upstream Conflicts — 2026-02-28

## 概览

从 upstream/main 合并到本地 `merge-upstream-0228` 分支，共 10 个文件存在冲突。

| # | 文件 | 冲突数 | 复杂度 |
|---|------|--------|--------|
| 1 | `nanobot/agent/context.py` | 1 | 低 |
| 2 | `nanobot/agent/loop.py` | 10 | **高** |
| 3 | `nanobot/agent/tools/message.py` | 1 | 低 |
| 4 | `nanobot/channels/manager.py` | 1 | 低 |
| 5 | `nanobot/channels/telegram.py` | 2 | 中 |
| 6 | `nanobot/cli/commands.py` | 1 | 低 |
| 7 | `nanobot/providers/litellm_provider.py` | 1 | 低 |
| 8 | `nanobot/skills/memory/SKILL.md` | delete/modify | 低 |
| 9 | `nanobot/utils/helpers.py` | 1 | 中 |
| 10 | `tests/test_heartbeat_service.py` | 3 | 中 |

---

## 逐文件冲突分析与决策

### 1. `nanobot/agent/context.py` — system prompt 中记忆路径描述 ✅

- **OURS**: `Memory files` / `Daily notes` / `History log` 三行
- **THEIRS**: `Long-term memory` + `History log` 两行，新增描述 `(write important facts here)` 和 `Each entry starts with [YYYY-MM-DD HH:MM]`
- **决策**: `合并双方`
- **处理**: 保留 OURS 的三行结构（Memory files / Daily notes / History log），采纳 THEIRS 的补充说明文案

### 2. `nanobot/agent/loop.py` — 主循环（10 处冲突，最复杂）✅

冲突点与决策：

**A. imports** — 保留双方（`uuid`/`datetime` + `weakref`），移除不需要的 `AsyncExitStack`

**B. `__init__` 属性** — 取 THEIRS 的 `_consolidating` + `_consolidation_locks`(WeakValueDict) + `_consolidation_tasks`，删除 OURS 的 `_consolidation_running_keys`/`_consolidation_pending_keys`；THEIRS 的 MCP 属性（`_mcp_servers`/`_mcp_stack`等）不保留，继续用 OURS 的 `_mcp_manager` 体系

**C. `run()`/`_dispatch()`/`_handle_stop()`/`_set_tool_context()`** — 取 OURS 的完整调度体系（支持 `/stop` 取消、Telegram typing 清理、subagent 取消）；`_set_tool_context` 保留 OURS 明确版本（传整个 metadata 而非仅 message_id）

**D. agent loop else 分支** — 取 OURS 的 `continue` + 详细空响应处理，采纳 THEIRS 的 `finish_reason == "error"` 提前 break（防止 error 响应毒化 session，upstream #1303）

**E. `_run_agent_loop` return** — 取 OURS 的 `return final_content, last_finish_reason, tool_use_log`

**F. `/new` consolidation** — 取 THEIRS 同步等待模式：先获取 lock，consolidation 成功才清 session，失败则保留数据并提示重试

**G. 自动 consolidation 触发** — 取 THEIRS 的 `unconsolidated >= memory_window` 触发机制，在 `_process_message` 中 build_messages 前执行

**清理**：删除 OURS 已废弃的 `_should_schedule_consolidation()`（`return False` 死代码）和 `_schedule_consolidation()` 方法，以及 `_process_message`/`_process_system_message` 中对它们的调用

### 3. `nanobot/agent/tools/message.py` — 消息发送后标记 ✅

- **OURS**: 无条件设 `self._sent_in_turn = True`，详细返回信息（reaction/sticker/attachment 分列）
- **THEIRS**: 仅当 channel/chat_id 匹配默认值时才设 `_sent_in_turn = True`，简略返回
- **决策**: `合并双方` — 采用 THEIRS 的条件判断 + OURS 的详细返回信息
- **处理**: `_sent_in_turn` 只在回复原始会话时置 True（防止跨渠道发送抑制默认回复），返回信息保留 reaction/sticker/attachment 细分

### 4. `nanobot/channels/manager.py` — 渠道注册 ✅

- **OURS**: 新增 HTTP channel 注册块
- **THEIRS**: 新增 Matrix channel 注册块
- **决策**: `保留双方` — 两个渠道互不冲突，合并即可
- **处理**: 在 QQ channel 之后依次添加 HTTP channel 和 Matrix channel 注册块，保留双方完整代码

### 5. `nanobot/channels/telegram.py` — Telegram 渠道（2 处）✅

冲突 1 — `__init__` 属性:
- **OURS**: 新增 `_recent_messages` 去重 + poll error 抑制属性
- **THEIRS**: 新增 `_media_group_buffers/tasks` 媒体组支持
- **决策**: `保留双方`
- **处理**: 合并所有属性，先 OURS 再 THEIRS

冲突 2 — 消息处理流程:
- **OURS**: 带截断的 log preview + `_remember_message` 索引
- **THEIRS**: 简单 log + media group 缓冲聚合逻辑（重复定义了 `str_chat_id`）
- **决策**: `合并双方`
- **处理**: 保留 OURS 的 log preview + remember_message，接入 THEIRS 的 media group 缓冲逻辑，去掉重复的 `str_chat_id` 定义

### 6. `nanobot/cli/commands.py` — agent 命令启动 ✅

- **OURS**: 删除了 `sync_workspace_templates` 调用
- **THEIRS**: 保留 `sync_workspace_templates(config.workspace_path)` 调用
- **决策**: `采用 THEIRS`
- **处理**: 恢复调用，因为 helpers.py 已保留了该函数且 import 已存在

### 7. `nanobot/providers/litellm_provider.py` — imports ✅

- **OURS**: `import re` + `import codecs`
- **THEIRS**: `import secrets` + `import string`
- **决策**: `保留双方` — 不同功能的 import，全部保留
- **处理**: 合并为 `import codecs / import re / import secrets / import string`（按字母序）

### 8. `nanobot/skills/memory/SKILL.md` — delete vs modify ✅

- **OURS**: 文件已删除
- **THEIRS**: 新增 memory skill（两层记忆体系：MEMORY.md + HISTORY.md，`always: true`）
- **决策**: `采用 THEIRS` — 恢复文件，与 context.py 中的记忆路径描述配套

### 9. `nanobot/utils/helpers.py` — 工具函数 ✅

- **OURS**: 新增 `get_logs_path()` + `setup_file_logging()` + `setup_heartbeat_logging()` + `parse_session_key()`
- **THEIRS**: 新增 `sync_workspace_templates()` 函数
- **决策**: `保留双方` — 两个函数集互不冲突
- **处理**: 先放 OURS 的 logging/parse 函数，再放 THEIRS 的 sync_workspace_templates，全部保留

### 10. `tests/test_heartbeat_service.py` — 测试（3 处）✅

- **OURS**: `StubProvider`（继承 `LLMProvider`，有类型签名），测试 `test_decide_uses_configured_model` + `test_trigger_now_executes_tasks_from_tool_call`
- **THEIRS**: `DummyProvider`（简易实现），测试 `test_decide_returns_skip_when_no_tool_call` + `test_trigger_now_returns_none_when_decision_is_skip`
- **决策**: `合并双方`
- **处理**:
  - 统一用 OURS 的 `StubProvider`（更规范，继承基类 + 类型签名），改为接受 `list[LLMResponse]` 以兼容 THEIRS 的多响应模式
  - 保留全部 5 个测试用例（OURS 3 + THEIRS 2）
  - model 统一为 `stub/heartbeat`

---

## 解决顺序建议

1. **先解决简单的** (#4, #7, #9) — 直接保留双方
2. **中等复杂度** (#1, #3, #5, #6, #8, #10) — 逐个讨论
3. **最后解决 loop.py** (#2) — 最复杂，需要仔细对比

## 待讨论问题

- [ ] HISTORY.md 是否采纳？
- [ ] memory SKILL.md 是否恢复？
- [ ] `sync_workspace_templates` 是否保留？
- [ ] loop.py 中 MCP 支持、WeakValueDictionary、_strip_think 等 upstream 新特性如何整合？
