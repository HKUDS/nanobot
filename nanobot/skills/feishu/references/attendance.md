# 考勤 (Attendance)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中查询飞书考勤数据。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `attendance:task:readonly` | 导出打卡数据 |
| `attendance:rule:readonly` | 导出打卡管理规则（查询考勤组时需要） |
| `contact:user.employee_id:readonly` | 获取用户 employee_id（open_id 转换必需） |

> **重要**：考勤 API 使用 `employee_id` 而非 `open_id`。需先通过通讯录 API 将 `open_id` 转换为 `employee_id`。

## open_id 转 employee_id

```typescript
// 通过通讯录 API 获取用户的 employee_id
const user = await client.contact.user.get({
  path: { user_id: 'ou_xxx' },
  params: { user_id_type: 'open_id' },
});
const employeeId = user.data?.user?.employee_id; // 如 'abd754f7'
```

## 查询打卡结果

```typescript
const tasks = await client.attendance.userTask.query({
  params: { employee_type: 'employee_id' },
  data: {
    user_ids: ['abd754f7'], // employee_id 列表，最多 50 个
    check_date_from: 20260209, // yyyyMMdd 格式整数
    check_date_to: 20260213,
  },
});

// 遍历结果
for (const task of tasks.data?.user_task_results || []) {
  console.log(`${task.employee_name} - ${task.day}`);
  for (const record of task.records || []) {
    console.log(`  上班: ${record.check_in_result}, 下班: ${record.check_out_result}`);
  }
}
```

### 日期格式

考勤 API 的日期格式是 `yyyyMMdd` **整数**（不是字符串，不是时间戳）：

```typescript
// 正确
check_date_from: 20260209

// 错误
check_date_from: '2026-02-09'     // 不是字符串
check_date_from: 1739059200        // 不是 Unix 时间戳
check_date_from: '20260209'        // 不是字符串
```

### 打卡状态码

| 值 | 含义 |
|----|------|
| `Normal` | 正常 |
| `Late` | 迟到 |
| `Early` | 早退 |
| `Lack` | 缺卡 |
| `Todo` | 未打卡 |
| `NoNeedCheck` | 无需打卡 |

## 查询补卡记录

```typescript
const remedys = await client.attendance.userTaskRemedy.query({
  params: { employee_type: 'employee_id' },
  data: {
    user_ids: ['abd754f7'],
    check_time_from: '1738800000', // Unix 秒时间戳字符串
    check_time_to: '1739404800',
    status: 2, // 0=待审批, 1=未通过, 2=已通过, 3=已取消, 4=已撤回
  },
});
```

### 补卡状态码

| 值 | 含义 |
|----|------|
| 0 | 待审批 |
| 1 | 未通过 |
| 2 | 已通过 |
| 3 | 已取消 |
| 4 | 已撤回 |

## 查询考勤组

```typescript
// group_id 从打卡结果中获取
const group = await client.attendance.group.get({
  path: { group_id: '6737202939523236110' },
  params: { employee_type: 'employee_id' },
});
// group.data — { group_name, time_zone, group_type, locations, ... }
```

### 考勤组类型

| 值 | 含义 |
|----|------|
| 0 | 固定班制 |
| 2 | 排班制 |
| 3 | 自由班制 |

## 列出考勤组

```typescript
const groups = await client.attendance.group.list({
  params: { page_size: 20 },
});
```

## 搜索考勤组

```typescript
const search = await client.attendance.group.search({
  data: { group_name: '产品部' },
});
```

## 典型工作流

### 查看本周考勤

1. **获取 employee_id** → `client.contact.user.get()` 转换 open_id
2. **查询打卡结果** → `client.attendance.userTask.query({ data: { user_ids, check_date_from, check_date_to } })`
3. 汇总每天上下班打卡状态
4. 标记异常（Late/Early/Lack）

### 查看考勤规则

1. **查询打卡结果** → 获取 `group_id`
2. **查询考勤组** → `client.attendance.group.get({ path: { group_id } })`
3. 查看打卡地点、考勤时间、补卡策略等配置

### 批量查询团队考勤

1. 获取部门成员 → `client.contact.user.findByDepartment()`
2. 提取所有成员的 `employee_id`
3. 分批查询（每批最多 50 人）→ `client.attendance.userTask.query()`
4. 汇总统计异常情况

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 用 open_id 调考勤 API | 先转换为 employee_id |
| 日期格式传字符串或时间戳 | 必须是 yyyyMMdd 整数如 `20260209` |
| 补卡查询时间传整数 | 补卡时间是 Unix 秒时间戳**字符串** |
| 一次查超过 50 人 | `user_ids` 最多 50 个，需分批 |
| 未申请 `contact:user.employee_id:readonly` | open_id 转 employee_id 必需此权限 |
