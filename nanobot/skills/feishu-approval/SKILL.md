---
name: feishu-approval
description: 飞书审批 — 审批定义查询、实例管理、请假审批。当用户提及审批、请假、调休、加班申请、审批流程、approval时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书审批 (Approval)

飞书审批 API，管理审批定义、审批实例，以及请假审批便捷函数。

## 使用流程

1. 根据下方 API 函数说明确认所需操作
2. 通过 `exec` 工具调用脚本执行

## 预置常量

默认请假审批编码: `E565EC28-57C7-461C-B7ED-1E2D838F4878`

### 假期类型映射

| 名称 | leave_id |
|------|----------|
| 年假 | 7138673249737506817 |
| 事假 | 7138673250187935772 |
| 病假 | 7138673250640347138 |
| 调休假 | 7138673251139731484 |
| 婚假 | 7138673251697475612 |
| 产假 | 7138673252143726594 |
| 陪产假 | 7138673252595236865 |
| 丧假 | 7138673253106663426 |
| 哺乳假 | 7138673253534695425 |

`create_leave_approval` 的 `leave_type` 参数可直接传中文名称（如 `"年假"`），会自动映射。

## API 函数

### approval_get_definition

获取审批定义详情（含表单结构）。

```
python3 scripts/feishu_approval.py definition --code E565EC28-57C7-461C-B7ED-1E2D838F4878
```

### approval_list_instances

批量获取审批实例 ID。默认查询最近 30 天。

```
python3 scripts/feishu_approval.py list --code E565EC28-... --limit 20
```

### approval_get_instance

获取审批实例详情。

```
python3 scripts/feishu_approval.py get --instance-code xxx
```

### approval_create_instance

创建审批实例。

```
python3 scripts/feishu_approval.py create --code E565EC28-... --user-id ou_xxx --form '[...]'
```

### 其他函数（通过脚本 Python API 调用）

- `approval_cancel_instance(approval_code, instance_code, user_id, reason)` — 撤回审批
- `approval_approve_task(approval_code, instance_code, task_id, user_id, comment)` — 同意
- `approval_reject_task(...)` — 拒绝
- `approval_transfer_task(..., transfer_user_id)` — 转交
- `approval_list_comments(instance_id)` — 获取评论
- `create_leave_approval(approval_code, user_id, leave_type, start_time, end_time, reason)` — 请假便捷函数

## 如何获取 approval_code

1. 打开 [飞书审批管理后台（开发者模式）](https://www.feishu.cn/approval/admin/approvalList?devMode=on)
2. 找到目标审批 → 点击编辑
3. 从浏览器地址栏复制 `definitionCode=` 后面的值

## 典型工作流：处理审批

1. `approval_list_instances(code)` → 获取实例列表
2. `approval_get_instance(instance_code)` → 查看详情，从 `task_list` 中找到 `task_id`
3. `approval_approve_task()` 同意 / `approval_reject_task()` 拒绝 / `approval_transfer_task()` 转交

## 常见表单控件类型

| 控件类型 | 说明 | value 格式 |
|----------|------|------------|
| `input` | 单行文本 | `"文本内容"` |
| `textarea` | 多行文本 | `"文本内容"` |
| `date` | 日期 | `"2026-03-01T09:00:00+08:00"` (RFC3339) |
| `radioV2` | 单选 | `"选项名称"` |
| `checkboxV2` | 多选 | `["选项1","选项2"]` |

## 常见错误

| 错误 | 正确做法 |
|------|----------|
| 想用 API 列出所有审批定义 | 无此 API，从管理后台获取 approval_code |
| form 传对象而非 JSON 字符串 | `form` 参数需要 `json.dumps([...])` |
| 忘记传 `task_id` 执行同意/拒绝 | 先通过 `approval_get_instance` 获取 task_id |
| 请假日期格式错误 | 必须用 RFC3339 格式 `"2026-03-01T00:00:00+08:00"` |

## 所需权限

- `approval:approval` — 审批完整权限
- `approval:approval:readonly` — 只读权限
- `approval:task` — 审批人操作（同意/拒绝/转交）

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。
