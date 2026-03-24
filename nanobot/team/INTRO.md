# Nano Team Mode

用一句话描述：用户给出一个目标，LLM 自动规划出 2-3 人的微型团队，每个成员作为独立 worker 异步执行任务，通过共享看板和邮箱协作，用户可以随时审批、追加指令或停止。

## 架构总览

```
用户指令
  │
  ▼
AgentLoop ──/team <goal>──► TeamManager.start_or_route_goal()
  │                              │
  │                         LLM 生成计划（mission / members / tasks）
  │                              │
  │                         创建 TeamRuntime（磁盘持久化）
  │                              │
  │                         为每个 member 启动 asyncio worker
  │                              │
  │         ┌────────────────────┼────────────────────┐
  │         ▼                    ▼                    ▼
  │    Worker A             Worker B             Worker C
  │    (researcher)         (builder)            (...)
  │         │                    │                    │
  │         ├─ board: claim/complete tasks            │
  │         ├─ mailbox: send/read messages            │
  │         └─ file/shell/web tools                   │
  │                              │
  │         ◄────── events.jsonl / tasks.json ───────►
  │
  ▼
用户查看状态 (/team status)、审批 (/team approve)、停止 (/team stop)
```

## 模块职责

```
nanobot/team/
├── __init__.py    瘦入口，re-export TeamManager / TeamRuntime / TeamState
├── manager.py     TeamManager — 运行时生命周期、LLM 规划、worker 调度
├── state.py       纯数据结构：Task, Teammate, Mail, TeamState, TeamRuntime
├── board.py       任务看板：claim / complete / approve / reject（文件锁保证并发安全）
├── mailbox.py     消息邮箱：send / broadcast / read_unread（JSONL 追加写，自动截断到 200 条）
├── tools.py       暴露给 LLM 的工具：TeamTool（管理端）、TeamWorkerTool（worker 端）
└── _filelock.py   跨平台文件锁（Unix fcntl / Windows msvcrt）
```

### 数据流

- **state.py** 定义所有数据结构，不含业务逻辑，纯 dataclass + JSON 序列化。
- **board.py** 管理 `tasks.json`——所有对任务状态的变更都经过 `_locked_update()`，通过文件锁保证多个 worker 并发写入安全。
- **mailbox.py** 管理 `mailbox.jsonl`——worker 之间、lead 与 worker 之间的消息通信。同样使用文件锁。每次写入后自动截断保留最近 200 条，防止文件无限增长。
- **tools.py** 包含两个 Tool 类：
  - `TeamTool`：暴露给主 agent 的管理接口（create / shutdown / approve / reject / board / message / add_task）
  - `TeamWorkerTool`：暴露给每个 worker 的协作接口（board / claim / complete / submit_plan / mail_send / mail_read）

### TeamManager 核心流程

1. **start_or_route_goal(session_key, goal)**
   - 如果当前 session 已有活跃团队 → 将指令路由为增量任务
   - 否则 → 调用 LLM 生成初始计划（mission + members + tasks），校验后创建 runtime，启动 workers

2. **Worker 执行循环** (`_run_worker`)
   - 每轮：检查邮箱 → 调用 LLM → 执行工具调用 → 检查任务状态
   - Worker 自主通过 `team_worker` tool 操作看板：claim 任务 → 执行 → complete
   - 如果任务 `requires_approval`，worker 提交 plan 后暂停等待用户审批

3. **审批流程**
   - worker `submit_plan` → 任务进入 `awaiting_approval`
   - 非 CLI 渠道（如 Telegram）：自动推送审批提示给用户
   - 用户可通过 `/team approve <id>` / `/team reject <id> <reason>` / `/team manual <id> <instruction>` 操作
   - 也支持自然语言审批（中英文关键词匹配）

4. **风险门控**
   - 包含 `rm -rf` / `drop table` 等危险关键词的指令会被暂停
   - 用户需 `/team confirm <instruction>` 确认后才继续执行

### 磁盘持久化结构

```
workspace/teams/<session_key>/<run_id>/
├── config.json      TeamState（team_id, mission, members, status）
├── tasks.json       所有 Task 的状态
├── mailbox.jsonl    消息记录
├── events.jsonl     事件日志（team_started, task_added, worker_update, ...）
├── NOTES.md         共享笔记
└── workers/
    ├── researcher/  worker 工作目录
    └── builder/
```

团队状态持久化到磁盘。进程重启后，`_auto_attach()` 会自动发现未完成的 run 并恢复执行。

## 使用方式

### CLI 交互模式

```bash
nanobot agent                        # 进入交互模式
> /team 帮我调研 Rust async 生态     # 启动团队
> /team status                       # 查看当前状态
> /team log                          # 查看详细事件日志
> /team log 50                       # 查看最近 50 条日志
> /team 补充：重点关注 tokio 生态    # 追加指令（自动拆解为增量任务）
> /team approve t3                   # 审批任务
> /team reject t3 需要更多细节       # 拒绝任务
> /team manual t3 请增加性能对比     # 要求修改
> /team stop                         # 停止团队（CLI 会输出最终看板快照）
```

CLI 模式下，团队看板会嵌入到 prompt 中实时刷新，支持 `Shift+↑↓` 导航成员、`Enter` 查看详情、`Esc` 返回。

### Telegram / 其他渠道

```
/team 写一份技术方案                  # 启动
/team status                         # 状态
# （worker 完成需要审批的任务时，bot 会主动推送审批提示）
批准 t1                              # 自然语言审批
拒绝 t2 缺少测试计划                 # 自然语言拒绝
/team stop                           # 停止
```

### 通过 LLM Tool 调用（TeamTool）

主 agent 也可以通过 `team` tool 自主创建和管理团队：

```json
{"action": "create", "team_id": "research", "members": [...], "tasks": [...], "mission": "..."}
{"action": "board"}
{"action": "approve", "task_id": "t1"}
{"action": "message", "to": "researcher", "content": "请优先完成 t2"}
{"action": "shutdown"}
```

## 测试覆盖

测试文件位于 `tests/` 目录：

| 文件 | 覆盖范围 |
|------|----------|
| `test_team_mode.py` | TeamManager 核心逻辑：计划校验（重复成员/空任务/循环依赖）、fallback 计划、会话隔离、生命周期（start → route → stop with snapshot）、自然语言审批（approve / reject / manual change） |
| `test_team_routing.py` | AgentLoop 层的命令路由：`/team status` / `/team log` / `/team <goal>` / `/teams` 别名 / `/team approve` / `/team reject` / `/team manual` / `/team stop`（CLI 快照）/ `/btw` 子任务、Telegram 自然语言审批拦截、team mode 下普通消息被阻断 |
| `test_cli_input.py` | CLI 团队视图：`_sync_team_view` / `_prompt_message` 的看板渲染和 suppress 逻辑 |
