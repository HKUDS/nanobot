# 给 nanobot 添加 HTTP Channel

## 目标

新增一个 HTTP channel，让外部设备（如 M5Stack）能通过 HTTP POST 与 nanobot gateway 通信。与 Telegram/Email 等 channel 不同，HTTP channel 是**同步请求-响应模式**：客户端 POST 一条消息，阻塞等待 agent 回复，一次 HTTP 往返完成一轮对话。

## 需要修改的文件

### 1. 新建 `nanobot/channels/http.py`

实现 `HttpChannel(BaseChannel)`，核心难点是**请求-响应关联**：

- `start()`: 启动一个 `aiohttp.web` 或 `uvicorn` 内嵌 HTTP 服务器，监听 POST 请求
- 收到请求时：创建一个 `asyncio.Future`，以 request_id 为 key 存入 `self._pending` 字典，然后调用 `self._handle_message()` 发布 InboundMessage（把 request_id 塞进 metadata），最后 `await future` 等待回复
- `send(msg: OutboundMessage)`: 从 `msg.metadata` 取出 request_id，找到对应的 Future，`future.set_result(msg.content)` 解除阻塞
- `stop()`: 关闭 HTTP 服务器

API 设计：
```
POST /api/chat
Request:  {"message": "...", "session_id": "..."}  (session_id 可选)
Response: {"reply": "...", "session_id": "..."}

GET /api/health
Response: {"status": "ok"}
```

参考 `nanobot/channels/email.py` 的结构，但用 Future 模式替代轮询模式。

### 2. 修改 `nanobot/config/schema.py`

添加配置类：
```python
class HttpConfig(BaseModel):
    """HTTP channel configuration."""
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    allow_from: list[str] = Field(default_factory=list)
```

在 `ChannelsConfig` 中添加：
```python
http: HttpConfig = Field(default_factory=HttpConfig)
```

### 3. 修改 `nanobot/channels/manager.py`

在 `_init_channels()` 中添加 HTTP channel 的注册块：
```python
if self.config.channels.http.enabled:
    try:
        from nanobot.channels.http import HttpChannel
        self.channels["http"] = HttpChannel(self.config.channels.http, self.bus)
        logger.info("HTTP channel enabled")
    except ImportError as e:
        logger.warning(f"HTTP channel not available: {e}")
```

## 关键设计点

1. **Future 关联机制**：agent 处理完消息后通过 bus 发布 OutboundMessage，ChannelManager 的 `_dispatch_outbound()` 会调用 `channel.send(msg)`。需要确保 InboundMessage 的 metadata 中携带 request_id，并且 agent 处理链路会将 metadata 透传到 OutboundMessage。**如果 metadata 不会透传，则改用 `chat_id` 作为关联 key**（每个请求生成唯一 chat_id）。

2. **超时处理**：`await asyncio.wait_for(future, timeout=120)` 防止请求永久挂起。

3. **并发安全**：`self._pending: dict[str, asyncio.Future]` 需要处理好并发请求。

## 验证

```bash
# 启用 HTTP channel
# ~/.nanobot/config.json 中添加:
# "channels": { "http": { "enabled": true, "port": 8080 } }

# 启动 gateway
nanobot gateway

# 测试
curl -X POST http://localhost:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "hello"}'
```
