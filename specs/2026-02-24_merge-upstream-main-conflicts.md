# merge upstream/main 冲突说明（2026-02-24）

- 分支：`sync-upstream-main-20260224`
- 合并基线：`upstream/main@30361c9`
- 当前未解决冲突文件：0 个（`git diff --name-only --diff-filter=U`）

## 本轮已确认策略快照（用于上下文压缩）

- 已处理并暂存（含策略）：
  - `nanobot/session/manager.py`：并集合并，保留 upstream `unconsolidated` 语义 + 本地 user-turn 对齐与日志。
  - `nanobot/cron/service.py`：采用 upstream 写法，`write_text(..., encoding="utf-8")`。
  - `nanobot/channels/base.py`：并集，`timestamp` 与 `session_key` 同时保留。
  - `nanobot/config/schema.py`：并集，保留 `http` + `send_progress/send_tool_hints`；Agent 默认值先保留本地（0.7/50/50 + thinking*）。
  - `nanobot/channels/manager.py`：保留 HTTP channel + outbound waiter ACK；日志改 `{}` 风格。
  - `nanobot/agent/context.py`：按用户要求，完全采用本地版本（HEAD）。
  - `README.md`：并集合并（Provider tip 合并；MCP Servers 与 Heartbeat 两个小节并存）。
  - `nanobot/agent/memory.py`：并集，保留 daily notes 能力 + upstream `consolidate()` 接口。
  - `nanobot/channels/dingtalk.py`：以本地逻辑为主（群聊识别/媒体处理）；发送 JSON 增加 `ensure_ascii=False`。
  - `nanobot/bus/queue.py`：保留本地增强（inbound 聚合 + waiter ACK），不做结构性删减。
  - `nanobot/cli/commands.py`：参数并集（含 `channels_config`）；保留 `try/finally`；修复 interactive 模式 `publish_inbound`。
  - `nanobot/agent/tools/mcp.py`：保留 `MCPManager` 架构，吸收超时与文本解析增强，并补 `connect_mcp_servers` 兼容函数。
  - `nanobot/agent/tools/message.py`：保留本地 `sticker/reaction/media` 能力，合入上游 `_sent_in_turn/start_turn` 防重复发送。
  - `nanobot/providers/litellm_provider.py`：去掉本地 Gemini 专用兼容逻辑，保留上游 `cache_control + sanitize_messages`，并保留本地日志/容错增强。
  - `nanobot/channels/telegram.py`：保留本地媒体发送、`sticker/reaction`、`silent`；`reply_to` 采用“显式 `msg.reply_to` 优先，`reply_to_message` 开启时回落 metadata.message_id”。
  - `nanobot/agent/loop.py`：以本地主流程为主，吸收上游关键修复（`channels_config`、`_sent_in_turn` 判重、`_progress/_tool_hint` 协议、filesystem tool `workspace` 参数）。

- 当前未解决冲突文件（待继续讨论）：
  - 无

- 备注：
  - `upstream` 在 `nanobot/bus/queue.py` 的主要变更是提交 `0001f28`（简化 MessageBus，移除 dead pub/sub 代码）；本轮未采纳该简化。

## 冲突文件总览

1. `nanobot/agent/context.py`
2. `nanobot/agent/loop.py`
3. `nanobot/agent/memory.py`
4. `nanobot/agent/tools/mcp.py`
5. `nanobot/agent/tools/message.py`
6. `nanobot/bus/queue.py`
7. `nanobot/channels/base.py`
8. `nanobot/channels/dingtalk.py`
9. `nanobot/channels/manager.py`
10. `nanobot/channels/telegram.py`
11. `nanobot/cli/commands.py`
12. `nanobot/config/schema.py`
13. `nanobot/providers/litellm_provider.py`
14. `nanobot/session/manager.py`

## 1) ✅ nanobot/agent/context.py

- 冲突1（行 86-90）
  - 本地：增加 `memory_daily_subdir`，支持可配置 daily memory 子目录。
  - upstream：同位置是基础 system prompt 内容（上下文模板调整）。
  - 冲突点：`context builder` 在“memory 路径拼接”与“提示词模板整理”两条改动线重叠。
- 冲突2（行 110-139）
  - 本地：更细化 `message tool` 使用规则（默认直接回复、特定场景才用 tool）。
  - upstream：新增 tool 调用行为规范（先说明意图、不要预告结果）。
  - 冲突点：system prompt 规则集合不同，需要合并成统一行为准则。

