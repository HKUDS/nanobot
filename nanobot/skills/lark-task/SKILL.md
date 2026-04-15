---
name: lark-task
version: 1.0.0
description: "飞书任务：管理任务和清单。创建待办任务、查看和更新任务状态、拆分子任务、组织任务清单、分配协作成员。当用户需要创建待办事项、查看任务列表、跟踪任务进度、管理项目清单或给他人分配任务时使用。"
metadata:
  requires:
    bins: ["lark-cli"]
  cliHelp: "lark-cli task --help"
---

# task (v2)

**CRITICAL — 开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)，其中包含认证、权限处理**

> **搜索技巧**：如果用户的查询只指定了任务名称（例如“完成任务龙虾一号”），请直接使用 `+get-my-tasks --query "龙虾一号"` 命令搜索（不要带 `--complete` 参数，这样可以同时搜索未完成和已完成的任务）。
> **用户身份识别**：在用户身份（user identity）场景下，如果用户提到了“我”（例如“分配给我”、“由我创建”），请默认获取当前登录用户的 `open_id` 作为对应的参数值。
> **术语理解**：如果用户提到 “todo”（待办），应当思考其是否是指“task”（任务），并优先尝试使用本 Skill 提供的命令来处理。
> **友好输出**：在输出任务（或清单）的执行结果给用户时，建议同时提取并输出命令返回结果中的 `url` 字段（任务链接），以便用户可以直接点击跳转查看详情。

> **创建/更新注意**：
> 1. 只有在设置了 `due`（截止时间）的情况下，才能设置 `repeat_rule`（重复规则）和 `reminder`（提醒时间）。
> 2. 若同时设置了 `start`（开始时间）和 `due`（截止时间），开始时间必须小于或等于截止时间。
> 3. 使用 tenant_access_token（应用身份）时，无法跨租户添加任务成员。

> **查询注意**：
> 1. 在输出任务详情时，如果需要渲染负责人、创建人等人员字段，除了展示 `id` (例如 open_id) 外，还必须通过其他方式（例如调用通讯录技能）尝试获取并展示这个人的真实名字，以便用户更容易识别。
> 2. 在输出任务详情时，如果需要渲染创建时间、截止时间等字段，需要使用本地时区来渲染（格式为2006-01-02 15:04:05）。

> **Task GUID 定义**：
> Task OpenAPI 中用于更新/操作任务的 `guid` 是任务的全局唯一标识（GUID），不是客户端展示的任务编号（例如 `t104121` / `suite_entity_num`）。
> 对于 Feishu 的任务 applink（例如 `.../client/todo/task?guid=...`），必须使用 URL query 里的 `guid` 参数作为 task guid。

## Shortcuts

- [`+create`](./references/lark-task-create.md) — Create a task
- [`+update`](./references/lark-task-update.md) — Update a task
- [`+comment`](./references/lark-task-comment.md) — Add a comment to a task
- [`+complete`](./references/lark-task-complete.md) — Complete a task
- [`+reopen`](./references/lark-task-reopen.md) — Reopen a task
- [`+assign`](./references/lark-task-assign.md) — Assign or remove members from a task
- [`+followers`](./references/lark-task-followers.md) — Manage task followers
- [`+reminder`](./references/lark-task-reminder.md) — Manage task reminders
- [`+get-my-tasks`](./references/lark-task-get-my-tasks.md) — List tasks assigned to me
- [`+tasklist-create`](./references/lark-task-tasklist-create.md) — Create a tasklist and batch add tasks
- [`+tasklist-task-add`](./references/lark-task-tasklist-task-add.md) — Add existing tasks to a tasklist
- [`+tasklist-members`](./references/lark-task-tasklist-members.md) — Manage tasklist members

## API Resources

```bash
lark-cli schema task.<resource>.<method>   # 调用 API 前必须先查看参数结构
lark-cli task <resource> <method> [flags] # 调用 API
```

> **重要**：使用原生 API 时，必须先运行 `schema` 查看 `--data` / `--params` 参数结构，不要猜测字段格式。

### tasks

  - `create` — 创建任务
  - `delete` — 删除任务
  - `get` — 获取任务详情
  - `list` — 列取任务列表
  - `patch` — 更新任务

### tasklists

  - `add_members` — 添加清单成员
  - `create` — 创建清单
  - `delete` — 删除清单
  - `get` — 获取清单详情
  - `list` — 获取清单列表
  - `patch` — 更新清单
  - `remove_members` — 移除清单成员
  - `tasks` — 获取清单任务列表

### subtasks

  - `create` — 创建子任务
  - `list` — 获取任务的子任务列表

### members

  - `add` — 添加任务成员
  - `remove` — 移除任务成员

## 权限表

| 方法 | 所需 scope |
|------|-----------|
| `tasks.create` | `task:task:write` |
| `tasks.delete` | `task:task:write` |
| `tasks.get` | `task:task:read` |
| `tasks.list` | `task:task:read` |
| `tasks.patch` | `task:task:write` |
| `tasklists.add_members` | `task:tasklist:write` |
| `tasklists.create` | `task:tasklist:write` |
| `tasklists.delete` | `task:tasklist:write` |
| `tasklists.get` | `task:tasklist:read` |
| `tasklists.list` | `task:tasklist:read` |
| `tasklists.patch` | `task:tasklist:write` |
| `tasklists.remove_members` | `task:tasklist:write` |
| `tasklists.tasks` | `task:tasklist:read` |
| `subtasks.create` | `task:task:write` |
| `subtasks.list` | `task:task:read` |
| `members.add` | `task:task:write` |
| `members.remove` | `task:task:write` |
