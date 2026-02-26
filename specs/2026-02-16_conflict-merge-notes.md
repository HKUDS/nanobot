# 冲突合并记录（2026-02-16）

## 目标与范围
本文件记录本轮冲突处理的决策，原则如下：
- 优先保留本地已验证的行为能力
- 吸收上游稳定且必要的改动
- 保持运行时行为连续，避免语义突变

## 已处理文件

### 1) `nanobot/agent/loop.py`

#### 合并目标
在保留本地消息处理能力（ack、SILENT、thinking、工具摘要）的前提下，吸收上游参数接线与记忆归档能力。

#### 保留（本地）
- 出站消息确认机制：`_publish_outbound_with_ack`
- SILENT 机制：`_contains_silent_marker`、`_strip_silent_marker`
- token 用量日志
- 工具调用摘要落盘（虚拟 tool call）
- 扩展推理参数：`thinking`、`thinking_budget`、`effort`
- `memory_daily_subdir` 透传到 `ContextBuilder`

#### 吸收（上游）
- `temperature`、`max_tokens`、`memory_window` 参数与调用链
- 统一斜杠命令：`/new`、`/help`
- 记忆归档入口与偏移追踪：`last_consolidated`
- 记忆归档 JSON 容错解析：`json_repair`
- `process_direct(..., session_key=...)` 兼容模式

#### 明确不采用
- 人工注入伪用户轮次：
  - `"Reflect on the results and decide next steps."`
  - 原因：会改变对话语义、增加 token 成本、影响用户意图建模。

#### 兼容处理
- 新增 `close_mcp()`，作为 `stop_mcp()` 别名，兼容不同调用点。

### 2) `nanobot/agent/memory.py`

#### 合并目标
同时保留 daily notes 架构与上游 HISTORY 架构。

#### 最终结构
- `memory/MEMORY.md`：长期记忆
- `memory/HISTORY.md`：可检索时间线日志（append-only）
- `memory/<daily_subdir>/YYYY-MM-DD.md`（或 `memory/YYYY-MM-DD.md`）：每日笔记

#### 保留（本地）
- `get_today_file`
- `read_today`
- `append_today`
- `get_recent_memories`
- `list_memory_files`
- `daily_subdir` 构造参数

#### 吸收（上游）
- `history_file`
- `append_history(entry)`

#### 上下文策略
- `get_memory_context()` 仅注入：
  - 长期记忆
  - 今日笔记
- `HISTORY.md` 保持“检索日志”定位，不直接自动注入提示词上下文。

### 3) `nanobot/session/manager.py`

#### 合并目标
保留本地工具调用历史窗口裁切能力，同时保留上游记忆归档偏移持久化能力。

#### 保留（本地）
- `get_history(max_messages=75)` 的窗口对齐逻辑：
  - 若窗口起点不是 `user`，向后裁到首个 `user`
  - 保留 `tool_calls`、`tool_call_id`、`name` 字段

#### 吸收（上游）
- `Session.last_consolidated`
- `clear()` 同步重置 `last_consolidated`
- `last_consolidated` 写入/读取 session 元数据
- `SessionManager.invalidate()`

### 4) `nanobot/cli/commands.py`

#### 合并目标
统一 CLI/Gateway 与合并后 `AgentLoop` 的参数、MCP 生命周期调用。

#### 最终决策
- Agent 构造统一使用：
  - `_enabled_mcp_servers(config) or None`
  - `thinking`、`thinking_budget`、`effort`
  - `temperature`、`max_tokens`、`memory_window`
  - `memory_daily_subdir`
- MCP 关闭路径统一为 `close_mcp()`（`finally`）
- 去除重复关闭：不再同时执行 `close_mcp()` 与 `stop_mcp()`
- 单次与交互模式均通过 `process_direct()` 执行，并在结束时显式关闭 MCP

### 5) `nanobot/agent/tools/mcp.py`

#### 合并目标
解决 add/add 冲突，保持既有 MCP 工具命名兼容并修正调用细节。

#### 最终决策
- 保留 `MCPManager` 生命周期方案（`start()` / `stop()` / server task）
- 保留工具命名格式：`mcp__{server}__{tool}`（兼容现有 skills 与调用习惯）
- 采用更稳妥的调用方式：
  - `ClientSession.call_tool(name, arguments=kwargs)`
