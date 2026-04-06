# Channel Plugin Guide

Build a custom nanobot channel in three steps: subclass, package, install.

> **Note:** We recommend developing channel plugins against a source checkout of nanobot (`pip install -e .`) rather than a PyPI release, so you always have access to the latest base-channel features and APIs.

## How It Works

nanobot discovers channel plugins via Python [entry points](https://packaging.python.org/en/latest/specifications/entry-points/). When `nanobot gateway` starts, it scans:

1. Built-in channels in `nanobot/channels/`
2. External packages registered under the `nanobot.channels` entry point group

If a matching config section has `"enabled": true`, the channel is instantiated and started.

## Quick Start

We'll build a minimal webhook channel that receives messages via HTTP POST and sends replies back.

### Project Structure

```
nanobot-channel-webhook/
├── nanobot_channel_webhook/
│   ├── __init__.py          # re-export WebhookChannel
│   └── channel.py           # channel implementation
└── pyproject.toml
```

### 1. Create Your Channel

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

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Base


class WebhookConfig(Base):
    """Webhook channel configuration."""
    enabled: bool = False
    port: int = 9000
    allow_from: list[str] = Field(default_factory=list)


class WebhookChannel(BaseChannel):
    name = "webhook"
    display_name = "Webhook"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
        super().__init__(config, bus)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {"enabled": False, "port": 9000, "allowFrom": []}

    async def start(self) -> None:
        """Start an HTTP server that listens for incoming messages.

        IMPORTANT: start() must block forever (or until stop() is called).
        If it returns, the channel is considered dead.
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

        # Block until stopped
        while self._running:
            await asyncio.sleep(1)

        await runner.cleanup()

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Deliver an outbound message.

        msg.content  — markdown text (convert to platform format as needed)
        msg.media    — list of local file paths to attach
        msg.chat_id  — the recipient (same chat_id you passed to _handle_message)
        msg.metadata — may contain "_progress": True for streaming chunks
        """
        logger.info("[webhook] -> {}: {}", msg.chat_id, msg.content[:80])
        # In a real plugin: POST to a callback URL, send via SDK, etc.

    async def _on_request(self, request: web.Request) -> web.Response:
        """Handle an incoming HTTP POST."""
        body = await request.json()
        sender = body.get("sender", "unknown")
        chat_id = body.get("chat_id", sender)
        text = body.get("text", "")
        media = body.get("media", [])       # list of URLs

        # This is the key call: validates allowFrom, then puts the
        # message onto the bus for the agent to process.
        await self._handle_message(
            sender_id=sender,
            chat_id=chat_id,
            content=text,
            media=media,
        )

        return web.json_response({"ok": True})
```

### 2. Register the Entry Point

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

The key (`webhook`) becomes the config section name. The value points to your `BaseChannel` subclass.

### 3. Install & Configure

```bash
pip install -e .
nanobot plugins list      # verify "Webhook" shows as "plugin"
nanobot onboard           # auto-adds default config for detected plugins
```

Edit `~/.nanobot/config.json`:

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

### 4. Run & Test

```bash
nanobot gateway
```

In another terminal:

```bash
curl -X POST http://localhost:9000/message \
  -H "Content-Type: application/json" \
  -d '{"sender": "user1", "chat_id": "user1", "text": "Hello!"}'
```

The agent receives the message and processes it. Replies arrive in your `send()` method.

## BaseChannel API

### Required (abstract)

| Method | Description |
|--------|-------------|
| `async start()` | **Must block forever.** Connect to platform, listen for messages, call `_handle_message()` on each. If this returns, the channel is dead. |
| `async stop()` | Set `self._running = False` and clean up. Called when gateway shuts down. |
| `async send(msg: OutboundMessage)` | Deliver an outbound message to the platform. |

### Interactive Login

If your channel requires interactive authentication (e.g. QR code scan), override `login(force=False)`:

```python
async def login(self, force: bool = False) -> bool:
    """
    Perform channel-specific interactive login.

    Args:
        force: If True, ignore existing credentials and re-authenticate.

    Returns True if already authenticated or login succeeds.
    """
    # For QR-code-based login:
    # 1. If force, clear saved credentials
    # 2. Check if already authenticated (load from disk/state)
    # 3. If not, show QR code and poll for confirmation
    # 4. Save token on success
```

Channels that don't need interactive login (e.g. Telegram with bot token, Discord with bot token) inherit the default `login()` which just returns `True`.

Users trigger interactive login via:
```bash
nanobot channels login <channel_name>
nanobot channels login <channel_name> --force  # re-authenticate
```

### Provided by Base

| Method / Property | Description |
|-------------------|-------------|
| `_handle_message(sender_id, chat_id, content, media?, metadata?, session_key?)` | **Call this when you receive a message.** Checks `is_allowed()`, then publishes to the bus. Automatically sets `_wants_stream` if `supports_streaming` is true. |
| `is_allowed(sender_id)` | Checks against `config.allow_from`; `"*"` allows all, `[]` denies all. |
| `default_config()` (classmethod) | Returns default config dict for `nanobot onboard`. Override to declare your fields. |
| `transcribe_audio(file_path)` | Transcribes audio via Groq Whisper (if configured). |
| `supports_streaming` (property) | `True` when config has `"streaming": true` **and** subclass overrides `send_delta()`. |
| `is_running` | Returns `self._running`. |
| `login(force=False)` | Perform interactive login (e.g. QR code scan). Returns `True` if already authenticated or login succeeds. Override in subclasses that support interactive login. |

### Optional (streaming)

| Method | Description |
|--------|-------------|
| `async send_delta(chat_id, delta, metadata?)` | Override to receive streaming chunks. See [Streaming Support](#streaming-support) for details. |

### Message Types

```python
@dataclass
class OutboundMessage:
    channel: str        # your channel name
    chat_id: str        # recipient (same value you passed to _handle_message)
    content: str        # markdown text — convert to platform format as needed
    media: list[str]    # local file paths to attach (images, audio, docs)
    metadata: dict      # may contain: "_progress" (bool) for streaming chunks,
                        #              "message_id" for reply threading
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

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
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

### Why Pydantic model is required

`BaseChannel.is_allowed()` and the `supports_streaming` property access config fields via `getattr()` (e.g. `getattr(self.config, "allow_from", [])`). This works for Pydantic models where `allow_from` is a real Python attribute, but **fails silently for plain `dict`** — `dict` has no `allow_from` attribute, so `getattr` always returns the default `[]`, causing all messages to be denied.

Built-in channels use Pydantic config models (subclassing `Base` from `nanobot.config.schema`). Plugin channels **must do the same**.

### Pattern

1. Define a Pydantic model inheriting from `nanobot.config.schema.Base`:

```python
from pydantic import Field
from nanobot.config.schema import Base

class WebhookConfig(Base):
    """Webhook channel configuration."""
    enabled: bool = False
    port: int = 9000
    allow_from: list[str] = Field(default_factory=list)
```

`Base` is configured with `alias_generator=to_camel` and `populate_by_name=True`, so JSON keys like `"allowFrom"` and `"allow_from"` are both accepted.

2. Convert `dict` → model in `__init__`:

```python
from typing import Any
from nanobot.bus.queue import MessageBus

class WebhookChannel(BaseChannel):
    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
        super().__init__(config, bus)
```

3. Access config as attributes (not `.get()`):

```python
async def start(self) -> None:
    port = self.config.port
    token = self.config.token
```

`allowFrom` is handled automatically by `_handle_message()` — you don't need to check it yourself.

Override `default_config()` so `nanobot onboard` auto-populates `config.json`:

```python
@classmethod
def default_config(cls) -> dict[str, Any]:
    return {"enabled": False, "port": 9000, "allowFrom": []}
```

> **Note:** `default_config()` still returns a plain `dict` (not a Pydantic model) because it's used to serialize into `config.json`. Use camelCase keys (`allowFrom`) to match the JSON convention.

If not overridden, the base class returns `{"enabled": false}`.

## Naming Convention

| What | Format | Example |
|------|--------|---------|
| PyPI package | `nanobot-channel-{name}` | `nanobot-channel-webhook` |
| Entry point key | `{name}` | `webhook` |
| Config section | `channels.{name}` | `channels.webhook` |
| Python package | `nanobot_channel_{name}` | `nanobot_channel_webhook` |

## Local Development

```bash
git clone https://github.com/you/nanobot-channel-webhook
cd nanobot-channel-webhook
pip install -e .
nanobot plugins list    # should show "Webhook" as "plugin"
nanobot gateway         # test end-to-end
```

## Verify

```bash
$ nanobot plugins list

  Name       Source    Enabled
  telegram   builtin  yes
  discord    builtin  no
  webhook    plugin   yes
```
