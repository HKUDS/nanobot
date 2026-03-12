# 日历与会议室 (Calendar)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中管理日程、预约会议室和查询忙闲状态。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `calendar:calendar` | 读写日历及日程信息 |
| `vc:room:readonly` | 查询/搜索会议室 |
| `contact:user.employee_id:readonly` | 获取用户 ID（可选） |

## 创建日程

```typescript
const res = await client.calendar.calendarEvent.create({
  path: { calendar_id: 'primary' }, // 'primary' 表示主日历
  data: {
    summary: '产品评审会议',
    description: 'Q1 产品路线图评审',
    start_time: {
      timestamp: String(Math.floor(new Date('2026-02-13T14:00:00+08:00').getTime() / 1000)),
    },
    end_time: {
      timestamp: String(Math.floor(new Date('2026-02-13T15:00:00+08:00').getTime() / 1000)),
    },
    attendee_ability: 'can_invite_others',
  },
});
const eventId = res.data?.event?.event_id;
```

## 更新日程

```typescript
await client.calendar.calendarEvent.patch({
  path: { calendar_id: 'primary', event_id: eventId },
  data: {
    summary: '产品评审会议（更新）',
    end_time: {
      timestamp: String(Math.floor(new Date('2026-02-13T15:30:00+08:00').getTime() / 1000)),
    },
  },
});
```

## 获取日程详情

```typescript
const detail = await client.calendar.calendarEvent.get({
  path: { calendar_id: 'primary', event_id: eventId },
});
```

## 获取日程列表

```typescript
const events = await client.calendar.calendarEvent.list({
  path: { calendar_id: 'primary' },
  params: {
    start_time: String(Math.floor(new Date('2026-02-13T00:00:00+08:00').getTime() / 1000)),
    end_time: String(Math.floor(new Date('2026-02-14T00:00:00+08:00').getTime() / 1000)),
    page_size: 50,
  },
});
```

## 删除日程

```typescript
await client.calendar.calendarEvent.delete({
  path: { calendar_id: 'primary', event_id: eventId },
});
```

## 添加参与人

```typescript
await client.calendar.calendarEventAttendee.create({
  path: { calendar_id: 'primary', event_id: eventId },
  data: {
    attendees: [
      { type: 'user', user_id: 'ou_xxx1' },
      { type: 'user', user_id: 'ou_xxx2' },
      { type: 'resource', room_id: 'omm_xxx' }, // 预约会议室
    ],
    need_notification: true,
  },
  params: { user_id_type: 'open_id' },
});
```

> **会议室预约是异步的**：添加会议室参与人成功不代表预约成功。需后续通过日程参与人列表中会议室的 `rsvp_status` 确认预约状态。

## 获取参与人列表

```typescript
const attendees = await client.calendar.calendarEventAttendee.list({
  path: { calendar_id: 'primary', event_id: eventId },
  params: { user_id_type: 'open_id', page_size: 50 },
});
```

## 删除参与人

```typescript
await client.calendar.calendarEventAttendee.batchDelete({
  path: { calendar_id: 'primary', event_id: eventId },
  data: {
    attendee_ids: ['user_xxx'],
  },
});
```

## 忙闲查询

```typescript
// 注意：方法名是 batch，不是 list
const freebusy = await client.calendar.freebusy.batch({
  data: {
    time_min: String(Math.floor(new Date('2026-02-13T09:00:00+08:00').getTime() / 1000)),
    time_max: String(Math.floor(new Date('2026-02-13T18:00:00+08:00').getTime() / 1000)),
    user_id: { user_id: 'ou_xxx', id_type: 'open_id' },
  },
});
// 返回 freebusy.data?.freebusy_list — 忙碌时间段数组
```

查询会议室忙闲时，使用 `room_id` 代替 `user_id`：

```typescript
const roomFreebusy = await client.calendar.freebusy.batch({
  data: {
    time_min: '...',
    time_max: '...',
    room_id: 'omm_xxx',
  },
});
```

## 会议室列表

```typescript
const rooms = await client.vc.room.list({
  params: {
    page_size: 20,
    // room_level_id: 'xxx', // 可选：指定层级
  },
});
```

## 搜索会议室

```typescript
const searchResult = await client.vc.room.search({
  data: {
    query: '大会议室',
  },
  params: { page_size: 10 },
});
```

## 典型工作流

### 预约会议室

1. **搜索会议室** → `client.vc.room.search({ data: { query: '关键词' } })`
2. **查询忙闲** → `client.calendar.freebusy.batch({ data: { room_id, time_min, time_max } })`
3. **创建日程** → `client.calendar.calendarEvent.create({ ... })`
4. **添加会议室** → `client.calendar.calendarEventAttendee.create({ data: { attendees: [{ type: 'resource', room_id }] } })`
5. **确认状态** → 查看参与人列表中会议室的 `rsvp_status`

### 安排团队会议

1. 分别查询每位成员忙闲 → `client.calendar.freebusy.batch()`
2. 找到共同空闲时间段
3. 搜索可用会议室
4. 创建日程并添加参与人和会议室

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 时间传 ISO 字符串 | SDK 需要 Unix 秒时间戳字符串 |
| 忙闲查询用 `freebusy.list` | 正确方法名是 `freebusy.batch` |
| 会议室查询用 `calendar.*` | 会议室在 `vc.room.*` 域下 |
| 以为添加会议室立即生效 | 会议室预约是异步的，需查询 `rsvp_status` |
| 忘记传 `calendar_id` | path 中必须传 `calendar_id`，主日历用 `'primary'` |
