# 飞书请假审批 API 参考

## 凭据配置

通过环境变量获取（与其他飞书 skill 共用），无需在参数中传入：

```bash
export NANOBOT_CHANNELS__FEISHU__APP_ID=cli_xxx
export NANOBOT_CHANNELS__FEISHU__APP_SECRET=xxx
```

## 参数说明

### 必填参数

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `approval_code` | string | 审批模板码（固定值） | `E565EC28-57C7-461C-B7ED-1E2D838F4878` |
| `user_id` | string | 申请人的 open_id | `ou_xxxxxxxxxxxx` |
| `leave_type` | string | 假期类型名称或 leave_id | `年假` 或 `7138673249737506817` |
| `start_time` | string | 开始时间 (RFC3339) | `2026-03-11T09:00:00+08:00` |
| `end_time` | string | 结束时间 (RFC3339) | `2026-03-11T18:00:00+08:00` |
| `reason` | string | 请假事由 | `出差` |

### 可选参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `unit` | string | `DAY` | 时长单位：`DAY`, `HOUR`, `HALF_DAY` |
| `interval` | string | `1` | 时长计算方式 |

## 假期类型列表

| 假期类型 | leave_id | 单位 | 余额规则 |
|----------|----------|------|----------|
| 年假 | 7138673249737506817 | 半天 | 限额 |
| 事假 | 7138673250187935772 | 小时 | 不限额 |
| 病假 | 7138673250640347138 | 半天 | 不限额 |
| 调休假 | 7138673251139731484 | 小时 | 限额 |
| 婚假 | 7138673251697475612 | 天 | 限额 |
| 产假 | 7138673252143726594 | 天 | 不限额 |
| 陪产假 | 7138673252595236865 | 天 | 限额 |
| 丧假 | 7138673253106663426 | 天 | 不限额 |
| 哺乳假 | 7138673253534695425 | 分钟 | 不限额 |

## Form 字段结构

form 必须是 JSON 字符串数组，通过 `json.dumps()` 序列化后传入：

```python
form_array = [
    {
        "id": "widgetLeaveGroupV2",
        "type": "leaveGroupV2",
        "value": [
            {"id": "widgetLeaveGroupType", "type": "radioV2", "value": leave_id},
            {"id": "widgetLeaveGroupStartTime", "type": "date", "value": start_time},
            {"id": "widgetLeaveGroupEndTime", "type": "date", "value": end_time},
            {"id": "widgetLeaveGroupInterval", "type": "radioV2", "value": "1"},
            {"id": "widgetLeaveGroupReason", "type": "textarea", "value": reason},
            {"id": "widgetLeaveGroupUnit", "type": "radioV2", "value": unit}
        ]
    }
]

payload["form"] = json.dumps(form_array, ensure_ascii=False)
```

## 常见错误码

| 错误码 | 消息 | 解决方案 |
|--------|------|----------|
| 9499 | Invalid parameter type in json: form | form 必须是 JSON 字符串数组 |
| 1390001 | user id not found | 检查 open_id 是否正确 |
| 1390001 | start time format is not RFC3339 | 时间格式改为 RFC3339 |
| 1390001 | leave is conflict | 请假时间冲突，调整时间 |
| 99991666 | 权限不足 | 检查应用权限配置 |

## 注意事项

- 应用必须发布到用户所在组织（跨租户无法调用）
- 不同审批模板的 form 结构可能不同，需根据实际模板调整
- 限额假期类型会检查用户余额，不足时创建失败
