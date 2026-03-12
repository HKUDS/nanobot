# 日历与日程 (Calendar)

飞书日历 API，管理日历、日程、忙闲查询和会议室。

## API 函数

### calendar_list

获取日历列表。

```python
from feishu_api import calendar_list

data = calendar_list(page_size=50)
# data["calendar_list"] -> [{calendar_id, summary, type, role, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py calendar list
```

### calendar_get

获取日历信息。

```python
from feishu_api import calendar_get

data = calendar_get("feishu.cn_xxx")
# data -> {calendar_id, summary, description, permissions, color, ...}
```

### calendar_list_events

获取日程列表。

```python
from feishu_api import calendar_list_events

data = calendar_list_events(
    calendar_id="primary",                           # "primary" 表示主日历
    start_time="2026-03-12T00:00:00+08:00",          # RFC3339（可选）
    end_time="2026-03-13T00:00:00+08:00",
    page_size=50,
)
# data["items"] -> [{event_id, summary, start_time, end_time, attendees, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py calendar events --calendar-id primary --start-time "2026-03-12T00:00:00+08:00"
```

### calendar_get_event

获取日程详情。

```python
from feishu_api import calendar_get_event

data = calendar_get_event("primary", "event_id_xxx")
# data["event"] -> {event_id, summary, description, start_time, end_time, attendees, ...}
```

### calendar_create_event

创建日程。

```python
from feishu_api import calendar_create_event

data = calendar_create_event(
    calendar_id="primary",
    summary="团队周会",
    start_time="2026-03-15T14:00:00+08:00",
    end_time="2026-03-15T15:00:00+08:00",
    description="讨论本周进展",
    attendees=[
        {"type": "user", "user_id": "ou_xxx"},
    ],
)
# data["event"] -> {event_id, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py calendar create-event --summary "周会" \
    --start-time "2026-03-15T14:00:00+08:00" \
    --end-time "2026-03-15T15:00:00+08:00"
```

### calendar_update_event

更新日程。

```python
from feishu_api import calendar_update_event

calendar_update_event("primary", "event_id_xxx", {
    "summary": "更新后的标题",
})
```

### calendar_delete_event

删除日程。

```python
from feishu_api import calendar_delete_event

calendar_delete_event("primary", "event_id_xxx")
```

### calendar_freebusy

查询忙闲信息。

```python
from feishu_api import calendar_freebusy

data = calendar_freebusy(
    user_ids=["ou_xxx"],
    start_time="2026-03-15T00:00:00+08:00",
    end_time="2026-03-16T00:00:00+08:00",
)
# data["freebusy_list"] -> [{start_time, end_time}]
```

### meeting_room_search

搜索会议室。

```python
from feishu_api import meeting_room_search

data = meeting_room_search(query="大会议室")
# data["rooms"] -> [{room_id, name, capacity, ...}]
```

### meeting_reserve

预约会议。

```python
from feishu_api import meeting_reserve

data = meeting_reserve(
    end_time="1710100800",
    meeting_settings={"topic": "项目评审", "meeting_no": ""},
)
```

## 时间格式

日历 API 使用 RFC3339 格式：`2026-03-12T14:00:00+08:00`

## 所需权限

- `calendar:calendar` — 日历完整权限
- `calendar:calendar:readonly` — 只读权限
- `vc:room:readonly` — 查询会议室
- `vc:reserve` — 预约会议
