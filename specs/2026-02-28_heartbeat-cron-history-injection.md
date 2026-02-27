# Heartbeat & Cron 通知消息注入 Session History

## 问题描述

心跳和 cron 执行完毕后，通知消息通过 `bus.publish_outbound()` 直接发送给用户，不进入任何 session history。导致用户回复时，agent 完全不知道自己发过什么通知，上下文断链。

**复现场景：**
1. 心跳触发 → agent 检查待办 → 发通知"你下午3点有个会"
2. 用户回复"推迟到4点"
3. agent 收到回复但 history 里没有自己的通知，不知道用户在说什么

Cron 的 deliver 通知也有同样问题。

## 代码分析（现状）

定位在 `nanobot/cli/commands.py` 的 gateway 回调：

1. `on_cron_job()` 固定使用 `session_key=f"cron:{job.id}"` 执行 `agent.process_direct(...)`。
2. `on_heartbeat_execute()` 固定使用 `session_key="heartbeat"` 执行 `agent.process_direct(...)`。
3. 两者后续通知都通过 `bus.publish_outbound(...)` 直接发送到目标 channel/chat。

结果是：通知文本虽然已生成并发出，但被写入的是“内部 session”（`cron:*` / `heartbeat`），不是用户实际回复所在的 `channel:chat_id` session，因此上下文断链。

## 期望行为

- 心跳/cron 产生的通知消息应进入目标 channel 的 session history
- 用户回复时 agent 能看到完整上下文
- 参考 `subagent._announce_result()` 通过 `bus.publish_inbound()` 注入的模式，这是目前唯一正确处理了 history 注入的路径

## 验收标准

- [x] 心跳通知进入目标 session history，用户回复时 agent 有上下文
- [x] Cron 通知（deliver=True）同上
- [x] 不影响 heartbeat/cron 的执行逻辑和 subagent 现有逻辑
- [x] lint / type check 通过

## 实施方案

### 1) 将“可投递通知”的执行 session 路由到目标会话

新增两个 helper（`nanobot/cli/commands.py`）：

- `_route_session_key(channel, chat_id) -> "channel:chat_id"`
- `_cron_execution_session_key(job_id, deliver, channel, chat_id, to)`
  - `deliver=True` 且有 `to`：写入目标用户 session
  - 其他情况：保持原行为，写入 `cron:{job_id}`

`on_cron_job()` 改为先计算 `target_channel/target_chat_id` 和 `session_key`，再执行 `agent.process_direct(...)`。

### 2) Heartbeat 写入实际目标会话

`on_heartbeat_execute()` 改为使用 `_route_session_key(channel, chat_id)` 作为 `session_key`，不再写入固定 `heartbeat` session。

同时增加 `heartbeat_target` 缓存，确保 `on_heartbeat_notify()` 使用与本次 execute 相同的 target 发送通知，避免 execute/notify 间 target 漂移。

### 3) 保持通知发送链路不变

仍使用 `bus.publish_outbound(...)` 发消息，不改 heartbeat/cron 执行与投递流程；仅修正“消息写入哪个 session”的路由。

## 验证结果

测试（`PYTHONPATH="$PWD"`）：

```bash
pytest tests/test_commands.py tests/test_heartbeat_service.py tests/test_cron_service.py tests/test_agent_loop_model_override.py
```

结果：`24 passed`

新增用例（`tests/test_commands.py`）：

- `test_route_session_key_uses_channel_and_chat`
- `test_cron_execution_session_key_uses_target_session_for_deliver`
- `test_cron_execution_session_key_keeps_job_session_for_non_deliver`
- `test_cron_execution_session_key_keeps_job_session_when_target_missing`

lint（针对改动文件，忽略仓库既有 I001/W293 噪音）：

```bash
ruff check nanobot/cli/commands.py tests/test_commands.py --ignore I001,W293
```

结果：通过。
