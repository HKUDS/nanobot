# Channel Package Guide

Use this guide to add a self-contained channel package to the nanobot repository. A channel is part of nanobot when its package lives at `nanobot/channels/<channel>/`; there is no separate external channel-plugin path.

> **Breaking change:** nanobot no longer discovers the `nanobot.channels` Python entry-point group. Move an entry-point implementation into `nanobot/channels/<channel>/` with a package-owned manifest, runtime, tests, and optional WebUI contribution.

## How It Works

When `nanobot gateway` starts, nanobot scans the packages under `nanobot/channels/` and loads each dependency-free `ChannelPlugin` descriptor from `manifest.py`.

If a matching config section has `"enabled": true`, the channel is instantiated and started.

## Ownership and Sources of Truth

| Concern | Owner and source of truth |
|---------|---------------------------|
| Runtime behavior and platform SDK use | `runtime.py` and package-local helpers |
| Python package requirements | `ChannelPlugin.dependencies` in `manifest.py` |
| Writable settings fields, types, defaults, requirements, secret handling, and validation | `ChannelPlugin.setup` in `manifest.py` |
| Persisted config expansion, instance updates, and runtime naming | `ChannelPlugin.management` backed by a dependency-free module |
| Interactive setup connections and their short-lived state | `ChannelPlugin.connector` backed by package-local `connect.py` |
| Reusable local login-state detection | `ChannelPlugin.management.local_state_present` backed by package-local code |
| Discovery metadata and lazy runtime target | `PLUGIN` in `manifest.py` |
| WebUI structure, components, URLs, field keys, actions, and preset values | `webui/index.ts` or `webui/index.tsx` |
| Channel-specific user-facing copy | `webui/locales/<locale>.json` |
| Generic settings-shell copy shared by every channel | `webui/src/i18n/locales/<locale>/common.json` |

Keep one source of truth for each concern. In particular, the backend setup contract decides what may be written, the TypeScript contribution decides how those fields are presented, and locale JSON supplies the channel-specific words shown to users.

## Quick Start

We'll build a minimal webhook channel that receives messages via HTTP POST and sends replies back.

### Project Structure

```text
nanobot/channels/webhook/
├── __init__.py          # lightweight package marker; do not import the runtime
├── manifest.py          # dependency-free ChannelPlugin descriptor
├── runtime.py           # channel implementation and optional SDK imports
├── tests/               # package-local tests
└── webui/               # optional settings UI and translations
```

### 1. Create Your Channel

```python
# nanobot/channels/webhook/__init__.py
"""Webhook channel package."""
```

```python
# nanobot/channels/webhook/manifest.py
from nanobot.channels.contracts import ChannelFieldSpec, ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin


PLUGIN = ChannelPlugin(
    name="webhook",
    display_name="Webhook",
    runtime=f"{__package__}.runtime:WebhookChannel",
    dependencies=("aiohttp>=3.9.0,<4.0.0",),
    setup=ChannelSetupSpec(
        fields={
            "port": ChannelFieldSpec(kind="int", default=9000),
            "allowFrom": ChannelFieldSpec(kind="list"),
        },
    ),
)
```

```python
# nanobot/channels/webhook/runtime.py
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
        return WebhookConfig().model_dump(by_alias=True)

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
        msg.metadata — channel routing context such as message/thread ids
        msg.event    — typed runtime event for progress/status messages
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

The package directory, `PLUGIN.name`, runtime class name, and config section must all use `webhook`. Channel names use a portable ASCII package identifier: they start with a letter and contain only letters, digits, or underscores.

Declare runtime requirements directly in `ChannelPlugin.dependencies`. Do not add channel requirements to the root `pyproject.toml`: the package manifest is the source of truth used by the CLI, WebUI, and gateway startup. Keep the manifest and anything it imports free of the optional SDK itself.

### 2. Configure

```bash
nanobot plugins list      # verify the channel package appears as "webhook"
nanobot onboard           # add default config for detected channels
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

nanobot always loads the dependency-free descriptor during discovery. When the WebUI gateway starts, it installs missing requirements for enabled channels before importing their runtimes. It also installs them when a channel is enabled from the CLI or WebUI. Status, configuration, and disable operations do not need the runtime. Single-instance and multi-instance channels use the same activation rules.

