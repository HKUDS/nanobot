---
name: feishu-chat
description: 飞书群组管理 — 群 CRUD、成员管理、群信息维护。当用户提及群组、建群、群成员、拉人进群、群管理、chat group时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书群组管理 (Chat)

飞书 IM 群组相关 API，创建/管理群、获取群信息和成员、邀请/移出成员。

## 使用流程

1. 根据下方 API 函数说明确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### list_chats

获取机器人所在的群列表。

```
python3 scripts/feishu_chat.py list --limit 20
```

### get_chat

获取群详细信息。

```
python3 scripts/feishu_chat.py info --chat-id oc_xxx
```

### get_chat_members

获取群成员列表（单页）。

```
python3 scripts/feishu_chat.py members --chat-id oc_xxx --limit 50
```

### get_chat_members_all

获取群全部成员（自动分页）。

```
python3 scripts/feishu_chat.py members --chat-id oc_xxx --all
```

### create_chat

创建群。

```
python3 scripts/feishu_chat.py create --name "测试群" --description "群描述"
python3 scripts/feishu_chat.py create --name "项目群" --user-ids ou_xxx,ou_yyy --owner-id ou_xxx
```

`--chat-type` 可选值: private（私有群，默认） / public（公开群）

### update_chat

更新群信息。

```
python3 scripts/feishu_chat.py update --chat-id oc_xxx --name "新群名" --description "新描述"
```

### add_members

邀请用户进群。

```
python3 scripts/feishu_chat.py add-members --chat-id oc_xxx --user-ids ou_xxx,ou_yyy
```

### remove_members

将用户移出群。

```
python3 scripts/feishu_chat.py remove-members --chat-id oc_xxx --user-ids ou_xxx
```

### disband_chat

解散群。

```
python3 scripts/feishu_chat.py disband --chat-id oc_xxx
```

## ID 前缀对应关系

| receive_id_type | ID 前缀 | 说明 |
|-----------------|---------|------|
| `chat_id` | `oc_` | 群聊 ID |
| `open_id` | `ou_` | 用户 open_id |
| `union_id` | `on_` | 用户 union_id |

## 所需权限

- `im:chat:readonly` — 获取群组信息
- `im:chat.member:read` — 获取群成员
- `im:chat` — 创建/更新/解散群
- `im:chat.member` — 邀请/移出成员

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。
