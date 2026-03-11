# nanobot API 互动聊天通道使用说明

本文说明如何使用 `channels.api` 把 nanobot 作为一个可交互的聊天 API（WebSocket）。

## 1. 功能概览

- 通道类型：`WebSocket`（不是 HTTP REST）
- 复用链路：`APIChannel -> MessageBus -> AgentLoop`（与现有渠道一致）
- 支持：
  - 实时聊天
  - 进度流（`progress`）
  - 工具提示流（可选）
  - 会话隔离（`chatId` / `sessionKey`）
  - 访问控制（`allowFrom`）
  - token 鉴权（可选）

## 2. 配置方式

在 `config.json` 中增加/修改以下配置：

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "api": {
      "enabled": true,
      "path": "/chat",
      "token": "your-shared-token",
      "allowFrom": ["*"]
    }
  }
}
```

字段说明：

- `channels.api.enabled`: 是否启用 API 通道
- `channels.api.path`: WebSocket 路径，默认 `/chat`
- `channels.api.token`: 可选共享 token；为空表示不校验 token
- `channels.api.allowFrom`: 允许的 `senderId` 列表
  - `[]`：拒绝所有
  - `["*"]`：允许所有
  - 其他：仅允许精确匹配的 `senderId`
- `gateway.host` / `gateway.port`: API 监听地址和端口

## 3. 启动服务

```bash
nanobot gateway
```

如果你指定了端口：

```bash
nanobot gateway --port 18888
```

`--port` 会覆盖运行时 `gateway.port`，API 通道会跟随该端口监听。

## 4. 日志存储

API 通道会把关键事件写入 JSONL 文件（每行一个 JSON）：

```text
<实例数据目录>/logs/api/chat_events.jsonl
```

默认配置下（未使用 `--config`）通常是：

```text
~/.nanobot/logs/api/chat_events.jsonl
```

如果使用了 `--config /path/to/config.json`，则实例数据目录是该配置文件所在目录，日志路径会变为：

```text
/path/to/logs/api/chat_events.jsonl
```

日志包含但不限于：服务启动/停止、连接打开/关闭、入站消息、出站消息、错误事件。

## 5. 连接地址与鉴权

连接地址：

```text
ws://<host>:<port><path>
```

默认即：

```text
ws://127.0.0.1:18790/chat
```

token 传递方式（二选一）：

1. Query 参数：`ws://127.0.0.1:18790/chat?token=your-shared-token`
2. Header：`Authorization: Bearer your-shared-token`

鉴权失败会被关闭连接（`4401`）；路径不匹配会关闭连接（`4404`）。

## 6. 消息协议

### 6.1 服务端握手消息

连接成功后，服务端会先发：

```json
{"type":"ready","channel":"api"}
```

### 6.2 客户端 -> 服务端

#### 聊天请求（`chat`）

```json
{
  "type": "chat",
  "senderId": "user_001",
  "chatId": "room_a",
  "requestId": "req_123",
  "sessionKey": "api:room_a:thread_1",
  "content": "你好，帮我总结今天待办",
  "media": [],
  "metadata": {
    "source": "web-ui"
  }
}
```

字段规则：

- `type`: 可省略，默认按 `chat` 处理
- `senderId`: 必填；用于权限校验（`allowFrom`）
- `chatId`: 可选；默认等于 `senderId`
- `content`: 必填，非空字符串
- `requestId`: 可选；会原样带回响应，便于前端关联
- `sessionKey`: 可选；用于自定义会话隔离
- `media`: 可选，字符串数组
- `metadata`: 可选，对象

#### 心跳

```json
{"type":"ping"}
```

返回：

```json
{"type":"pong"}
```

### 6.3 服务端 -> 客户端

#### 最终回复

```json
{
  "type": "message",
  "channel": "api",
  "chatId": "room_a",
  "content": "这是最终答复",
  "requestId": "req_123",
  "metadata": {}
}
```

#### 进度流

```json
{
  "type": "progress",
  "channel": "api",
  "chatId": "room_a",
  "content": "正在检索资料...",
  "requestId": "req_123",
  "toolHint": true,
  "metadata": {
    "_progress": true,
    "_tool_hint": true
  }
}
```

说明：

- `type=progress` 由内部 `_progress` 元数据触发
- `toolHint` 是否出现，取决于是否是工具提示流
- 是否发送 progress/toolHint，受 `channels.sendProgress` 与 `channels.sendToolHints` 控制

#### 错误

```json
{
  "type": "error",
  "error": "content must be a non-empty string.",
  "requestId": "req_123"
}
```

## 7. 会话与命令行为

- 默认会话键：`api:<chatId>`
- 你可以通过 `sessionKey` 强制分会话（例如同一 `chatId` 下多线程会话）
- 支持与其他渠道一致的命令：
  - `/new`：清空当前会话并重新开始
  - `/stop`：停止当前会话内正在执行的任务
  - `/help`：返回帮助

## 8. 最小客户端示例

### 7.1 JavaScript（浏览器）

```javascript
const ws = new WebSocket("ws://127.0.0.1:18790/chat?token=your-shared-token");

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "chat",
    senderId: "web_user_1",
    chatId: "room_web",
    requestId: "r1",
    content: "给我一个三行总结"
  }));
};

ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  console.log(msg.type, msg.content || msg.error);
};
```

### 7.2 Python（websockets）

```python
import asyncio
import json
import websockets

async def main():
    uri = "ws://127.0.0.1:18790/chat?token=your-shared-token"
    async with websockets.connect(uri) as ws:
        print(await ws.recv())  # ready
        await ws.send(json.dumps({
            "type": "chat",
            "senderId": "py_user_1",
            "chatId": "room_py",
            "requestId": "r1",
            "content": "你好"
        }, ensure_ascii=False))
        while True:
            print(await ws.recv())

asyncio.run(main())
```

## 9. 常见问题

- 连接后立即断开：检查 `path` 是否匹配（`/chat`）。
- 返回 `Unauthorized`：检查 token（query 或 Bearer header）。
- 发消息无响应：检查 `allowFrom` 是否允许当前 `senderId`。
- 看不到进度流：确认 `channels.sendProgress=true`。
- 想隐藏工具调用提示：`channels.sendToolHints=false`。