## 2) ✅ nanobot/agent/loop.py

- 冲突1（行 7-13）
  - 本地：额外引入 `uuid/datetime/Path/json_repair` 等依赖。
  - upstream：该段 import 更简化。
  - 冲突点：导入集合来自两套 loop 实现。
- 冲突2（行 57-68）
  - 本地默认：`max_iterations=50, temperature=0.7, memory_window=50`。
  - upstream默认：`max_iterations=40, temperature=0.1, memory_window=100`。
  - 冲突点：核心推理参数默认值不一致。
- 冲突3（行 75-87）
  - 本地：构造参数有 `thinking/thinking_budget/effort/memory_daily_subdir`。
  - upstream：构造参数新增 `channels_config`。
  - 冲突点：`AgentLoop.__init__` API 扩展方向不同。
- 冲突4（行 123-140）
  - 本地：使用 `_mcp_manager + consolidation_running/pending`。
  - upstream：使用 `AsyncExitStack + _mcp_connected/_consolidation_tasks/locks`。
  - 冲突点：MCP 生命周期与记忆压缩并发控制模型不同。
- 冲突5（行 146-285）
  - 本地：显式逐个注册工具，并引入 outbound ack 的 `MessageTool(send_callback=...)`。
  - upstream：批量注册工具类，MCP/消息流实现更轻量。
  - 冲突点：工具注册策略和消息发送确认机制差异大。
- 冲突6（行 478-489）
  - 本地：`on_progress` 类型更具体，返回值类型约束更强。
  - upstream：`Callable[..., Awaitable[None]]` 更宽松。
  - 冲突点：类型签名收紧 vs 放宽。
- 冲突7（行 525-531）
  - 本地：`json.dumps(tc.arguments)`。
  - upstream：`json.dumps(..., ensure_ascii=False)`。
  - 冲突点：tool 参数序列化是否保留非 ASCII 字符。
- 冲突8（行 594-616）
  - 本地：无最终回复时统一 fallback 警告逻辑。
  - upstream：仅在达到迭代上限时触发特定 fallback。
  - 冲突点：无回复兜底条件与文案不同。
- 冲突9（行 620-672）
  - 本地：对应区域为空/已重构。
  - upstream：保留主 `run()` 消费循环实现。
  - 冲突点：消息主循环实现位置与结构差异。
- 冲突10（行 677-707）
  - 本地：`_process_message` 的系统消息处理更直接。
  - upstream：系统消息增加 `chat_id` 溯源解析说明。
  - 冲突点：system channel 消息路由规则差异。
- 冲突11（行 713-847）
  - 本地：`/new` 等命令处理与会话归档流程更完整。
  - upstream：命令处理简化版本。
  - 冲突点：slash command 语义和归档行为不一致。
- 冲突12（行 856-1130）
  - 本地：保存会话+工具轨迹、内存压缩与归档逻辑更重。
  - upstream：`_save_turn` + `MemoryStore.consolidate()` 轻量方案。
  - 冲突点：会话持久化与记忆压缩路径是两套实现。
- 冲突13（行 1141-1145）
  - 本地：`start_mcp()`。
  - upstream：`_connect_mcp()`。
  - 冲突点：MCP 启动入口命名与实现不同。

## 3) ✅ nanobot/agent/memory.py

- 冲突1（行 3-9）
  - 本地：偏同步读写工具，依赖 `datetime`。
  - upstream：新增 `from __future__ import annotations` 与 `json`，为异步 consolidate 铺路。
  - 冲突点：模块定位从“读写 helper”向“可异步 consolidate”演进。
- 冲突2（行 130-217）
  - 本地：拼接 long-term/today 文本输出。
  - upstream：新增 `consolidate()` 主逻辑接口。
  - 冲突点：memory 职责边界（仅读取展示 vs 包含压缩归档）。

## 4) ✅ nanobot/agent/tools/mcp.py

- 冲突1（行 3-10）
  - 本地：保留基础 asyncio 结构。
  - upstream：引入 `AsyncExitStack`。
  - 冲突点：MCP 连接资源释放策略不同。
- 冲突2（行 22-44）
  - 本地：`MCPTool` 构造函数签名更通用。
  - upstream：构造函数绑定 `session + tool_def + timeout`。
  - 冲突点：工具实例化时是否固定绑定会话及原始 tool 定义。