### 3. Run & Test

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

## Channel Package Requirements

Every channel is a self-contained package at `nanobot/channels/<channel>/`; channel-specific runtime code, setup metadata, tests, WebUI structure, components, and translations stay under that directory.

### Package Layout

```text
nanobot/channels/<channel>/
├── __init__.py                 # package marker only; no runtime or SDK imports
├── manifest.py                 # dependency-free ChannelPlugin and ChannelSetupSpec
├── config.py                   # optional dependency-free config model and defaults
├── connect.py                  # optional interactive setup connector
├── instances.py                # optional dependency-free multi-instance management adapter
├── state.py                    # optional persisted login-state detection
├── validation.py               # optional package-owned setup checks
├── runtime.py                  # BaseChannel implementation and platform SDK imports
├── tests/                      # channel-specific Python tests
└── webui/                      # optional, compiled into the shared WebUI
    ├── index.ts or index.tsx   # structure and optional React components
    └── locales/
        ├── en.json             # canonical locale shape
        └── <locale>.json       # one file for every supported WebUI locale
```

Do not add a runtime module directly under `nanobot/channels/`, create a parallel manifest tree, or add a central per-channel UI catalog. If existing channel files move, use `git mv` so history remains traceable.

### Manifest and Runtime Boundary

`manifest.py` exports a typed `ChannelPlugin` whose `runtime` target is an absolute import target, such as `nanobot.channels.telegram.runtime:TelegramChannel`; using `f"{__package__}.runtime:TelegramChannel"` keeps it package-owned without repeating the package path. Discovery imports the manifest before it knows whether the optional platform dependency is installed, so `manifest.py` must not import `runtime.py` or any platform SDK. Import runtime symbols from `runtime.py` explicitly; `__init__.py` remains an inert package marker.

The manifest owns the channel name, display name, setup contract, management adapter, optional connector target, dependency requirements, capabilities, default activation, and optional WebUI entry path. The management adapter alone decides whether a channel is single-instance or multi-instance.

Interactive browser setup uses one small connector contract. Set `connector=f"{__package__}.connect:MyConnectStore"`; the target is loaded only when `/api/settings/channels/<name>/connect/{start,poll,cancel}` is called. The store exposes one async `handle(action, query)` method and keeps platform-specific parsing, sessions, and errors inside the channel package. The shared settings router only authenticates, dispatches, and applies a successful connection.

Use the small constructors in [`nanobot/channels/_manifest.py`](../nanobot/channels/_manifest.py) for declarative field and requirement definitions. Use [`nanobot/channels/dingtalk/manifest.py`](../nanobot/channels/dingtalk/manifest.py) as a compact single-instance example and [`nanobot/channels/feishu/`](../nanobot/channels/feishu/) as a multi-instance example.

### Package-owned WebUI

Set `webui="webui/index.ts"` or `webui="webui/index.tsx"` in the channel manifest. Candidate modules are bundled from channel packages, but the settings UI activates only the exact path returned by the backend feature payload.

The entry module exports one default `ChannelUiContribution`. Channel identity comes from the package directory, so do not repeat a `channel` field in TypeScript. Keep only structure and executable UI data in this module: presentation metadata, icons or logo URLs, docs URLs, config field keys, action payloads, preset values, aliases, and optional `Panel` or `ConnectFlow` components.

Do not put static descriptions, setup steps, labels, placeholders, help text, action labels, or preset labels in TSX. Those strings belong in the channel's locale JSON. TSX remains appropriate for dynamic rendering, interpolation, conditions, and rich component composition.

### Channel-owned i18n

Create `webui/locales/<locale>.json` for every locale code declared in [`webui/src/i18n/config.ts`](../webui/src/i18n/config.ts). Treat `en.json` as the canonical shape; every other locale must contain the same message keys and the same interpolation variables. `displayName` may be omitted when the product name should remain unchanged.

