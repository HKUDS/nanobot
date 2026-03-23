# 频道插件指南

通过三步创建一个自定义的 nanobot 频道：继承、打包、安装。

## 工作原理

nanobot 通过 Python 的 [entry points](https://packaging.python.org/en/latest/specifications/entry-points/) 发现频道插件。当 `nanobot gateway` 启动时，它会扫描：

1. `nanobot/channels/` 里的内置频道
2. 注册到 `nanobot.channels` 入口点组的外部包

如果某个配置段的 `"enabled": true`，对应频道就会被实例化并启动。

## 快速开始

下面我们实现一个最小的 webhook 频道，它通过 HTTP POST 接收消息，并把回复发回去。

### 项目结构

```text
nanobot-channel-webhook/
├── nanobot_channel_webhook/
│   ├── __init__.py          # 重新导出 WebhookChannel
│   └── channel.py           # 频道实现
└── pyproject.toml
```

### 1. 创建你的频道

```python
# nanobot_channel_webhook/__init__.py
from nanobot_channel_webhook.channel import WebhookChannel

__all__ = ["WebhookChannel"]
```

```python
# nanobot_channel_webhook/channel.py
import asyncio
from typing import Any

from aiohttp import web
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage


class WebhookChannel(BaseChannel):
    name = "webhook"
    display_name = "Webhook"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
        super().__init__(config, bus)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebhookConfig().model_dump(by_alias=True)

    async def start(self) -> None:
        """启动一个监听传入消息的 HTTP 服务。

        重要：start() 必须一直阻塞，直到 stop() 被调用。
        如果它直接返回，这个频道就会被认为已停止。
        """
        self._running = True
        port = self.config.port

        app = web.Application()
        app.router.add_post("/message", self._on_request)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("Webhook listening on :{}", port)

        # 持续阻塞，直到被停止
        while self._running:
            await asyncio.sleep(1)

        await runner.cleanup()

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """发送一条输出消息。

        msg.content  - markdown 文本（需要时转换成平台格式）
        msg.media    - 要附加的本地文件路径列表
        msg.chat_id  - 接收者（与调用 _handle_message 时传入的 chat_id 一致）
        msg.metadata - 可能包含 "_progress": True，用于流式分片
        """
        logger.info("[webhook] -> {}: {}", msg.chat_id, msg.content[:80])
        # 真实插件里：可以 POST 到回调地址、调用 SDK 等

    async def _on_request(self, request: web.Request) -> web.Response:
        """处理传入的 HTTP POST 请求。"""
        body = await request.json()
        sender = body.get("sender", "unknown")
        chat_id = body.get("chat_id", sender)
        text = body.get("text", "")
        media = body.get("media", [])  # URL 列表

        # 这是关键调用：它会校验 allowFrom，然后把消息放进 bus，
        # 交给 agent 去处理。
        await self._handle_message(
            sender_id=sender,
            chat_id=chat_id,
            content=text,
            media=media,
        )

        return web.json_response({"ok": True})
```

### 2. 注册入口点

```toml
# pyproject.toml
[project]
name = "nanobot-channel-webhook"
version = "0.1.0"
dependencies = ["nanobot", "aiohttp"]

[project.entry-points."nanobot.channels"]
webhook = "nanobot_channel_webhook:WebhookChannel"

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends._legacy:_Backend"
```

上面的键名（`webhook`）会成为配置段名称。值则指向你的 `BaseChannel` 子类。

### 3. 安装与配置

```bash
pip install -e .
nanobot plugins list      # 验证是否显示为 "plugin"
nanobot onboard           # 自动为已发现的插件补上默认配置
```

编辑 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "webhook": {
      "enabled": true,
      "port": 9000,
      "allowFrom": ["*"]
    }
  }
}
```

### 4. 运行与测试

```bash
nanobot gateway
```

在另一个终端中：

```bash
curl -X POST http://localhost:9000/message \
  -H "Content-Type: application/json" \
  -d '{"sender": "user1", "chat_id": "user1", "text": "Hello!"}'
