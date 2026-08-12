# WebSocket 服务器 channel

Nanobot 可以充当 WebSocket 服务器，使外部客户端（Web 应用、CLI、脚本）能够通过持久连接与 agent 实时交互。

## 功能

- 通过 WebSocket 进行双向实时通信
- 支持流式传输：逐 token 接收 agent 响应
- 基于 token 的身份验证（静态 token 和短期签发的 token）
- 多聊天复用：一个连接可以运行多个并发的 `chat_id`
- 支持 TLS/SSL（WSS），并强制要求最低 TLSv1.2
- 通过 `allowFrom` 提供客户端允许列表
- 自动清理失效连接

## 快速开始

### 1. 配置

WebSocket channel 默认已启用。仅在 `channels.websocket` 下添加要覆盖的字段：

```json
{
  "channels": {
    "websocket": {
      "host": "127.0.0.1",
      "port": 8765,
      "path": "/",
      "tokenIssueSecret": "your-webui-password",
      "websocketRequiresToken": true,
      "allowFrom": ["*"],
      "streaming": true
    }
  }
}
```

### 2. 启动 nanobot

```bash
nanobot gateway
```

你应当会看到：

```text
WebSocket server listening on ws://127.0.0.1:8765/
```

### 3. 连接客户端

```bash
# 使用 websocat
websocat ws://127.0.0.1:8765/?client_id=alice

# 使用 Python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8765/?client_id=alice") as ws:
        ready = json.loads(await ws.recv())
        print(ready)  # {"event": "ready", "chat_id": "...", "client_id": "alice"}
        await ws.send(json.dumps({"content": "Hello nanobot!"}))
        reply = json.loads(await ws.recv())
        print(reply["text"])

asyncio.run(main())
```

## 连接 URL

```text
ws://{host}:{port}{path}?client_id={id}&token={token}
```

| 参数 | 必填 | 描述 |
|-----------|----------|-------------|
| `client_id` | 否 | 用于 `allowFrom` 授权的标识符。若省略，将自动生成为 `anon-xxxxxxxxxxxx`。最多截断为 128 个字符。 |
| `token` | 条件性必填 | 身份验证 token。当 `websocketRequiresToken` 为 `true` 或配置了 `token`（静态 secret）时必须提供，除非请求来自已通过身份验证的 `trustedProxyAuth` 对等方。 |

## Wire Protocol

所有帧均为 JSON 文本。每条消息都有一个 `event` 字段。

### 服务器 → 客户端

**`ready`**：在建立连接后立即发送：

```json
{
  "event": "ready",
  "chat_id": "uuid-v4",
  "client_id": "alice"
}
```

**`message`**：完整的 agent 响应：

```json
{
  "event": "message",
  "chat_id": "uuid-v4",
  "text": "Hello! How can I help?",
  "media": ["/tmp/image.png"],
  "reply_to": "msg-id"
}
```

仅在适用时才会存在 `media` 和 `reply_to`。

**`delta`**：流式文本块（仅当 `streaming: true` 时）：

```json
{
  "event": "delta",
  "chat_id": "uuid-v4",
  "text": "Hello",
  "stream_id": "s1"
}
```

**`stream_end`**：表示一个流式片段结束：

```json
{
  "event": "stream_end",
  "chat_id": "uuid-v4",
  "stream_id": "s1"
}
```

**`reasoning_delta`**：当前 assistant turn 的增量 model 推理/思考块。与 `delta` 对应，但目标是答案上方的推理气泡，而不是答案正文：

```json
{
  "event": "reasoning_delta",
  "chat_id": "uuid-v4",
  "text": "Let me decompose ",
  "stream_id": "r1"
}
```

**`reasoning_end`**：当前推理流的关闭标记。WebUI 使用此标记锁定原位气泡，并将闪烁标题切换为静态的折叠状态：

```json
{
  "event": "reasoning_end",
  "chat_id": "uuid-v4",
  "stream_id": "r1"
}
```

仅当该 channel 的 `showReasoning` 为 `true`（默认值），且 model 返回推理内容时，才会发送推理帧（DeepSeek-R1 / Kimi / MiMo / OpenAI 推理 model、Anthropic 扩展思考，或内联 `<think>` / `<thought>` 标签）。不具备推理能力的 model 不会产生任何 `reasoning_delta` 帧。

**`runtime_model_updated`**：当 gateway 默认运行时发生变化，或配置重新加载要求客户端刷新其 model 目录时广播：

```json
{
  "event": "runtime_model_updated",
  "model_name": "openai/gpt-4.1-mini",
  "model_preset": "fast"
}
```

未启用具名 preset 时会省略 `model_preset`。WebUI 客户端使用此 event
在默认运行时和配置变更后刷新 model 设置。`/model <preset>`
仅限于 session；其选择会通过 `session_updated` 以及
session 行的 `model_preset` 字段反映，而非通过此全局 event。

