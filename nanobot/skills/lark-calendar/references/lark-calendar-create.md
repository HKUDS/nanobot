
# calendar +create

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

创建日程并按需邀请参会人。

需要的scopes: ["calendar:calendar.event:create","calendar:calendar.event:update"]

## 推荐命令

```bash
# 创建日程 + 邀请参会人（ISO 8601 时间）
lark-cli calendar +create \
  --summary "产品评审" \
  --start "2026-03-12T14:00+08:00" \
  --end "2026-03-12T15:00+08:00" \
  --attendee-ids ou_aaa,ou_bbb

# 无参会人
lark-cli calendar +create \
  --summary "午餐" \
  --start "2026-03-12T12:00+08:00" \
  --end "2026-03-12T13:00+08:00"

# 指定日历
lark-cli calendar +create --summary "..." --start "..." --end "..." \
  --calendar-id cal_xxx
```

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--summary <text>` | 否 | 日程标题。注意：标题中不应该出现时间、地点、人物信息 |
| `--start <time>` | 是 | 开始时间（ISO 8601，如 `2026-03-12T14:00+08:00`） |
| `--end <time>` | 是 | 结束时间（ISO 8601） |
| `--description <text>` | 否 | 日程详细描述。提供会议议程、活动内容、注意事项或链接等。与 summary 配合使用，仅关注当前日程信息 |
| `--attendee-ids <id_list>` | 否 | 参与人 ID 列表（逗号分隔）。支持用户（`ou_`）、群组（`oc_`）和会议室（`omm_`）。AI 提取时请务必保留对应前缀 |
| `--calendar-id <id>` | 否 | 日历 ID（省略则使用主日历） |
| `--rrule <rrule>` | 否 | 重复日程的重复性规则，规则设置方式参考rfc5545。**【⚠️注意：系统绝对不支持 COUNT，如需限制重复次数，必须转为 UNTIL】**。示例值："FREQ=DAILY;INTERVAL=1" |
| `--dry-run` | 否 | 预览 API 调用，不执行 |

> **⚠️ `rrule` 规则限制：飞书日历系统不支持 `COUNT` 参数。遇到限制重复次数的需求，必须根据开始时间和频率自行推算并转换成 `UNTIL=<具体日期>` 格式。**
> 自动设置 `attendee_ability: "can_modify_event"`，参会人可查看彼此并编辑日程。
> 自动设置 `free_busy_status: "busy"`，默认日程忙闲状态为忙碌。
> 自动设置 `reminders: [{"minutes": 5}]`，默认日程开始前 5 分钟提醒。
> 自动设置 `vchat: {"vc_type": "vc"}`，默认日程包含飞书视频会议。如需其他视频会议类型或不含视频会议，请使用完整 API 命令。
> 失败保护：若添加参会人失败（如 open_id 错误），CLI 会自动删除刚创建的空日程（回滚，不通知参会人）。

## 高级用法（完整 API 命令）

如需配置 `location`（地理位置，不含会议室位置）、`visibility`（日程公开范围）、自定义 `reminders`（提醒设置）、自定义 `attendee_ability`（参与人权限）、自定义 `free_busy_status`（日程忙闲状态）、参与人可选参加状态或全天日程等高级参数，请使用完整的 API 命令：
**注意**：
- 全天日程的开始日期和结束日期必须分别是日程开始的第一天和结束的最后一天。如果只有一天的话，开始日期和结束日期是相同。

```bash
# 第一步：创建日程（含高级参数）
## 查看完整参数定义
lark-cli schema calendar.events.create
## 创建日程
lark-cli calendar events create --calendar-id primary --data '{
  "summary": "产品评审",
  "description": "本周分享主题：CLI 架构设计",
  "start_time": { "timestamp": "1741586400" },
  "end_time": { "timestamp": "1741593600" },
  "location": { "name": "5F-大会议室" },
  "attendee_ability": "can_modify_event",
  "reminders": [{ "minutes": 15 }]
}'

# 第二步：添加参会人（使用第一步返回的 calendar_id 和 event_id）
## 查看完整参数定义
lark-cli schema calendar.event.attendees.create
## 添加参会人
lark-cli calendar event.attendees create \
  --calendar-id <CALENDAR_ID> --event-id <EVENT_ID> \
  --data '{"attendees": [{"type": "user", "user_id": "ou_xxx"}]}'

# 可选第三步（推荐）：若第二步失败，回滚删除空日程
## 查看完整参数定义
lark-cli schema calendar.events.delete
## 删除空日程
lark-cli calendar events delete \
  --calendar-id <CALENDAR_ID> --event-id <EVENT_ID> \
  --params '{"need_notification":false}'

```

> 完整 API 命令的时间参数是 **Unix 秒字符串**（非 ISO 8601）。
> 当你手动拆成两步执行时，建议保留“失败后回滚删除”的第三步，避免遗留空日程。

## 参会人类型

| `type` | `user_id` 格式 | 说明 |
|--------|---------------|------|
| `user` | `ou_xxx`（open_id） | 飞书用户 |
| `group` | `oc_xxx` | 飞书群组 |
| `resource` | `omm_xxx` | 会议室 |
| `third_party` | 邮箱地址 | 外部参会人 |

> [!CAUTION]
> 这是**写入操作** -- 执行前必须确认用户意图。

## 参考

- [lark-calendar](../SKILL.md) -- 日历全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
- [lark-calendar-suggestion](lark-calendar-suggestion.md) -- 根据非明确时间或一段时间范围，推荐多个可用时间块方案