```json
{
  "description": "Use nanobot from Example chats.",
  "requirements": "Example app credentials and gateway",
  "setup": {
    "docsLabel": "Open Example setup",
    "officialLabel": "Open Example console",
    "summary": "Example needs app credentials.",
    "tryIt": "Send a test message.",
    "steps": [
      "Create an Example app.",
      "Add the credentials.",
      "Save, enable, and test the channel."
    ],
    "fields": {
      "clientId": {
        "label": "Client ID",
        "placeholder": "Example client ID",
        "help": "Copy it from the Example console."
      }
    },
    "actions": {
      "copyManifest": "Copy manifest"
    },
    "presets": {
      "default": "Default"
    }
  },
  "custom": {
    "connected": "{{name}} is connected."
  }
}
```

Field messages are keyed by the config path after `channels.<channel>.`, with remaining punctuation converted to underscores. For example, `channels.signal.dm.allowFrom` maps to `setup.fields.dm_allowFrom`. Action and preset messages use the IDs declared in the TypeScript contribution.

Custom channel components should read dynamic copy with `channelTranslator(t, "<channel>")`; keep the English fallback adjacent to the call so an incomplete translation still renders useful text. Aliases reuse the owning channel's locale namespace rather than duplicating translations.

The dependency direction is intentional:

- [`webui/src/i18n/index.ts`](../webui/src/i18n/index.ts) imports the pure JSON [`channel-plugins/locale-registry.ts`](../webui/src/channel-plugins/locale-registry.ts).
- The locale registry discovers only `nanobot/channels/*/webui/locales/*.json` and must not import the UI registry, React, or TSX.
- Settings components may consume both the UI registry and locale registry.
- Channel UI code may use shared types and generic settings components, but core settings code must not add `if (feature.name === "...")` branches for individual channels.

This separation prevents i18n initialization from eagerly loading every channel React component and keeps channel-specific ownership below the channel package.

### Tests and Definition of Done

Put channel-specific Python tests in `nanobot/channels/<channel>/tests/`. Keep only shared registry, manager, base-class, and cross-channel contract tests in `tests/channels/`. Release builds exclude package-local tests while the repository test configuration discovers both trees.

For a focused channel change, run the smallest relevant set:

```bash
uv run pytest nanobot/channels/<channel>/tests -q

cd webui
bun run test -- src/tests/channel-locale-registry.test.ts src/tests/channel-ui-registry.test.ts src/tests/channel-identity.test.ts
bun run lint
bun run build
```

Before considering the change complete, verify all of the following:

- The manifest can be discovered without importing the runtime or optional platform SDK.
- `ChannelSetupSpec` contains every writable field and rejects unknown fields.
- The TypeScript field, action, and preset IDs have matching English locale messages.
- Every supported locale matches the English key shape and interpolation variables.
- Generic settings copy remains in core `common.json`; channel-specific copy remains inside the channel package.
- User-facing WebUI changes work through the built frontend served by a real gateway, including language switching and refresh persistence.
- Markdown prose paragraphs and individual list items remain on one source line; let the renderer handle visual wrapping.

## BaseChannel API

### Required (abstract)

| Method | Description |
|--------|-------------|
| `async start()` | **Must block forever.** Connect to platform, listen for messages, call `_handle_message()` on each. If this returns, the channel is dead. |
| `async stop()` | Set `self._running = False` and clean up. Called when gateway shuts down. |
| `async send(msg: OutboundMessage)` | Deliver an outbound message to the platform. Raise when the transport does not accept it. |

#### Outbound delivery contract

A normal return from `send()` means either the visible payload was accepted by the platform transport/API, or the channel deliberately had nothing to deliver, such as an empty progress event. Do not log and return when the client is disconnected, still starting, or the platform rejects the request. Raise an exception so `ChannelManager` can apply the shared retry policy.

