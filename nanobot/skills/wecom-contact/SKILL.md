---
name: wecom-contact
description: 企业微信通讯录 — 用户信息查询、部门列表、通过手机号/邮箱查 userid。当用户提及企业微信、wecom、通讯录、查人、查员工、部门列表、组织架构、userid、手机号查人、邮箱查人时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 企业微信通讯录 (Contact)

企业微信通讯录 API，查询用户信息和部门组织结构。

## 使用流程

1. 根据下方 API 函数确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### get_user

获取用户信息。

```
python3 scripts/wecom_contact.py user --userid zhangsan
```

返回：{userid, name, department, position, mobile, email, gender, avatar, status, ...}

### list_department_users

获取部门下用户列表（1 表示根部门）。

```
python3 scripts/wecom_contact.py dept-users --department-id 1 --fetch-child 1
```

### get_department

获取部门信息。

```
python3 scripts/wecom_contact.py dept --department-id 1
```

### list_departments

获取子部门列表。

```
python3 scripts/wecom_contact.py dept-children --parent-id 1
```

### search

通过手机号或邮箱查询 userid。

```
python3 scripts/wecom_contact.py search --mobile "13800138000"
python3 scripts/wecom_contact.py search --email "zhang@example.com"
```

返回：{userid, name, ...}

## 用户 ID 类型说明

| ID 类型 | 说明 |
|---------|------|
| `userid` | 企业内用户唯一标识，由管理员设置（通常是拼音或工号） |
| `mobile` | 手机号 |
| `email` | 邮箱 |

## 常见错误

| 错误 | 正确做法 |
|------|----------|
| 未配置通讯录权限范围 | 管理后台 → 应用 → 权限管理 → 添加通讯录查看权限 |
| Access Token 过期 | Token 有效期 2 小时，脚本会自动刷新 |
| 部门 ID 不存在 | 企业微信部门 ID 是整数，根部门是 1 |
| 用户不在可见范围 | 检查应用权限的可见范围配置 |

## 所需权限

- **通讯录查看权限**：在应用管理后台配置
- **可见范围**：选择需要访问的部门或全部成员

## 配置说明

自动读取 `~/.hiperone/config.json` 中的企业微信配置：

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "corp_id": "wwxxxxxxxxxxxx",
      "corp_secret": "xxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

或通过环境变量：
- `NANOBOT_CHANNELS__WECOM__CORP_ID`
- `NANOBOT_CHANNELS__WECOM__CORP_SECRET`

## 官方文档

- [通讯录 API 文档](https://developer.work.weixin.qq.com/document/path/90208)
- [读取成员](https://developer.work.weixin.qq.com/document/path/90196)
- [获取部门成员](https://developer.work.weixin.qq.com/document/path/90200)
