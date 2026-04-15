
# contact +get-user（获取用户信息）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

本 skill 对应 shortcut：`lark-cli contact +get-user`。

支持两种模式：

1. **不传 `--user-id`**：获取当前用户自己的信息（底层 `GET /open-apis/authen/v1/user_info`）
2. **传 `--user-id`**：获取指定用户信息（底层 `GET /open-apis/contact/v3/users/{user_id}`，默认 `user_id_type=open_id`）

## 命令

```bash
# 模式 1：获取当前用户
lark-cli contact +get-user

# 模式 2：获取指定用户（默认 user_id_type=open_id）
lark-cli contact +get-user --user-id ou_xxx

# 指定 user_id_type
lark-cli contact +get-user --user-id 4g3f... --user-id-type user_id

# 表格输出（默认 JSON）
lark-cli contact +get-user --user-id ou_xxx --table
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--user-id <id>` | 否 | 用户 ID；不传则获取当前用户 |
| `--user-id-type <type>` | 否 | `open_id`（默认）/ `union_id` / `user_id` |
| `--table` | 否 | 表格输出（默认 JSON） |

## 常见错误（41050）

如果返回提示无权限（常见错误码 `41050`），通常是**组织架构可见范围**限制导致：

- 建议联系管理员调整当前用户的组织架构可见范围
- 或改用应用身份（tenant_access_token）调用通讯录 API

## 参考

- [lark-contact-search-user](lark-contact-search-user.md) — 先搜到 open_id 再 get
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