- 冲突3（行 59-293）
  - 本地：调用后做结果拼装/文本提取。
  - upstream：加入 `wait_for` 超时控制与类型分支处理。
  - 冲突点：MCP 调用超时与结果格式化策略不同。

## 5) ✅ nanobot/agent/tools/message.py

- 冲突1（行 3-8）
  - 本地：引入 `Path`（媒体文件处理）。
  - upstream：无 `Path` 依赖。
  - 冲突点：是否支持本地媒体附件能力。
- 冲突2（行 22-26）
  - 本地：默认上下文字段为 `default_metadata`。
  - upstream：默认字段为 `default_message_id`。
  - 冲突点：message tool 上下文载荷类型不同。
- 冲突3（行 31-50）
  - 本地：`set_context(..., metadata=...)`。
  - upstream：`set_context(..., message_id=...)` 且跟踪 `_sent_in_turn`。
  - 冲突点：上下文模型与“本轮是否已发送”状态管理不同。
- 冲突4（行 65-74）
  - 本地：tool 描述包含 media/sticker/reaction。
  - upstream：简化描述，仅文本发送。
  - 冲突点：工具能力范围描述不一致。
- 冲突5（行 116-120）
  - 本地：`content` 可空。
  - upstream：`content` 必填。
  - 冲突点：接口参数约束不同。
- 冲突6（行 132-138）
  - 本地：标准化 `content/sticker/reaction`。
  - upstream：`message_id` 兜底赋值。
  - 冲突点：输入清洗重点不同。
- 冲突7（行 146-183）
  - 本地：强校验 + 支持贴纸/反应/媒体。
  - upstream：直接构造 `OutboundMessage` 发送。
  - 冲突点：发送流程复杂度与功能面差异大。
- 冲突8（行 188-201）
  - 本地：返回更细粒度投递结果信息。
  - upstream：只返回简化成功文案并设置 `_sent_in_turn`。
  - 冲突点：回执信息与回合状态标记策略不同。

## 6) ✅ nanobot/bus/queue.py

- 冲突1（行 4-10）
  - 本地：新增 `datetime/logger/callback` 相关依赖。
  - upstream：保持简化 import。
  - 冲突点：消息总线增强功能依赖不一致。
- 冲突2（行 26-125）
  - 本地：支持 outbound subscriber、waiter、active inbound session 管理。
  - upstream：仅基础 inbound/outbound 队列。
  - 冲突点：消息总线是否承担 ACK/订阅/并发会话控制。
- 冲突3（行 133-195）
  - 本地：新增 `subscribe_outbound` 等 API。
  - upstream：对应 API 不存在。
  - 冲突点：bus API 面扩展与兼容性。

## 7) ✅ nanobot/channels/base.py

- 冲突1（行 110-114）
  - 本地：`OutboundMessage` 增加 `timestamp`。
  - upstream：`OutboundMessage` 增加 `session_key`。
  - 冲突点：出站消息扩展字段冲突（时间戳 vs 会话覆写键）。
- 冲突2（行 127-131）
  - 本地：文档说明 `timestamp`。
  - upstream：文档说明 `session_key`。
  - 冲突点：字段语义定义需统一。

## 8) ✅ nanobot/channels/dingtalk.py

- 冲突1（行 78-102）
  - 本地：补充分组/私聊识别逻辑。
  - upstream：仅基础接收日志。
  - 冲突点：入站会话类型识别能力。
- 冲突2（行 347-384）
  - 本地：区分群发接口和私聊接口 payload。
  - upstream：按用户 staffId 发送简化路径。
  - 冲突点：出站发送 API 选择策略不同。
- 冲突3（行 443-474）
  - 本地：`chat_id` 兜底与分组标记日志。
  - upstream：简单日志。
  - 冲突点：入站映射字段与可观测性增强是否保留。

## 9) ✅ nanobot/channels/manager.py

- 冲突1（行 138-153）
  - 本地：该片段包含 HTTP channel 初始化逻辑邻接改动。
  - upstream：主要是日志格式替换（`f-string` -> `{}`）。
  - 冲突点：功能改动与日志风格改动重叠。
- 冲突2（行 223-235）
  - 本地：发送失败时会回填 `bus waiter` 失败态。
  - upstream：仅记录 error/warning。
  - 冲突点：是否保留发送 ACK 失败回传机制。

## 10) ✅ nanobot/channels/telegram.py

