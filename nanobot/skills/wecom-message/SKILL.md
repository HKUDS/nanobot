---
name: wecom-message
description: 企业微信消息收发 — 发送/撤回文本、图片、文件、Markdown 消息、群消息。当用户提及发消息、发企业微信、撤回消息、群消息、send message 时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 企业微信消息收发 (Message)

企业微信消息 API，支持发送文本、图片、文件、语音、图文、Markdown 消息。

## 使用流程

1. 根据下方 API 函数确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### send_text

发送文本消息。

```
python3 scripts/wecom_message.py send-text --touser zhangsan --content "你好，开会了"
```

返回：{errcode, errmsg, msgid}

### send_image

发送图片消息（需先上传）。

```
python3 scripts/wecom_message.py send-image --touser zhangsan --media_id MEDIA_ID
```

### send_file

发送文件消息（需先上传）。

```
python3 scripts/wecom_message.py send-file --touser zhangsan --media_id MEDIA_ID
```

### send_markdown

发送 Markdown 消息。

```
python3 scripts/wecom_message.py send-markdown --touser zhangsan --content "## 标题\n**加粗**内容"
```

### upload_media

上传媒体文件。

```
python3 scripts/wecom_message.py upload --file /path/to/file.pdf --type file
python3 scripts/wecom_message.py upload --file /path/to/image.png --type image
python3 scripts/wecom_message.py upload --file /path/to/voice.amr --type voice
```

返回：{type, media_id, created_at}

### recall_message

撤回消息。

```
python3 scripts/wecom_message.py recall --msgid msgid_xxxxx
```

### send_group_chat

发送群消息。

```
python3 scripts/wecom_message.py group-send --chatid CHAT_ID --msgtype text --content "大家好"
```

## 消息类型

| 类型 | 说明 | 参数 |
|------|------|------|
| `text` | 文本消息 | content |
| `image` | 图片消息 | media_id |
| `file` | 文件消息 | media_id |
| `voice` | 语音消息 | media_id |
| `news` | 图文消息 | articles |
| `markdown` | Markdown 消息 | content |

## Markdown 语法支持

```markdown
# 一级标题
## 二级标题
### 三级标题

**加粗**
*斜体*
~~删除线~~

[链接](https://example.com)
`行内代码`

- 列表项 1
- 列表项 2

> 引用内容

@mention
```

## 媒体文件限制

| 类型 | 大小限制 | 格式 |
|------|---------|------|
| 图片 | ≤2MB | jpg, png, gif, bmp |
| 文件 | ≤20MB | 任意格式 |
| 语音 | ≤2MB | amr, mp3 |

## 常见错误

| 错误码 | 说明 | 解决方法 |
|--------|------|----------|
| 60020 | IP 不在白名单 | 管理后台添加可信 IP |
| 82003 | 用户不存在 | 检查 userid 是否正确 |
| 85003 | 应用无权限 | 检查应用可见范围 |
| 85016 | 媒体文件不存在 | media_id 已过期（3 天） |

## 配置说明

自动读取 `~/.hiperone/config.json` 中的企业微信配置：

```json
{
  "channels": {
    "wecom": {
      "enabled": "true",
      "corp_id": "wwd2b8d74d9fcc433b",
      "corp_secret": "xxx",
      "agent_id": 1000003
    }
  }
}
```

## 官方文档

- [发送应用消息](https://developer.work.weixin.qq.com/document/path/90236)
- [上传媒体文件](https://developer.work.weixin.qq.com/document/path/90253)
- [撤回消息](https://developer.work.weixin.qq.com/document/path/94481)
- [Markdown 语法](https://developer.work.weixin.qq.com/document/path/90255)
