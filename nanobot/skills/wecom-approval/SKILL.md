---
name: wecom-approval
description: 企业微信审批管理 — 提交/查询/撤回审批申请。当用户提及审批、请假、加班、调休、报销、approval 时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 企业微信审批 (Approval)

企业微信审批 API，支持提交、查询、撤回审批申请。

## 使用流程

1. 获取审批模板 ID（管理后台查看）
2. 根据模板构造申请数据
3. 调用 API 提交审批

## API 函数

### get_template

获取审批模板详情。

```
python3 scripts/wecom_approval.py template --template-id TEMPLATE_ID
```

### create

提交审批申请。

```
python3 scripts/wecom_approval.py create --creator zhangsan --template-id xxx --apply-data '{"contents": [...]}'
```

### get

获取审批详情。

```
python3 scripts/wecom_approval.py get --sp-no SP202603180001
```

### list

批量获取审批列表。

```
python3 scripts/wecom_approval.py list --start-time 1710720000 --end-time 1710806400 --limit 100
```

### withdraw

撤回审批申请。

```
python3 scripts/wecom_approval.py withdraw --sp-no SP202603180001
```

## 请假申请示例

```json
{
  "contents": [
    {
      "control": "Content",
      "id": "control-1",
      "value": {
        "text": "事假申请"
      }
    },
    {
      "control": "Date",
      "id": "control-2",
      "value": {
        "new_begin": "2026-03-20 09:00",
        "new_end": "2026-03-20 18:00"
      }
    },
    {
      "control": "Textarea",
      "id": "control-3",
      "value": {
        "text": "个人事务处理"
      }
    }
  ]
}
```

## 常见错误

| 错误码 | 说明 | 解决方法 |
|--------|------|----------|
| 301025 | 参数错误 | 检查模板 ID 和 apply_data 格式 |
| 301026 | 模板不存在 | 确认模板 ID 正确 |
| 301027 | 无权限 | 检查应用审批权限 |

## 配置说明

自动读取 `~/.hiperone/config.json` 中的企业微信配置。

## 官方文档

- [审批 API](https://developer.work.weixin.qq.com/document/path/91853)
- [提交审批申请](https://developer.work.weixin.qq.com/document/path/91854)