- 冲突1（行 11-15）
  - 本地：引入 `InputMediaPhoto/ReactionTypeEmoji`。
  - upstream：引入 `ReplyParameters`。
  - 冲突点：能力重点（媒体/reaction vs reply 参数）不同。
- 冲突2（行 300-436）
  - 本地：非法 `chat_id` 时抛异常并走统一异常处理。
  - upstream：非法 `chat_id` 直接返回，同时设置 reply 参数流。
  - 冲突点：错误处理策略（fail-fast vs graceful return）。
- 冲突3（行 445-510）
  - 本地：媒体发送有错误分级和文件名追踪。
  - upstream：媒体发送实现更简化。
  - 冲突点：附件发送鲁棒性逻辑差异。
- 冲突4（行 681-698）
  - 本地：长消息日志截断策略更细。
  - upstream：简单预览 + `chat_id` 字符串化处理。
  - 冲突点：日志可观测性与字段规范化处理不同。

## 11) ✅ nanobot/cli/commands.py

- 冲突1（行 333-342）
  - 本地：传入 `_enabled_mcp_servers + thinking*` 参数。
  - upstream：传入 `config.tools.mcp_servers + channels_config`。
  - 冲突点：CLI 构造 `AgentLoop` 的参数集合不一致。
- 冲突2（行 508-517）
  - 本地：同上（另一处命令路径）。
  - upstream：同上（另一处命令路径）。
  - 冲突点：同类参数冲突重复出现。
- 冲突3（行 539-551）
  - 本地：`process_direct` 增加 `try` 包裹路径。
  - upstream：输出打印位置与上下文管理略不同。
  - 冲突点：CLI 交互态异常处理与打印时机。
- 冲突4（行 618-631）
  - 本地：对应片段为空。
  - upstream：新增 turn 同步控制（`turn_done/turn_response`）。
  - 冲突点：channel 模式 CLI 的回合同步能力是否引入。

## 12) ✅ nanobot/config/schema.py

- 冲突1（行 181-186）
  - 本地：该位置保留 `http` channel 配置结构。
  - upstream：新增 `send_progress/send_tool_hints`。
  - 冲突点：channel 配置字段扩展冲突。
- 冲突2（行 204-217）
  - 本地默认：`temperature=0.7, max_tool_iterations=50, memory_window=50`。
  - upstream默认：`temperature=0.1, max_tool_iterations=40, memory_window=100`。
  - 冲突点：Agent 默认策略参数不一致。

## 13) nanobot/providers/litellm_provider.py

- 冲突1（行 112-147）
  - 本地：该区域为空。
  - upstream：新增 `_supports_cache_control()`。
  - 冲突点：是否按模型能力动态启用 `cache_control`。
- 冲突2（行 158-257）
  - 本地：新增 `_preview_text()` 用于日志预览。
  - upstream：新增 `_sanitize_messages()` 过滤非标准消息字段。
  - 冲突点：日志可观测增强 vs 请求消息规范化增强。
- 冲突3（行 283-291）
  - 本地：直接解析 `model`。
  - upstream：保留 `original_model` 并据此判定 `cache_control`。
  - 冲突点：模型路由与特性判断流程不同。
- 冲突4（行 599-607）
  - 本地：`reasoning_content` 原值透传。
  - upstream：`reasoning_content` 额外做 `or None` 归一。
  - 冲突点：空值归一化处理差异。

## 14) ✅ nanobot/session/manager.py

- 冲突1（行 47-88）
  - 本地：`get_recent_history` 的说明与截断逻辑按现有会话窗口。
  - upstream：改为“对齐到 user turn 的未 consolidate 消息窗口”。
  - 冲突点：历史窗口切分规则（普通条数窗口 vs user-turn 对齐窗口）。

## 建议讨论顺序

1. `nanobot/agent/loop.py`（最大风险，涉及主流程、MCP、memory consolidation）
2. `nanobot/agent/tools/message.py` + `nanobot/bus/queue.py` + `nanobot/channels/manager.py`（消息投递 ACK 机制链路）
3. `nanobot/agent/tools/mcp.py` + `nanobot/cli/commands.py` + `nanobot/config/schema.py`（参数与生命周期）
4. `nanobot/channels/*`（DingTalk/Telegram 行为分歧）
5. `nanobot/providers/litellm_provider.py` + `nanobot/session/manager.py` + `nanobot/agent/context.py` + `nanobot/agent/memory.py`