**`attached`**：针对入站 `new_chat` / `attach` envelope 的确认（参见[多聊天复用](#multi-chat-multiplexing)）：

```json
{"event": "attached", "chat_id": "uuid-v4"}
```

**`error`**：针对格式错误的入站 envelope 的软错误。连接保持打开：

```json
{"event": "error", "detail": "invalid chat_id"}
```

### 客户端 → 服务器

**旧版（默认聊天）：**发送纯字符串，或带有已识别文本字段的 JSON 对象：

```json
"Hello nanobot!"
```

```json
{"content": "Hello nanobot!"}
```

已识别字段：`content`、`text`、`message`（按该顺序检查）。无效 JSON 会被视为纯文本。这些帧会路由至连接的默认 `chat_id`（即 `ready` 中公布的那个）。

**类型化 envelope（多聊天）：**任何具有字符串 `type` 字段的 JSON 对象都是类型化 envelope：

| `type` | 字段 | 效果 |
|--------|--------|--------|
| `new_chat` | — | 服务器创建新的 `chat_id`，订阅此连接，并以 `attached` 响应。 |
| `attach` | `chat_id` | 订阅现有 `chat_id`（例如在页面重新加载后）。以 `attached` 响应。 |
| `message` | `chat_id`, `content` | 在 `chat_id` 上发送 `content`。首次使用会自动 attach；无需显式 `attach`。 |

完整流程请参见[多聊天复用](#multi-chat-multiplexing)。

## 配置参考

所有字段均位于 `config.json` 中的 `channels.websocket` 下。

### 连接

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | 启用 WebSocket 服务器。仅当你有意不需要捆绑的 WebUI/WebSocket 界面时，才设置为 `false`。 |
| `host` | string | `"127.0.0.1"` | 绑定地址。使用 `"0.0.0.0"` 以接受外部连接。 |
| `port` | int | `8765` | 监听端口。 |
| `path` | string | `"/"` | WebSocket 升级路径。尾随斜杠会被规范化（保留根路径 `/`）。 |
| `publicWsUrl` | string | `""` | `/webui/bootstrap` 返回的精确公共 `ws://` 或 `wss://` endpoint。当反向代理使用源 `Host` header 转发请求时设置此项（例如 `wss://claw.example.com/`）；其路径必须与 `path` 匹配。 |
| `maxMessageBytes` | int | `37748736` | 最大入站消息大小，以字节为单位（1 KB – 40 MB）。默认值（36 MB）可接受最多 4 个各为 8 MB 的 base64 编码图像附件；如果该 channel 仅承载文本，请降低此值。 |

### 身份验证

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `token` | string | `""` | 静态共享 secret。设置后，客户端必须提供与此 secret 匹配的 `?token=<value>`（时序安全比较）。签发的 token 也可作为回退方式接受。受信任代理断言会绕过此要求。 |
| `websocketRequiresToken` | bool | `true` | 当为 `true` 且未配置静态 `token` 时，客户端仍必须提供有效的签发 token，除非 `trustedProxyAuth` 对直接代理对等方进行身份验证。设置为 `false` 可允许未经身份验证的连接（仅在本地/受信任网络中安全）。 |
| `tokenIssuePath` | string | `""` | 用于签发短期 token 的 HTTP 路径。必须与 `path` 不同。参见 [Token 签发](#token-issuance)。 |
| `tokenIssueSecret` | string | `""` | 通过签发 endpoint 获取 token 所需的 secret。若为空，任何客户端都可以从 `tokenIssuePath` 获取 WebSocket 连接 token（会记录为警告）。`/webui/bootstrap` 为本地或经 secret 身份验证的请求签发 token；受信任代理请求不会收到 bootstrap 或 API token。 |
| `trustedProxyAuth` | object 或 `null` | `null` | 针对直接连接的上游代理提供的可选双部分无 token 授权。`trustedPeerCidrs` 和非空 `assertionHeader` 值必须同时匹配；单独的 CIDR 永远不会授权 bootstrap 或 WebSocket/API 访问。 |
| `trustedProxyAuth.trustedPeerCidrs` | CIDR string 列表 | — | 可提供断言的直接 TCP 对等网络。支持 IPv4、IPv6 和 IPv4 映射 IPv6 对等方；拒绝通用 CIDR（`0.0.0.0/0`、`::/0`）。 |
| `trustedProxyAuth.assertionHeader` | string | — | 身份感知代理在成功完成身份验证后注入的 header。会拒绝路由/客户端元数据 header（`Host`、`Forwarded`、`X-Forwarded-*`、`X-Real-IP`、`CF-Connecting-IP`）；nanobot 信任其余 header 的非空值，但不会对其进行加密验证。 |
| `tokenTtlS` | int | `300` | 签发 token 的存活时间，单位为秒（30 – 86,400）。 |

### 访问控制

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `allowFrom` | string 列表 | `["*"]` | 允许的 `client_id` 值。`"*"` 允许全部；`[]` 拒绝全部。 |

### 流式传输

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `streaming` | bool | `true` | 启用流式模式。agent 会发送 `delta` + `stream_end` 帧，而非单个 `message`。 |

### 保活

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `pingIntervalS` | float | `20.0` | WebSocket ping 间隔，单位为秒（5 – 300）。 |
| `pingTimeoutS` | float | `20.0` | 在关闭连接前等待 pong 的时间（5 – 300）。 |

### TLS/SSL

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `sslCertfile` | string | `""` | TLS 证书文件（PEM）的路径。必须同时设置 `sslCertfile` 和 `sslKeyfile` 才能启用 WSS。 |
| `sslKeyfile` | string | `""` | TLS 私钥文件（PEM）的路径。最低 TLS 版本强制为 TLSv1.2。 |

## Token 签发

对于 `websocketRequiresToken: true` 的生产部署，请使用短期 token，而不要在客户端中嵌入静态 secret。

### 工作原理

1. 客户端使用 `Authorization: Bearer {tokenIssueSecret}`（或 `X-Nanobot-Auth` header）发送 `GET {tokenIssuePath}`。
2. 服务器响应一个一次性 token：

```json
{"token": "nbwt_aBcDeFg...", "expires_in": 300}
```

3. 客户端使用 `?token=nbwt_aBcDeFg...&client_id=...` 打开 WebSocket。
4. token 会被消耗（单次使用），且无法重复使用。

嵌入式 WebUI 的 `/webui/bootstrap` 路由会为本地或经 secret 身份验证的请求返回一个 WebSocket token 和
REST `api_token`。当 `trustedProxyAuth` 对直接代理对等方进行身份验证时，它仅返回连接
元数据：没有 bootstrap token、没有 REST API token，并且 WebSocket handshake 或后续 REST 请求均不需要
token query parameter。
### 受信任代理无 token 引导

`trustedProxyAuth` 是一种可选替代方案，适用于身份感知型反向代理在连接到 nanobot 前对用户进行身份验证的部署。
代理断言成为整个 WebUI 表面的身份验证边界：`/webui/bootstrap`、WebSocket 握手和 REST API 路由。
仅当**同时**满足以下条件时才接受引导：直接 TCP 对等端匹配 `trustedPeerCidrs` 之一，且已配置的断言标头存在且非空。
仅有受信任地址绝不充分。

Nanobot 在对等端检查中刻意只使用 `connection.remote_address`。
它绝不会使用 `X-Forwarded-For`、`Forwarded`、`X-Real-IP`、`CF-Connecting-IP`
或 `X-Forwarded-Host` 来决定代理是否受信任。Nanobot 信任由明确受信任对等端提供的
断言，但不会对 JWT/断言内容进行加密验证或解析。如果不受信任的客户端可以直接连接到
nanobot 监听器，请勿启用此选项。

已配置的断言标头必须是由代理生成的身份验证断言，而不是路由或客户端元数据标头。
`Host`、`Forwarded`、`X-Forwarded-*`、`X-Real-IP` 和 `CF-Connecting-IP` 等标头
会被配置拒绝；请改用身份 provider 的认证后断言标头
（例如 `Cf-Access-Jwt-Assertion`）。

例如，本地 Cloudflare Tunnel 配合 Cloudflare Access 可以在边缘验证
用户，并转发生成的 `Cf-Access-Jwt-Assertion`：

```json
{
  "channels": {
    "websocket": {
      "host": "127.0.0.1",
      "publicWsUrl": "wss://nanobot.example.com/",
      "trustedProxyAuth": {
        "trustedPeerCidrs": ["127.0.0.1/32", "::1/128"],
        "assertionHeader": "Cf-Access-Jwt-Assertion"
      }
    }
  }
}
```

这仅在直接连接的 `cloudflared` 进程通过已配置的回环地址访问
nanobot 且提供非空断言时有效。请继续使用防火墙阻止不受信任的客户端访问 nanobot；
此配置不是基于 CIDR 的引导绕过。

### 示例设置

```json
{
  "channels": {
    "websocket": {
      "port": 8765,
      "path": "/ws",
      "tokenIssuePath": "/auth/token",
      "tokenIssueSecret": "your-secret-here",
      "tokenTtlS": 300,
      "websocketRequiresToken": true,
      "allowFrom": ["*"],
      "streaming": true
    }
  }
}
```

客户端流程：

```bash
# 1. 获取 token
curl -H "Authorization: Bearer your-secret-here" http://127.0.0.1:8765/auth/token

# 2. 使用 token 连接
websocat "ws://127.0.0.1:8765/ws?client_id=alice&token=nbwt_aBcDeFg..."
```

### 限制

- 已签发的 token 为一次性使用，每个 token 只能完成一次握手。
- 未使用的 token 上限为 10,000。超出上限的请求将返回 HTTP 429。
- 每次签发或验证请求时，都会惰性清除过期 token。

## 多聊天多路复用

单个 WebSocket 可以承载多个并发聊天。服务器将 `chat_id -> {connections}` 跟踪为扇出集合，
因此同一聊天也可以镜像到多个连接中（例如两个浏览器标签页）。

### 典型流程（带侧边栏的 Web UI）

```text
客户端                                服务器
  | --- 连接 ------------------------>  |
  | <-- {"event":"ready",              |
  |      "chat_id":"d3..."}   （默认）  |
  |                                     |
  | --- {"type":"new_chat"} --------->  |
  | <-- {"event":"attached",            |
  |      "chat_id":"a1..."}             |
  |                                     |
  | --- {"type":"message",              |
  |      "chat_id":"a1...",             |
  |      "content":"hi"} ------------>  |
  | <-- {"event":"delta", ...}          |
  | <-- {"event":"stream_end", ...}     |
  |                                     |
  | --- {"type":"attach",               |  # 页面重新加载后
  |      "chat_id":"a1..."} --------->  |
  | <-- {"event":"attached", ...}       |
```

### 规则

- 每个出站事件都包含 `chat_id`。客户端必须根据该字段分发。
- `chat_id` 格式：`^[A-Za-z0-9_:-]{1,64}$`。不匹配的值将返回 `error`。
- `message` 会在首次使用时自动 attach，对于服务器在同一连接上创建的聊天（`new_chat`），无需单独执行 `attach`。
- 错误（无效 envelope、未知 `type`、错误的 `chat_id`）为软错误：服务器回复 `{"event":"error","detail":"..."}`，并保持连接打开。

### 向后兼容性

仅发送纯文本或 `{"content": ...}` 的旧版客户端无需任何修改即可继续工作：
这些 frame 会路由到连接的默认 `chat_id`（即 `ready` 中的那个）。无需配置标志。

### 安全边界

`chat_id` 是一种*能力*：任何持有有效 WebSocket 身份验证凭据和 chat_id 的人都可以
attach 到该对话并查看其输出。这对于 nanobot 的本地单用户模型是安全的。
多租户部署应按用户为 chat_ids 添加命名空间（或引入按租户划分的身份验证门槛）；
nanobot 目前不会执行此操作。

## 安全说明

- **时序安全比较**：静态 token 验证使用 `hmac.compare_digest` 防止时序攻击。
- **纵深防御**：在 HTTP 握手层和消息层都会检查 `allowFrom`。
- **作为能力的 chat_id**：请参阅[多聊天多路复用](#multi-chat-multiplexing)。WebSocket 握手上的身份验证是唯一的防线；通过验证的调用方可以 attach 到其知晓的任意 chat_id。
- **TLS 强制执行**：启用 SSL 时，允许的最低版本为 TLSv1.2。
- **默认安全**：`websocketRequiresToken` 默认为 `true`。仅在受信任网络中才应显式将其设为 `false`。

## 媒体文件

出站 `message` 事件可能包含一个 `media` 字段，其中含有本地文件系统路径。远程客户端无法直接访问这些文件，它们需要以下其中一项：

- 共享文件系统挂载，或
- 提供 nanobot 媒体目录的 HTTP 文件服务器

## 常见模式

### 受信任的本地网络（无需身份验证）

```json
{
  "channels": {
    "websocket": {
      "host": "0.0.0.0",
      "port": 8765,
      "websocketRequiresToken": false,
      "allowFrom": ["*"],
      "streaming": true
    }
  }
}
```

### 静态 token（简单身份验证）

```json
{
  "channels": {
    "websocket": {
      "token": "my-shared-secret",
      "allowFrom": ["alice", "bob"]
    }
  }
}
```

客户端使用 `?token=my-shared-secret&client_id=alice` 连接。

### 使用已签发 token 的公共端点

```json
{
  "channels": {
    "websocket": {
      "host": "0.0.0.0",
      "port": 8765,
      "path": "/ws",
      "tokenIssuePath": "/auth/token",
      "tokenIssueSecret": "production-secret",
      "websocketRequiresToken": true,
      "sslCertfile": "/etc/ssl/certs/server.pem",
      "sslKeyfile": "/etc/ssl/private/server-key.pem",
      "allowFrom": ["*"]
    }
  }
}
```

### 自定义路径

```json
{
  "channels": {
    "websocket": {
      "path": "/chat/ws",
      "allowFrom": ["*"]
    }
  }
}
```

客户端连接到 `ws://127.0.0.1:8765/chat/ws?client_id=...`。尾部斜杠会被规范化，因此 `/chat/ws/` 的效果相同。
