---
name: wecom-attendance
description: 企业微信考勤打卡 — 查询打卡记录、打卡规则、排班信息。当用户提及考勤、打卡、出勤、迟到、早退、工时统计时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 企业微信考勤打卡 (Attendance)

企业微信打卡 API，查询打卡记录、规则、排班信息。

## 使用流程

1. 确认需要查询的用户和时间范围
2. 调用 API 获取打卡数据
3. 分析出勤情况

## API 函数

### get_data

获取打卡记录。

```
python3 scripts/wecom_attendance.py data --useridlist smile,zhangsan --start-time 1710720000 --end-time 1710806400
```

### get_option

获取打卡规则。

```
python3 scripts/wecom_attendance.py option --datetime 1710720000
```

### get_group

获取打卡组列表。

```
python3 scripts/wecom_attendance.py group
```

### add_user

添加打卡人员。

```
python3 scripts/wecom_attendance.py add-user --groupid 1 --useridlist smile,zhangsan
```

## 时间戳转换

Unix 时间戳（秒）：
- 2026-03-18 00:00:00 = `1710691200`
- 2026-03-18 23:59:59 = `1710777599`

Python 生成：
```python
import time
int(time.time())  # 当前时间戳
```

## 打卡记录返回

```json
{
  "errcode": 0,
  "errmsg": "ok",
  "checkin_data": [
    {
      "userid": "smile",
      "checkin_type": 1,
      "checkin_time": 1710720000,
      "location_title": "公司",
      "location_addr": "xxx",
      "notes": "",
      "wifiname": "Office-WiFi",
      "checkin_option": "正常"
    }
  ]
}
```

## 常见错误

| 错误码 | 说明 | 解决方法 |
|--------|------|----------|
| 48002 | API 未授权 | 管理后台启用打卡 API |
| 48003 | 无权限 | 检查应用可见范围 |

## 配置说明

自动读取 `~/.hiperone/config.json` 中的企业微信配置。

## 官方文档

- [打卡 API](https://developer.work.weixin.qq.com/document/path/90263)
- [获取打卡记录](https://developer.work.weixin.qq.com/document/path/90262)
