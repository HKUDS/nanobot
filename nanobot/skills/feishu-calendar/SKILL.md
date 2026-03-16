---
name: feishu-calendar
description: 飞书日历与日程 — 日历列表、日程 CRUD、忙闲查询、会议室。当用户提及日历、日程、会议、约会、忙闲、会议室预订、schedule、calendar时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书日历与日程 (Calendar)

飞书日历 API，管理日历、日程、忙闲查询和会议室。

## 使用流程

1. 根据下方 API 函数说明确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### calendar_list

获取日历列表。

```
python3 scripts/feishu_calendar.py list
```

### calendar_list_events

获取日程列表（"primary" 表示主日历）。

```
python3 scripts/feishu_calendar.py events --calendar-id primary --limit 50
python3 scripts/feishu_calendar.py events --calendar-id primary --start-time "2026-03-12T00:00:00+08:00" --end-time "2026-03-13T00:00:00+08:00"
```

### calendar_create_event

创建日程。

```
python3 scripts/feishu_calendar.py event-create --calendar-id primary --summary "团队周会" --start-time "2026-03-15T14:00:00+08:00" --end-time "2026-03-15T15:00:00+08:00" --description "讨论进展"
```

### calendar_update_event

更新日程。

```
python3 scripts/feishu_calendar.py event-update --calendar-id primary --event-id EVENT_ID --summary "新标题" --start-time "2026-03-15T15:00:00+08:00" --end-time "2026-03-15T16:00:00+08:00"
```

### calendar_delete_event

删除日程。

```
python3 scripts/feishu_calendar.py event-delete --calendar-id primary --event-id EVENT_ID
```

### calendar_freebusy

查询忙闲信息。

```
python3 scripts/feishu_calendar.py freebusy --user-id ou_xxx --start-time "1773576000" --end-time "1773662400"
```

### meeting_room_search

搜索会议室。

```
python3 scripts/feishu_calendar.py rooms --query "大会议室" --limit 10
```

### meeting_reserve

预约会议。

```
python3 scripts/feishu_calendar.py reserve --start-time "1773576000" --end-time "1773579600"
python3 scripts/feishu_calendar.py reserve --start-time "1773576000" --end-time "1773579600" --room-id ROOM_ID
```

### 其他 CLI 命令

```
python3 scripts/feishu_calendar.py get --calendar-id primary
python3 scripts/feishu_calendar.py event-get --calendar-id primary --event-id EVENT_ID
```

## 典型工作流

### 预约会议室

1. `meeting_room_search("大会议室")` → 搜索会议室
2. `calendar_freebusy(user_ids, start, end)` → 查询忙闲
3. `calendar_create_event(...)` → 创建日程并添加参与人

## 时间格式

日历 API 使用 RFC3339 格式：`2026-03-12T14:00:00+08:00`

## 常见错误

| 错误 | 正确做法 |
|------|----------|
| 时间传 Unix 时间戳 | 日历 API 需要 RFC3339 字符串 |
| 忘记传 `calendar_id` | 必须传，主日历用 `"primary"` |
| 会议室查询用日历 API | 会议室在 `vc` 域下：`meeting_room_search` |

## 所需权限

- `calendar:calendar` — 日历完整权限
- `calendar:calendar:readonly` — 只读权限
- `vc:room:readonly` — 查询会议室
- `vc:reserve` — 预约会议

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。
