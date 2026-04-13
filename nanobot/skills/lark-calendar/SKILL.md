---
name: lark-calendar
version: 1.0.0
description: "飞书日历（calendar）：提供日历与日程（会议）的全面管理能力。核心场景包括：查看/搜索日程、创建/更新日程、管理参会人、查询忙闲状态及推荐空闲时段、查询/搜索与预定会议室。注意：涉及【预约日程/会议】或【查询/预定会议室】时，必须先读取 references/lark-calendar-schedule-meeting.md 工作流！高频操作请优先使用 Shortcuts：+agenda（快速概览今日/近期行程）、+create（创建日程并按需邀请参会人及预定会议室）、+freebusy（查询用户主日历的忙闲信息和rsvp的状态）、+rsvp（回复日程邀请）"
metadata:
  requires:
    bins: ["lark-cli"]
  cliHelp: "lark-cli calendar --help"
---

# calendar (v4)

**CRITICAL — 开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)，其中包含认证、权限处理**
**CRITICAL — 所有的 Shortcuts 在执行之前，务必先使用 Read 工具读取其对应的说明文档，禁止直接盲目调用命令。**
**CRITICAL — 凡涉及【预约日程/会议】或【查询/搜索会议室】，第一步 MUST 强制使用 Read 工具读取 [`references/lark-calendar-schedule-meeting.md`](references/lark-calendar-schedule-meeting.md)。禁止跳过此步直接调用 API 或 Shortcut！**
**CRITICAL — 术语约束：用户日常表达中常说的“帮我约个日历”、“查一下今天的日历”等，其实际意图通常是针对 日程（Event） 的创建或查询，而非操作 日历（Calendar） 容器本身。请自动将口语化的“日历”意图映射为“日程”操作（如 `+create`, `+agenda`）。**


**时间与日期推断规范：**
为确保准确性，在涉及时间推断时，请严格遵循以下规则：
- **星期的定义**：周一是一周的第一天，周日是一周的最后一天。计算`下周一`等相对日期时，务必基于当前真实日期和星期基准进行推算，避免算错日期。
- **一天的范围**：当用户提到`明天`、`今天`等泛指某一天时，时间范围应默认覆盖整天时间范围。**切勿**自行缩减查询范围，以免遗漏晚上的时间安排。
- **历史时间约束**：不能预约已经完全过去的时间。唯一的例外情况是“跨越当前时间”的日程，即日程的开始时间在过去，但结束时间在未来。

## 核心场景

### 1. 预约日程/会议、查询/搜索可用会议室
**BLOCKING REQUIREMENT (阻塞性要求): 只要用户的意图包含“预约日程/会议”或“查询/搜索可用会议室”，你必须立即停止其他思考，优先使用 Read 工具完整读取 [`references/lark-calendar-schedule-meeting.md`](references/lark-calendar-schedule-meeting.md)！未读取该文件前，绝对禁止执行任何日程创建或会议室查询操作。**
**CRITICAL: 必须严格按照上述文档中定义的工作流（Workflow）执行后续操作。处理该场景时，默认做“智能助理”，不要做“表单填写机”。能补全的默认值先补全，只有在时间冲突、结果无法唯一确定、时间语义存在歧义时才主动追问。**
**CRITICAL: 执行顺序必须固定为：先补默认值，再判断时间是否明确，再进入“明确时间”或“模糊时间/无时间信息”分支。不要跳步。**
**CRITICAL: 明确时间且需要会议室时，先 `+room-find`，再 `+freebusy`；模糊时间或无时间信息时，先 `+suggestion`，如需会议室再批量 `+room-find`。**
**CRITICAL: 当用户说“查会议室”“找会议室”“搜可用会议室”或“推荐常用会议室”时，默认是查会议室可用性，不是查会议室资源名录，更严禁拉取历史日程做统计分析。完整规则以 [lark-calendar-schedule-meeting.md](references/lark-calendar-schedule-meeting.md) 为准。**
**BLOCKING REQUIREMENT: 即使用户的核心诉求是“查会议室”，只要【没有提供明确的起止时间】，绝对禁止直接调用 `+room-find`！必须先进入【无时间/模糊时间】分支，调用 `+suggestion` 拿到候选时间块后，再将时间块传给 `+room-find`。**
**BLOCKING REQUIREMENT: 只要面临时间方案或会议室方案的选择（如模糊时间、无时间或需要会议室），在调用 `+create` 创建日程之前，必须先向用户展示候选方案并等待用户明确确认。绝对禁止擅自替用户做决定。**

## 核心概念