```

agent 会收到这条消息并进行处理。回复会在你的 `send()` 方法里送达。

## BaseChannel API

### 必需方法（抽象）

| 方法 | 说明 |
|------|------|
| `async start()` | **必须一直阻塞。** 连接平台、监听消息，并在每条消息到达时调用 `_handle_message()`。如果它返回了，就说明这个频道已经结束。 |
| `async stop()` | 设置 `self._running = False` 并清理资源。gateway 关闭时会调用。 |
| `async send(msg: OutboundMessage)` | 把一条输出消息发送到平台。 |

### BaseChannel 已提供

| Method / Property | Description |
|-------------------|-------------|
| `_handle_message(sender_id, chat_id, content, media?, metadata?, session_key?)` | **Call this when you receive a message.** Checks `is_allowed()`, then publishes to the bus. Automatically sets `_wants_stream` if `supports_streaming` is true. |
| `is_allowed(sender_id)` | Checks against `config["allowFrom"]`; `"*"` allows all, `[]` denies all. |
| `default_config()` (classmethod) | Returns default config dict for `nanobot onboard`. Override to declare your fields. |
| `transcribe_audio(file_path)` | Transcribes audio via Groq Whisper (if configured). |
| `supports_streaming` (property) | `True` when config has `"streaming": true` **and** subclass overrides `send_delta()`. |
| `is_running` | Returns `self._running`. |
| `login(force=False)` | Perform interactive login (e.g. QR code scan). Returns `True` if already authenticated or login succeeds. Override in subclasses that support interactive login. |

### 消息类型

```python
@dataclass
class OutboundMessage:
    channel: str        # 你的频道名
    chat_id: str        # 接收者（与传给 _handle_message 的值一致）
    content: str        # markdown 文本，必要时转换为平台格式
    media: list[str]    # 要附加的本地文件路径（图片、音频、文档）
    metadata: dict      # 可能包含："_progress"（bool，流式分片）、"message_id"（回复线程）
```

## Streaming Support

Channels can opt into real-time streaming — the agent sends content token-by-token instead of one final message. This is entirely optional; channels work fine without it.

### How It Works

When **both** conditions are met, the agent streams content through your channel:

1. Config has `"streaming": true`
2. Your subclass overrides `send_delta()`

If either is missing, the agent falls back to the normal one-shot `send()` path.

### Implementing `send_delta`

Override `send_delta` to handle two types of calls:

```python
async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
    meta = metadata or {}

    if meta.get("_stream_end"):
        # Streaming finished — do final formatting, cleanup, etc.
        return

    # Regular delta — append text, update the message on screen
    # delta contains a small chunk of text (a few tokens)
```

**Metadata flags:**

| Flag | Meaning |
|------|---------|
| `_stream_delta: True` | A content chunk (delta contains the new text) |
| `_stream_end: True` | Streaming finished (delta is empty) |
| `_resuming: True` | More streaming rounds coming (e.g. tool call then another response) |

### Example: Webhook with Streaming

```python
class WebhookChannel(BaseChannel):
    name = "webhook"
    display_name = "Webhook"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._buffers: dict[str, str] = {}

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata or {}
        if meta.get("_stream_end"):
            text = self._buffers.pop(chat_id, "")
            # Final delivery — format and send the complete message
            await self._deliver(chat_id, text, final=True)
            return

        self._buffers.setdefault(chat_id, "")
        self._buffers[chat_id] += delta
        # Incremental update — push partial text to the client
        await self._deliver(chat_id, self._buffers[chat_id], final=False)

    async def send(self, msg: OutboundMessage) -> None:
        # Non-streaming path — unchanged
        await self._deliver(msg.chat_id, msg.content, final=True)
```

### Config

Enable streaming per channel:

```json
{
  "channels": {
    "webhook": {
      "enabled": true,
      "streaming": true,
      "allowFrom": ["*"]
    }
  }
}
```

When `streaming` is `false` (default) or omitted, only `send()` is called — no streaming overhead.

### BaseChannel Streaming API

| Method / Property | Description |
|-------------------|-------------|
| `async send_delta(chat_id, delta, metadata?)` | Override to handle streaming chunks. No-op by default. |
| `supports_streaming` (property) | Returns `True` when config has `streaming: true` **and** subclass overrides `send_delta`. |

## Config

Your channel receives config as a plain `dict`. Access fields with `.get()`:

```python
async def start(self) -> None:
    port = self.config.port
    token = self.config.token
```

`allowFrom` 会被 `_handle_message()` 自动处理，你不需要自己检查。

重写 `default_config()`，让 `nanobot onboard` 自动填充 `config.json`：

```python
@classmethod
def default_config(cls) -> dict[str, Any]:
    return WebhookConfig().model_dump(by_alias=True)
```

> **Note:** `default_config()` returns a plain `dict` (not a Pydantic model) because it's used to serialize into `config.json`. The recommended way is to instantiate your config model and call `model_dump(by_alias=True)` — this automatically uses camelCase keys (`allowFrom`) and keeps defaults in a single source of truth.

如果不重写，基类默认返回 `{"enabled": false}`。

## 命名约定

| 对象 | 格式 | 示例 |
|------|------|------|
| PyPI 包名 | `nanobot-channel-{name}` | `nanobot-channel-webhook` |
| 入口点 key | `{name}` | `webhook` |
| 配置段 | `channels.{name}` | `channels.webhook` |
| Python 包名 | `nanobot_channel_{name}` | `nanobot_channel_webhook` |

## 本地开发

```bash
git clone https://github.com/you/nanobot-channel-webhook
cd nanobot-channel-webhook
pip install -e .  
nanobot plugins list    # 应该能看到 "Webhook" 显示为 "plugin"
nanobot gateway         # 端到端测试
```

## 验证

```bash
$ nanobot plugins list

  Name       Source    Enabled
  telegram   builtin  yes
  discord    builtin  no
  webhook    plugin   yes
```
