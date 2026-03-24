---
name: feishu-attendance
description: 飞书考勤 — 查询员工打卡记录。当用户提及考勤、打卡、出勤、迟到、早退、工时统计时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书考勤 (Attendance)

飞书考勤 API，查询员工打卡记录。

## 使用流程

1. 先用通讯录接口 `get_user` 获取 employee_id
2. 再用本脚本查询打卡记录

## API 函数

### get_attendance

查询打卡结果。

```
python3 scripts/feishu_attendance.py query --user-ids EID001,EID002 --date-from 20260301 --date-to 20260312
```

- `--user-ids`: employee_id 逗号分隔，最多 50 个
- `--date-from` / `--date-to`: yyyyMMdd 格式整数

返回: user_task_results -> [{employee_name, day, records: [{check_in_result, check_out_result, ...}]}]

## 打卡状态码

| 值 | 含义 |
|----|------|
| `Normal` | 正常 |
| `Late` | 迟到 |
| `Early` | 早退 |
| `Lack` | 缺卡 |
| `Todo` | 未打卡 |
| `NoNeedCheck` | 无需打卡 |

## 日期格式

考勤 API 的日期格式是 `yyyyMMdd` **整数**（不是字符串，不是时间戳）：

- 正确: `20260301`
- 错误: `"2026-03-01"` 或 `1739059200`

## 常见错误

| 错误 | 正确做法 |
|------|----------|
| 用 open_id 调考勤 API | 先通过通讯录获取 employee_id |
| 日期格式传字符串或时间戳 | 必须是 yyyyMMdd 整数如 `20260209` |
| 一次查超过 50 人 | `user_ids` 最多 50 个，需分批 |
| 未申请 `contact:user.employee_id:readonly` | open_id 转 employee_id 必需此权限 |

## 所需权限

- `contact:user.employee_id:readonly` — 获取 employee_id
- `attendance:task` — 查询考勤打卡

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。
