---
name: feishu-message
description: 飞书消息收发 — 发送/回复/撤回/转发消息、图片文件上传、消息卡片、表情回复。当用户提及发消息、发飞书、撤回消息、转发、消息卡片、发图片、send message时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书消息收发 (Message)

飞书消息 API，支持发送文本/图片/文件/卡片消息、回复、撤回、转发、表情回复和会话历史。

## 使用流程

1. 根据下方 API 函数说明确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### send_text

发送文本消息。

```
python3 scripts/feishu_message.py send --receive-id ou_xxx --text "你好"
python3 scripts/feishu_message.py send --receive-id oc_xxx --text "你好" --id-type chat_id
```

`--id-type` 默认 `open_id`（发群聊时传 `chat_id`）。可选值: chat_id / open_id / union_id / email

### send-image

上传本地图片并发送图片消息。

```
python3 scripts/feishu_message.py send-image --receive-id oc_xxx --file /path/to/image.png
```

### send-file

上传本地文件并发送文件消息。

```
python3 scripts/feishu_message.py send-file --receive-id oc_xxx --file /path/to/doc.pdf --file-type pdf
```

`--file-type` 可选值: opus / mp4 / pdf / doc / xls / ppt / stream

### send-card

发送消息卡片 (interactive card)。

```
python3 scripts/feishu_message.py send-card --receive-id oc_xxx --card-json '{"header":{"title":{"tag":"plain_text","content":"标题"}},"elements":[{"tag":"div","text":{"tag":"plain_text","content":"内容"}}]}'
python3 scripts/feishu_message.py send-card --receive-id oc_xxx --card-json @card.json
```

`--card-json` 支持直接传 JSON 字符串，或以 `@` 前缀从文件读取。

### get_message

获取单条消息详情。

```
python3 scripts/feishu_message.py get --message-id om_xxx
```

### get_chat_history

获取会话历史消息。

```
python3 scripts/feishu_message.py history --chat-id oc_xxx --limit 20
python3 scripts/feishu_message.py history --chat-id oc_xxx --start-time "1710000000" --end-time "1710086400"
```

时间为秒级时间戳字符串。

### recall

撤回消息（仅限机器人自己发送的消息）。

```
python3 scripts/feishu_message.py recall --message-id om_xxx
```

### forward

转发消息到其他会话。

```
python3 scripts/feishu_message.py forward --message-id om_xxx --receive-id oc_yyy
```

### reply

回复指定消息。

```
python3 scripts/feishu_message.py reply --message-id om_xxx --text "收到，已处理"
```

### react

给消息添加表情回复。

```
python3 scripts/feishu_message.py react --message-id om_xxx --emoji THUMBSUP
```

常用表情: SMILE / THUMBSUP / HEART / CLAP / MUSCLE / JIAYI / OK

### reactions

获取消息的所有表情回复。

```
python3 scripts/feishu_message.py reactions --message-id om_xxx
```

## 消息类型 msg_type

| 类型 | content 格式 |
|------|-------------|
| text | `{"text": "内容"}` |
| post | `{"zh_cn": {"title": "标题", "content": [[{"tag": "text", "text": "段落"}]]}}` |
| interactive | 卡片 JSON |
| image | `{"image_key": "img_xxx"}` |

## @ 用户语法

在文本消息中 @ 用户：`{"text": "<at user_id=\"ou_xxx\">张三</at> 请查看"}`

## 使用限制

- 向同一用户发消息限频：**5 QPS**
- 向同一群组发消息限频：群内机器人共享 **5 QPS**
- 文本消息最大 **150 KB**
- 卡片/富文本消息最大 **30 KB**

## 常见错误

| 错误 | 正确做法 |
|------|----------|
| `content` 传对象 | 必须 `json.dumps({"text": "hello"})` |
| 群聊 ID 用 `open_id` 类型 | `oc_` 开头的是 `chat_id` |
| 富文本 content 不是二维数组 | `content: [[{"tag":"text", "text":"..."}]]` 外层是行数组 |
| 忘记开启机器人能力 | 应用能力 → 添加机器人 |

## 所需权限

- `im:message:send_as_bot` — 发送消息
- `im:message:readonly` — 获取消息
- `im:message` — 完整消息权限（撤回、转发）
- `im:resource` — 上传图片/文件
- `im:message.reactions:readonly` — 获取表情回复
- `im:message.reactions` — 添加表情回复

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。
