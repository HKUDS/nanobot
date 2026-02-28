# Telegram 打通细节

## 概述

nanobot 与 Telegram 的集成采用**长轮询（Long Polling）**机制，由 bot 端定期向 Telegram 服务器请求新消息。

## 通信协议

### 协议方式

- **请求方式**：GET 请求（HTTPS 长连接）
- **API 端点**：`https://api.telegram.org/bot<token>/getUpdates`
- **发起方**：Bot 主动轮询 Telegram 服务器

### 长轮询工作原理

```
时间轴：
T0:      Bot → 发送 getUpdates 请求
T0-T10:  Telegram 阻塞等待（有新消息立即响应）
T10:     无新消息 → Telegram 返回 [] (空数组)
T10:     Bot → 立即发起下一个 getUpdates 请求
```

**关键特性**：
- Telegram 最多阻塞 **10 秒** 等待消息
- 若有新消息，立即返回（不需等待 10 秒）
- 无消息时，10 秒后返回空数组，降低流量占用

## 超时配置详解

### HTTPXRequest 配置（nanobot/channels/telegram.py:142）

```python
req = HTTPXRequest(
    connection_pool_size=16,    # 连接池大小
    pool_timeout=5.0,           # 连接池获取超时
    connect_timeout=30.0,       # TCP 连接建立超时
    read_timeout=30.0           # HTTP 读取超时
)
```

### 各层级超时设置对照表

| 层级 | 参数 | 值 | 用途 |
|------|------|-----|------|
| **连接池** | `pool_timeout` | 5 秒 | 从池中获取空闲连接的超时 |
| **TCP 连接** | `connect_timeout` | 30 秒 | 建立 TCP 连接的超时 |
| **HTTP 读取** | `read_timeout` | 30 秒 | 单次 HTTP 响应读取的超时（防止连接卡死） |
| **Telegram API** | `getUpdates timeout` | **10 秒**（默认） | 长轮询阻塞等待新消息的时间 |

**配置原因**：
- `read_timeout=30s` > `getUpdates timeout=10s`，确保不会因为 Telegram 正常阻塞而触发超时
- `connection_pool_size=16` 避免长轮询过程中出现 `pool-timeout`
- 使用代理时，同样配置也应用到代理请求上

## 实现细节

### 轮询启动代码（nanobot/channels/telegram.py:180-183）

```python
await self._app.updater.start_polling(
    allowed_updates=["message"],
    drop_pending_updates=True  # 启动时忽略历史消息
)
```

### 消息处理流程

1. **长轮询获取**：Bot 通过 `getUpdates` 长轮询获取新消息
2. **本地处理**：
   - 解析消息内容（文本、媒体等）
   - 下载媒体文件到 `~/.nanobot/media/`
   - 语音/音频通过 Groq API 转录
3. **转发到 MessageBus**：将消息转发到 nanobot 的消息总线处理
4. **回复发送**：通过 `send_message` API 发送回复

### 特殊处理

#### 媒体组（Media Group）缓冲

Telegram 中一次发送多张图片会产生媒体组（`media_group_id`）。nanobot 会：

```python
# 缓冲 0.6 秒，等待同组内的所有消息到达
await asyncio.sleep(0.6)
# 随后作为一个聚合的回合转发到消息处理流程
```

#### 打字指示器（Typing Indicator）

处理消息时显示"正在输入"状态：

```python
# 在消息处理前启动
self._start_typing(chat_id)

# 每 4 秒发送一次 send_chat_action，持续到消息发送完成
await asyncio.sleep(4)
await self._app.bot.send_chat_action(chat_id=chat_id, action="typing")
```

## 优缺点对比

### 长轮询 vs Webhook

| 方案 | 发起方 | 优点 | 缺点 | 适用场景 |
|------|--------|------|------|---------|
| **长轮询** | Bot | ✓ 无需公网 IP<br>✓ 无需 HTTPS<br>✓ 部署简单 | ✗ 实时性较差（秒级）<br>✗ 流量占用（轮询请求） | 家庭自托管、无公网环境 |
| **Webhook** | Telegram | ✓ 实时性好（毫秒级）<br>✓ 流量效率高 | ✗ 需要公网 IP<br>✗ 需要 HTTPS<br>✗ 部署复杂 | 生产环境、需要低延迟 |

## 代码位置

| 功能 | 文件路径 | 行号 |
|------|---------|------|
| 主实现 | `nanobot/channels/telegram.py` | - |
| HTTPXRequest 配置 | `nanobot/channels/telegram.py` | 142 |
| 长轮询启动 | `nanobot/channels/telegram.py` | 180-183 |
| 消息处理 | `nanobot/channels/telegram.py` | 330-448 |
| 媒体组处理 | `nanobot/channels/telegram.py` | 410-463 |
| 打字指示器 | `nanobot/channels/telegram.py` | 465-486 |

## 常见问题

### 为什么选择长轮询而不是 Webhook？

nanobot 的设计目标是支持在家庭网络、NAT 环境等无法使用公网 IP 的场景下运行。长轮询无此限制，更加灵活。

### 10 秒超时时间是否可配置？

当前实现使用 Telegram Bot API 的默认 10 秒超时。若要自定义，需要在 `start_polling()` 调用时传入 `timeout` 参数。

### 媒体文件存储位置

所有下载的媒体文件存储在 `~/.nanobot/media/` 目录，文件名为 Telegram 的 `file_id` 前 16 位加扩展名。

### 语音/音频处理

使用 Groq API 的转录服务（`GroqTranscriptionProvider`），需要在配置中提供 `groq_api_key`。