- 传输支持保留：
  - `stdio`
  - `sse`
  - `streamable-http`（`streamablehttp_client`，与本地 `mcp>=1.0.0` 一致）

## Feature/Bug List

### Feature List
- 保留并增强消息发送可靠性（出站 ack + 错误透传）
- 保留 SILENT 去重机制，避免 message tool 与文本最终回复重复发送
- 吸收并接通模型参数：`temperature` / `max_tokens` / `memory_window`
- 吸收统一命令：`/new` / `/help`
- 记忆体系升级为“三层并存”：`MEMORY.md` + `HISTORY.md` + daily notes
- 增加 `close_mcp()` 兼容入口，统一 MCP 资源释放语义
- 会话归档支持偏移量增量处理（`last_consolidated`）

### Bug List
- 修复冲突态导致的语法/运行阻断（`loop.py` / `memory.py` / `session/manager.py` / `commands.py` / `mcp.py`）
- 修复 MCP 工具调用参数传递方式（改为 `arguments=kwargs`）
- 修复 CLI/Gateway 中 MCP 重复关闭路径（减少重复清理和行为分叉）
- 移除“伪 user 反思轮次”注入，避免对话语义污染与额外 token 开销
- 修复 `memory.py` 冲突态下导入与构造不一致问题（daily 与 history 架构可共存）

## 本轮确认结果

### 冲突状态
- 已无冲突文件：
  - `git diff --name-only --diff-filter=U` 为空
  - 无 `UU/AA/DD/...` 状态

### 本轮处理文件
- `nanobot/agent/loop.py`
- `nanobot/agent/memory.py`
- `nanobot/session/manager.py`
- `nanobot/cli/commands.py`
- `nanobot/agent/tools/mcp.py`

### 已执行验证
- 语法检查通过：
  - `python -m py_compile nanobot/agent/loop.py`
  - `python -m py_compile nanobot/agent/memory.py`
  - `python -m py_compile nanobot/session/manager.py`
  - `python -m py_compile nanobot/cli/commands.py`
  - `python -m py_compile nanobot/agent/tools/mcp.py`
- 定向测试：
  - `pytest -q tests/test_session_manager.py tests/test_consolidate_offset.py tests/test_commands.py`
  - 结果：`38 passed, 3 failed`
  - 失败原因：沙箱权限限制，测试写入 `~/.nanobot/sessions/*.jsonl` 被拒绝（`PermissionError`），非合并逻辑错误。

## 当前状态
- 本轮冲突处理与文档补充已完成。
- 剩余工作为在可写环境做完整功能回归验证。

---

## E2E 回归清单（可执行版）

> 目标：验证“冲突合并后”主链路可用、核心行为不回退、跨渠道关键改动可用。  
> 建议执行顺序：`P0 -> P1 -> P2`。P0 全通过后再进入 P1/P2。

### 0) 执行前准备

1. 使用可写的 HOME（避免沙箱权限影响）：
   - `export HOME=/tmp/nanobot-e2e-home`
   - `mkdir -p "$HOME"`
2. 准备最小配置：
   - `nanobot onboard`
   - 在 `$HOME/.nanobot/config.json` 配置可用模型 API Key。
3. 建议开启日志窗口（便于定位）：
   - `tail -f $HOME/.nanobot/logs/nanobot_$(date +%F).log`

### P0（必须通过）

1. 启动烟雾测试（CLI 基本可用）
   - 命令：
     - `nanobot status`
     - `nanobot agent -m "/help"`
   - 预期：
     - 命令可执行，无 import/runtime 异常
     - `/help` 返回命令说明（含 `/new`、`/help`）

2. `/new` 会话重置 + 异步归档触发
   - 命令：
     - `nanobot agent --session e2e:newtest -m "我叫Alice，喜欢Rust"`
     - `nanobot agent --session e2e:newtest -m "请记住我在西雅图"`
     - `nanobot agent --session e2e:newtest -m "/new"`
     - `nanobot agent --session e2e:newtest -m "我刚刚说我叫什么？"`
   - 预期：
     - `/new` 返回 `New session started. Memory consolidation in progress.`
     - 新会话不再直接继承旧对话上下文
     - `memory/HISTORY.md` 后续出现归档条目（允许异步延迟）