`send()` may run as soon as `is_running` becomes true. If a channel sets `_running` before its transport is ready, it must keep raising until delivery can be attempted safely. Small platform-specific retries are fine, but the final failure must still reach the manager.

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
| `default_config()` (classmethod) | Returns runtime-local defaults for callers that construct the class directly. Discovery and onboarding use the descriptor instead. |
| `refresh_feature_metadata(config_path, instance_id)` (classmethod) | Optionally refreshes saved display metadata after an explicit settings action. It is never called by a read-only feature GET. |
| `transcribe_audio(file_path)` | Transcribes audio via the shared top-level `transcription` config (if configured). |
| `supports_streaming` (property) | `True` when config has `"streaming": true` **and** subclass overrides `send_delta()`. |
| `is_running` | Returns `self._running`. |
| `login(force=False)` | Perform interactive login (e.g. QR code scan). Returns `True` if already authenticated or login succeeds. Override in subclasses that support interactive login. |
| `send_reasoning_delta(chat_id, delta, metadata?, *, stream_id?)` | Optional hook for streamed model reasoning/thinking content. Default is no-op. |
| `send_reasoning_end(chat_id, metadata?, *, stream_id?)` | Optional hook marking the end of a reasoning block. Default is no-op. |
| `send_reasoning(msg)` | Optional one-shot reasoning fallback. Default translates to `send_reasoning_delta()` + `send_reasoning_end()`. |

### Optional management contract

Persisted-state management belongs to `ChannelPlugin.management`, not `BaseChannel`. Keep the adapter and anything it imports free of optional platform SDKs so status, settings, and disable operations still work when the runtime cannot be imported. Runtime classes own network lifecycle, message delivery, interactive login, enable-time availability checks, and explicit runtime-only actions such as metadata refresh.

```python
from nanobot.channels.contracts import ChannelFieldSpec, ChannelSetupSpec, SetupRequirement
from nanobot.channels.plugin import ChannelPlugin

from .instances import MANAGEMENT

PLUGIN = ChannelPlugin(
    name="webhook",
    display_name="Webhook",
    runtime=f"{__package__}.channel:WebhookChannel",
    setup=ChannelSetupSpec(
        fields={
            "token": ChannelFieldSpec(kind="secret"),
            "region": ChannelFieldSpec(
                kind="enum",
                choices=frozenset({"us", "eu"}),
                default="us",
            ),
        },
        required=(SetupRequirement.field("token"),),
    ),
    management=MANAGEMENT,
)
```

`instances.py` then exports the dependency-free adapter assembled from channel-owned callbacks:

```python
from typing import Any

from nanobot.channels.contracts import ChannelInstanceSpec, ChannelManagementSpec

from .config import default_config


def instance_specs(section: Any, *, enabled_only: bool = True) -> list[ChannelInstanceSpec]:
    ...  # Expand the persisted channel-owned envelope.


def update_instance_config(
    section: Any,
    values: dict[str, Any],
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    ...  # Update one instance without discarding sibling data.


MANAGEMENT = ChannelManagementSpec(
    multi_instance=True,
    default_config=default_config,
    instance_specs=instance_specs,
    update_instance_config=update_instance_config,
)
```

`ChannelSetupSpec` is authoritative for writable field names, field types, choices, defaults, required setup, secret redaction, and optional backend validation. The settings API rejects fields outside this contract. A validator receives `(values, context)`; use `context.allow_local_service_access` for host network policy instead of loading global config from the channel package.

The dependency-free `MANAGEMENT` value is a `ChannelManagementSpec`. Multi-instance plugins provide `instance_specs(section, enabled_only=True)` and `update_instance_config(section, values, instance_id=...)`; they may also provide `default_config`, `runtime_name`, presentation-only `feature_instances`, and `local_state_present`. Single-instance plugins normally derive onboarding defaults from `ChannelSetupSpec`; use `default_config` only when persisted defaults include fields that are not part of generic setup.

Multi-instance adapters return `ChannelInstanceSpec` objects and preserve their persisted envelope when updating one instance. Their descriptor sets `ChannelManagementSpec(multi_instance=True)`. The shared contract enforces these invariants:

- every `instance_id` is non-empty and unique;
- the management adapter's `runtime_name(channel_name, instance_id)` is the single source of routing names, and every derived name is unique and is either the channel name or starts with `<channel-name>.`;
- runtime names cannot overwrite a runtime already owned by another channel;
- settings instance summaries are generated from `instance_specs()` and `ChannelPlugin.setup`. They contain the authoritative `enabled` and `configured` state plus secret-safe `config_values` and `configured_fields` for the generic instance editor;
- the management adapter's `feature_instances()` may return `None` or presentation overrides containing an `id` plus `name`, `display_name`, or `avatar_url`. It cannot override runtime state or the configuration snapshot.