- **日历（Calendar）**：日程的容器。每个用户有一个主日历（primary calendar），也可以创建或订阅共享日历。
- **日程（Event）**：日历中的单个日程，包含起止时间、地点、标题、参与人等属性。支持单次日程和重复日程，遵循RFC5545 iCalendar国际标准。
- ***全天日程（All-day Event）***: 只按日期占用、没有具体起止时刻的日程，结束日期是包含在日程时间内的。
- **日程实例（Instance）**：日程的具体时间实例，本质是对日程的展开。普通日程和例外日程对应1个Instance，重复性日程对应N个Instance。在按时间段查询时，可通过实例视图将重复日程展开为独立的实例返回，以便在时间线上准确展示和管理。
- **重复规则（Rrule/Recurrence Rule）**：定义重复性日程的重复规则，比如`FREQ=DAILY;UNTIL=20230307T155959Z;INTERVAL=14`表示每14天重复一次。
- **例外日程（Exception）**：重复性日程中与原重复性日程不一致的日程。
- **参会人（Attendee）**：日程的参与者，可以是用户、群、会议室资源、外部邮箱地址等。每个参与人有独立的RSVP状态。
- **响应状态（RSVP）**：参与人对日程邀请的回复状态（接受/拒绝/待定）。
- **忙闲时间（FreeBusy）**：查询用户在指定时间段的忙闲状态，用于会议时间协调。
- **会议室（Room）**：“room”不是“房间”，是“会议室”。请在理解和处理意图时将“room”和“房间”准确映射为“会议室”及其相关操作。
- **时间块（Time Slot / Time Block）**：指一个**具体且确定**的连续时间段（如 `14:00~15:00`）。在文档中，它与泛指的“时间范围/区间”（如“今天下午”、“下周”）有严格区别。在调用预定、查询可用会议室等确切操作时，必须基于确定的“时间块”而非模糊的“时间范围”。

## 资源关系

```
Calendar (日历)
└── Event (日程)
    ├── Attendee (参会人)
    └── Reminder (提醒)
```

## Shortcuts（推荐优先使用）

Shortcut 是对常用操作的高级封装（`lark-cli calendar +<verb> [flags]`）。有 Shortcut 的操作优先使用。

| Shortcut | 说明 |
|----------|------|
| [`+agenda`](references/lark-calendar-agenda.md) | 查看日程安排（默认今天） |
| [`+create`](references/lark-calendar-create.md) | 创建日程并邀请参会人（ISO 8601 时间） |
| [`+freebusy`](references/lark-calendar-freebusy.md) | 查询用户主日历的忙闲信息和rsvp的状态 |
| [`+room-find`](references/lark-calendar-room-find.md) | 针对一个或多个**明确的**时间块查找可用会议室（**无明确时间时禁止直接调用，需先走 +suggestion**） |
| [`+rsvp`](references/lark-calendar-rsvp.md) | 回复日程（接受/拒绝/待定） |
| [`+suggestion`](references/lark-calendar-suggestion.md) | 根据非明确时间或一段时间范围，推荐多个可用时间块方案 |

## 会议室相关规则

- **会议室是日程的一种参与人（resource attendee），不能脱离日程单独存在或单独预定。**
- **凡是用户意图是“预定/查询/搜索可用会议室”时，都必须进入 `references/lark-calendar-schedule-meeting.md` 工作流处理。**
- `+room-find` 的时间输入必须是**确定时间块**，不能是时间区间搜索。
- **强制约束：如果用户仅要求“查询会议室”但未提供明确时间，必须先调用 `+suggestion` 获取可用时间块，然后再将时间块交给 `+room-find` 批量查询。严禁直接猜测时间并盲目调用 `+room-find`。**

## API Resources

```bash
lark-cli schema calendar.<resource>.<method>   # 调用 API 前必须先查看参数结构
lark-cli calendar <resource> <method> [flags] # 调用 API
```

> **重要**：使用原生 API 时，必须先运行 `schema` 查看 `--data` / `--params` 参数结构，不要猜测字段格式。

### calendars

  - `create` — 创建共享日历
  - `delete` — 删除共享日历
  - `get` — 查询日历信息
  - `list` — 查询日历列表
  - `patch` — 更新日历信息
  - `primary` — 查询用户主日历
  - `search` — 搜索日历

### event.attendees

  - `batch_delete` — 删除日程参与人
  - `create` — 添加日程参与人
  - `list` — 获取日程参与人列表

### events

  - `create` — 创建日程
  - `delete` — 删除日程
  - `get` — 获取日程
  - `instance_view` — 查询日程视图
  - `patch` — 更新日程
  - `search` — 搜索日程

### freebusys

  - `list` — 查询主日历日程忙闲信息

## 权限表

| 方法 | 所需 scope |
|------|-----------|
| `calendars.create` | `calendar:calendar:create` |
| `calendars.delete` | `calendar:calendar:delete` |
| `calendars.get` | `calendar:calendar:read` |
| `calendars.list` | `calendar:calendar:read` |
| `calendars.patch` | `calendar:calendar:update` |
| `calendars.primary` | `calendar:calendar:read` |
| `calendars.search` | `calendar:calendar:read` |
| `event.attendees.batch_delete` | `calendar:calendar.event:update` |
| `event.attendees.create` | `calendar:calendar.event:update` |
| `event.attendees.list` | `calendar:calendar.event:read` |
| `events.create` | `calendar:calendar.event:create` |
| `events.delete` | `calendar:calendar.event:delete` |
| `events.get` | `calendar:calendar.event:read` |
| `events.instance_view` | `calendar:calendar.event:read` |
| `events.patch` | `calendar:calendar.event:update` |
| `events.search` | `calendar:calendar.event:read` |
| `freebusys.list` | `calendar:calendar.free_busy:read` |

**注意（强制性）：**
- 涉及日期（时间）字符串与时间戳的相互转换时，务必调用系统命令或脚本代码等外部工具进行处理，以确保转换的绝对准确。违者将导致严重的逻辑错误！