3. 记忆增量归档偏移（`last_consolidated`）
   - 配置：将 `agents.defaults.memory_window` 临时改小（如 `6`）
   - 命令：
     - 同一 session 连续发送 10+ 轮消息，触发归档
     - 再发送 4~6 轮，触发第二次归档
   - 预期：
     - 第二次归档只处理新增消息，不重复归档旧消息
     - 对应 session jsonl 的 `last_consolidated` 单调前进（`/new` 例外会重置）

4. MCP 生命周期与工具发现
   - 命令：
     - `nanobot mcp list`
     - `nanobot mcp tools`
     - `nanobot agent -m "列出你可用的 mcp 工具名"`
   - 预期：
     - 能发现已启用 MCP 工具
     - 工具名格式为 `mcp__{server}__{tool}`
     - 退出时无重复关闭 MCP 的报错

5. Cron 三种调度（`every` / `cron` / `at`）
   - 命令：
     - `nanobot cron add --name "e2e-every" --message "ping every" --every 60`
     - `nanobot cron add --name "e2e-cron" --message "ping cron" --cron "*/5 * * * *"`
     - `nanobot cron add --name "e2e-at" --message "ping once" --at "2026-02-16T23:59:00"`
     - `nanobot cron list --all`
   - 预期：
     - 三类任务都可创建
     - `at` 类型执行后应一次性完成并按配置自动清理或禁用
     - `cron` 下次执行时间符合本地时区

### P1（强烈建议）

1. Telegram 命令统一转发
   - 步骤：
     - 在 Telegram 对 bot 发送 `/new`、`/help`
   - 预期：
     - 两个命令均由 AgentLoop 统一处理并返回
     - 无旧 `/reset` 专有逻辑依赖

2. Feishu post 入站解析 + 卡片渲染
   - 步骤：
     - 发送 `post`（含标题/链接/@）
     - 让 bot 回复包含 `# 标题`、Markdown 表格、代码块
   - 预期：
     - 入站文本提取正确（标题、链接文本、@ 提及可见）
     - 出站卡片中标题/表格/代码块无明显错位或丢失

3. WhatsApp Bridge 鉴权
   - 步骤：
     - 启动 bridge 时设置 `BRIDGE_TOKEN`
     - 使用正确 token 连接一次，再用错误 token 连接一次
   - 预期：
     - 正确 token 可连接并收发
     - 错误 token 被拒绝（鉴权失败）
     - bridge 仅监听 `127.0.0.1`

4. 长连接自动重连（QQ / Feishu / DingTalk）
   - 步骤：
     - 人工断网或杀掉连接后恢复网络
   - 预期：
     - 渠道端记录重连日志
     - 约 5 秒级退避后可恢复

### P2（回归增强）

1. Provider 边界参数
   - 步骤：
     - 将 `max_tokens` 配置为 `0` 或负数做一次请求
   - 预期：
     - 不因 `max_tokens` 非法直接报错（应被安全钳制）

2. `custom` provider 选择链路
   - 步骤：
     - 配置 `providers.custom.api_key/api_base`
     - 选择一个 openai-compatible 模型做请求
   - 预期：
     - 请求可经 `custom` 提供方成功发送

3. 子代理工具集回归
   - 步骤：
     - 触发 `spawn` 子任务，让其执行读取/编辑文件
   - 预期：
     - 子代理可使用 `read/write/edit/list/exec/web` 工具链
     - 最终 summary 正常回主对话

### 失败时优先排查

1. 环境/权限问题优先：
   - `HOME` 是否可写
   - 是否能写 `$HOME/.nanobot/logs`、`$HOME/.nanobot/sessions`
2. 依赖问题：
   - `mcp`、`json-repair` 是否安装
3. 配置问题：
   - `providers.*.api_key` 是否有效
   - `mcp.enabled` 与 `mcp.servers.*.enabled` 是否匹配
4. 渠道问题：
   - token/secret 是否正确
   - 代理/网络连通性是否正常

### 建议验收门槛

1. `P0` 全通过
2. 你实际启用的渠道对应 `P1` 用例全通过
3. 至少完成 1 项 `P2`（建议 provider 边界）
