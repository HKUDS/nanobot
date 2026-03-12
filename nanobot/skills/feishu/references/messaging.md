# 消息 (Messaging)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中发送和回复飞书消息。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `im:message:send_as_bot` | 以应用身份发送消息 |

## 发送消息

```typescript
// 发送文本消息
const res = await client.im.message.create({
  params: { receive_id_type: 'chat_id' },
  data: {
    receive_id: 'oc_xxx',
    content: JSON.stringify({ text: '你好，这是一条测试消息' }),
    msg_type: 'text',
  },
});
if (res.code !== 0) throw new Error(`[${res.code}] ${res.msg}`);
```

### receive_id_type 与 ID 前缀对应关系

| receive_id_type | ID 前缀 | 说明 |
|-----------------|---------|------|
| `chat_id` | `oc_` | 群聊 ID |
| `open_id` | `ou_` | 用户 open_id |
| `union_id` | `on_` | 用户 union_id |
| `user_id` | 无固定前缀 | 用户 user_id |
| `email` | - | 用户邮箱 |

## 发送富文本消息

```typescript
await client.im.message.create({
  params: { receive_id_type: 'chat_id' },
  data: {
    receive_id: 'oc_xxx',
    content: JSON.stringify({
      zh_cn: {
        title: '项目更新',
        content: [
          [
            { tag: 'text', text: '版本 2.0 已发布，主要更新：' },
            { tag: 'a', text: '查看详情', href: 'https://example.com' },
          ],
        ],
      },
    }),
    msg_type: 'post',
  },
});
```

## 发送卡片消息

```typescript
// 方式 1：JSON 卡片
await client.im.message.create({
  params: { receive_id_type: 'chat_id' },
  data: {
    receive_id: 'oc_xxx',
    content: JSON.stringify({
      header: {
        template: 'blue',
        title: { content: '卡片标题', tag: 'plain_text' },
      },
      elements: [
        { tag: 'markdown', content: '**进度更新**\n- 前端：80%\n- 后端：60%' },
        {
          tag: 'action',
          actions: [
            { tag: 'button', text: { tag: 'plain_text', content: '确认' }, type: 'primary' },
          ],
        },
      ],
    }),
    msg_type: 'interactive',
  },
});

// 方式 2：SDK 内置默认卡片（快速使用）
await client.im.message.create({
  params: { receive_id_type: 'chat_id' },
  data: {
    receive_id: 'oc_xxx',
    content: lark.messageCard.defaultCard({ title: '标题', content: '内容' }),
    msg_type: 'interactive',
  },
});

// 方式 3：卡片模板（推荐，在卡片搭建工具中配置后使用 template_id）
await client.im.message.createByCard({
  params: { receive_id_type: 'chat_id' },
  data: {
    receive_id: 'oc_xxx',
    template_id: 'your_template_id',
    template_variable: { title: '标题', content: '正文内容' },
  },
});
```

## 回复消息

```typescript
await client.im.message.reply({
  path: { message_id: 'om_xxx' },
  data: {
    content: JSON.stringify({ text: '收到，我马上处理' }),
    msg_type: 'text',
  },
});
```

## 编辑消息（24h 内）

```typescript
await client.im.message.update({
  path: { message_id: 'om_xxx' },
  data: {
    content: JSON.stringify({ text: '已更新的消息内容' }),
    msg_type: 'text',
  },
});
```

## 更新卡片消息

```typescript
await client.im.message.patch({
  path: { message_id: 'om_xxx' },
  data: {
    content: JSON.stringify({
      elements: [{ tag: 'markdown', content: '已更新的卡片内容' }],
    }),
  },
});
```

## 消息内容格式

### text（文本）

```json
{"text": "你好，这是一条消息"}
```

支持 @ 用户：`{"text": "<at user_id=\"ou_xxx\">张三</at> 请查看"}`

### post（富文本）

```json
{
  "zh_cn": {
    "title": "标题",
    "content": [
      [
        {"tag": "text", "text": "普通文本"},
        {"tag": "a", "text": "链接文字", "href": "https://example.com"},
        {"tag": "at", "user_id": "ou_xxx"}
      ]
    ]
  }
}
```

### interactive（卡片）

```json
{
  "header": {
    "template": "blue",
    "title": {"content": "卡片标题", "tag": "plain_text"}
  },
  "elements": [
    {"tag": "markdown", "content": "**标题**\n内容文本"},
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "按钮"}, "type": "primary"}
      ]
    }
  ]
}
```

## 使用限制

- 向同一用户发消息限频：**5 QPS**
- 向同一群组发消息限频：群内机器人共享 **5 QPS**
- 文本消息最大 **150 KB**
- 卡片/富文本消息最大 **30 KB**

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| `content` 传对象 | 必须 `JSON.stringify({text: 'hello'})` |
| 群聊 ID 用 `open_id` 类型 | `oc_` 开头的是 `chat_id` |
| 富文本 content 不是二维数组 | `content: [[{tag:'text', text:'...'}]]` 外层是行数组 |
| 忘记开启机器人能力 | 应用能力 → 添加机器人 |
