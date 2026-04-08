---
name: feishu-contact
description: 飞书通讯录 — 用户信息查询、部门与子部门列表、通过手机号/邮箱查 open_id。当用户提及通讯录、查人、查员工、部门列表、组织架构、open_id、user_id、手机号查人、邮箱查人时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书通讯录 (Contact)

飞书通讯录 API，查询用户信息和部门组织结构。

## 使用流程

1. 根据下方 API 函数说明确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### get_user

获取用户信息。

```
python3 scripts/feishu_contact.py user --user-id ou_xxx --id-type open_id
```

返回: user -> {open_id, name, en_name, email, mobile, avatar, department_ids, employee_id, ...}

### list_department_users

获取部门下用户列表（"0" 表示根部门）。

```
python3 scripts/feishu_contact.py dept-users --department-id 0 --limit 50
```

### get_department

获取部门信息。

```
python3 scripts/feishu_contact.py dept --department-id od_xxx
```

### list_departments

获取子部门列表。

```
python3 scripts/feishu_contact.py dept-children --parent-id 0 --limit 50
```

### batch_get_user_id (search)

通过手机号或邮箱批量查询 open_id。

```
python3 scripts/feishu_contact.py search --mobiles "13800138000,13900139000"
python3 scripts/feishu_contact.py search --emails "zhang@example.com,li@example.com"
python3 scripts/feishu_contact.py search --mobiles "13800138000" --emails "zhang@example.com"
```

返回: {user_list: [{user_id, mobile, email}, ...]}

## 用户 ID 类型说明

| user_id_type | 前缀 | 说明 |
|--------------|------|------|
| `open_id` | `ou_` | 应用级唯一标识（默认） |
| `union_id` | `on_` | 跨应用统一标识 |
| `user_id` | 无固定前缀 | 企业内用户 ID |

## 常见错误

| 错误 | 正确做法 |
|------|----------|
| 未配置通讯录权限范围 | 安全设置 → 通讯录权限范围 → 全部成员 |
| 部门 ID 类型不匹配 | `od_` 开头用 `open_department_id`，纯数字用 `department_id` |
| 忘记传 `user_id_type` 参数 | 不传默认 `open_id`，注意和实际传入的 ID 类型一致 |
| 分页获取不完整 | 检查 `has_more` 和 `page_token` 是否需要翻页 |

## 所需权限

- `contact:user.base:readonly` — 获取用户基本信息
- `contact:user.employee_id:readonly` — 获取员工工号
- `contact:user.email:readonly` — 获取用户邮箱
- `contact:user.phone:readonly` — 获取用户手机号
- `contact:department.base:readonly` — 获取部门基本信息
- `contact:user.id:readonly` — 通过手机号/邮箱查询 open_id

**重要**：还需要在「飞书管理后台 → 安全设置 → 数据权限」中将「通讯录权限范围」设置为「全部成员」，否则只能获取到机器人所在群的成员。

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。