`ChannelInstanceSpec` contains only `instance_id` and the instance config; nanobot derives its runtime name through the adapter. Single-instance plugins keep ownership of their entire config, including a field named `instances`. Only plugins whose management spec sets `multi_instance=True` opt into instance expansion.

The package/config section name owns every runtime produced from that section. Class inheritance does not transfer runtime ownership to another package.

Return a concrete iterable or generator from the adapter's `instance_specs()`; nanobot materializes and validates it before constructing any runtime. Raise an exception for malformed persisted data rather than silently changing instance identity. Keep network-backed metadata refresh behind the runtime's `refresh_feature_metadata()` so feature GET requests remain dependency-free and read-only.

For package layout, WebUI ownership, and localization rules, see [Channel Package Requirements](#channel-package-requirements).

### Optional (streaming)

| Method | Description |
|--------|-------------|
| `async send_delta(chat_id, delta, metadata?, *, stream_id?, stream_end=False, resuming=False)` | Override to receive streaming chunks. See [Streaming Support](#streaming-support) for details. |

### Message Types

```python
@dataclass
class OutboundMessage:
    channel: str        # your channel name
    chat_id: str        # recipient (same value you passed to _handle_message)
    content: str        # markdown text — convert to platform format as needed
    media: list[str]    # local file paths to attach (images, audio, docs)
    metadata: dict      # channel routing context, e.g. "message_id" for threading
    event: object | None # typed runtime/UI event; usually inspect with isinstance()
```

Runtime/UI semantics live on `msg.event`. Plugin-authored outbound messages should use typed events instead of legacy metadata flags such as `_progress`, `_stream_delta`, `_stream_end`, `_reasoning_delta`, `_turn_end`, or `_goal_status`. nanobot still accepts those old flags as a compatibility bridge for existing in-process extensions, but new plugin code should not add fresh dependencies on them.

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
async def send_delta(
    self,
    chat_id: str,
    delta: str,
    metadata: dict[str, Any] | None = None,
    *,
    stream_id: str | None = None,
    stream_end: bool = False,
    resuming: bool = False,
) -> None:
    buffer_key = stream_id or chat_id
    if stream_end:
        # Streaming finished — do final formatting, cleanup, etc.
        return

    # Regular delta — append text, update the message on screen
    # delta contains a small chunk of text (a few tokens)
```

Streaming state is passed through keyword-only arguments, not `_stream_delta` or `_stream_end` metadata flags. Use `stream_id` to key any per-stream buffers; fall back to `chat_id` when it is missing.

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

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
        stream_end: bool = False,
        resuming: bool = False,
    ) -> None:
        buffer_key = stream_id or chat_id
        if stream_end:
            text = self._buffers.pop(buffer_key, "")
            # Final delivery — format and send the complete message
            await self._deliver(chat_id, text, final=True)
            return

        self._buffers.setdefault(buffer_key, "")
        self._buffers[buffer_key] += delta
        # Incremental update — push partial text to the client
        await self._deliver(chat_id, self._buffers[buffer_key], final=False)

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
| `async send_delta(chat_id, delta, metadata?, *, stream_id?, stream_end=False, resuming=False)` | Override to handle streaming chunks. No-op by default. |
| `supports_streaming` (property) | Returns `True` when config has `streaming: true` **and** subclass overrides `send_delta`. |

## Progress, Tool Hints, and Reasoning

Besides normal assistant text, nanobot can emit low-emphasis trace blocks. These are intended for UI affordances like status rows, collapsible "used tools" groups, or reasoning/thinking blocks. Platforms that do not have a good place for them can ignore them safely.

### Progress and Tool Hints

Progress and tool hints arrive through the normal `send(msg)` path. Check `msg.event` before rendering:

```python
from nanobot.bus.outbound_events import ProgressEvent

async def send(self, msg: OutboundMessage) -> None:
    event = msg.event

    if isinstance(event, ProgressEvent) and event.tool_hint:
        # A short tool breadcrumb, e.g. read_file("config.json")
        await self._send_trace(msg.chat_id, msg.content, kind="tool")
        return

    if isinstance(event, ProgressEvent):
        # Generic non-final status, e.g. "Thinking..." or "Running command..."
        await self._send_trace(msg.chat_id, msg.content, kind="progress")
        return

    await self._send_message(msg.chat_id, msg.content, media=msg.media)
```

Tool hints are off by default for most channels. Users can enable them globally or per channel:

```json
{
  "channels": {
    "sendToolHints": true,
    "webhook": {
      "enabled": true,
      "sendToolHints": true
    }
  }
}
```

### Reasoning Blocks

Reasoning is delivered through dedicated optional hooks, not `send()`. Override `send_reasoning_delta()` and `send_reasoning_end()` if your platform can show model reasoning as a subdued/collapsible block. The default implementation is a no-op, so unsupported channels simply drop reasoning content.

```python
class WebhookChannel(BaseChannel):
    name = "webhook"
    display_name = "Webhook"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig(**config)
        super().__init__(config, bus)
        self._reasoning_buffers: dict[str, str] = {}

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        buffer_key = stream_id or chat_id
        self._reasoning_buffers[buffer_key] = self._reasoning_buffers.get(buffer_key, "") + delta
        await self._update_reasoning_block(chat_id, self._reasoning_buffers[buffer_key], final=False)

    async def send_reasoning_end(
        self,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        buffer_key = stream_id or chat_id
        text = self._reasoning_buffers.pop(buffer_key, "")
        if text:
            await self._update_reasoning_block(chat_id, text, final=True)
```

**Reasoning arguments:**

| Argument | Meaning |
|------|---------|
| `delta` | A reasoning/thinking chunk for `send_reasoning_delta()`. |
| `stream_id` | Stable id for this assistant turn/segment. Use it to key buffers instead of only `chat_id`. |
| `send_reasoning_end()` | The current reasoning block is complete. |

Reasoning visibility is controlled by `showReasoning` globally or per channel:

```json
{
  "channels": {
    "showReasoning": true,
    "webhook": {
      "enabled": true,
      "showReasoning": true
    }
  }
}
```

Recommended rendering:

- Render tool hints and progress as trace/status UI, not as normal assistant replies.
- Render reasoning with lower visual emphasis and collapse it after completion when the platform supports that.
- Keep reasoning separate from final answer text. A final answer still arrives through `send()` or `send_delta()`.

## Config

### Why Pydantic model is required

`BaseChannel.is_allowed()` reads the permission list via `getattr(self.config, "allow_from", [])`. This works for Pydantic models where `allow_from` is a real Python attribute, but **fails silently for plain `dict`** — `dict` has no `allow_from` attribute, so `getattr` always returns the default `[]`, causing all messages to be denied.

Channel runtimes use Pydantic config models by subclassing `Base` from `nanobot.config.schema`.

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

`nanobot onboard` reads the descriptor without importing the runtime. Put writable defaults in `ChannelSetupSpec`:

```python
setup=ChannelSetupSpec(
    fields={
        "port": ChannelFieldSpec(kind="int", default=9000),
        "allowFrom": ChannelFieldSpec(kind="list"),
    },
)
```

String and secret fields default to `""`, list fields to `[]`, and boolean fields to `false` when no explicit default is declared. For non-setup or multi-instance persisted defaults, provide `ChannelManagementSpec.default_config` from a dependency-free package-local module.

## Naming Convention

| What | Format | Example |
|------|--------|---------|
| Package directory | `nanobot/channels/{name}` | `nanobot/channels/webhook` |
| Manifest name | `{name}` | `webhook` |
| Config section | `channels.{name}` | `channels.webhook` |
| Runtime import | `nanobot.channels.{name}.runtime` | `nanobot.channels.webhook.runtime` |

## Local Development

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python -m pip install -e .
nanobot plugins list    # should show the package as "webhook"
nanobot plugins enable webhook
nanobot gateway         # test end-to-end
```

## Verify

```bash
$ nanobot plugins list

  Name       Type      Enabled
  discord    channel   no
  telegram   channel   yes
  webhook    channel   yes
```
