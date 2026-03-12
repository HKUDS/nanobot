# ADR-007: Channel Adapter Model

## Status

Accepted

## Date

2026-03-12

## Context

Nanobot supports 9 chat platform channels (Telegram, Discord, Slack, WhatsApp,
Email, DingTalk, Feishu, Mochat, QQ).  Each adapter follows `BaseChannel` but
has significant protocol-specific complexity (WebSocket reconnection, OAuth,
message editing, reaction handling).

The `channels/` package is the largest non-agent area of the codebase.  It must
remain strictly decoupled from agent internals to allow platform adapters to be
developed and tested independently.

## Decision

1. **`BaseChannel` ABC contract** remains the public interface:
   - `async start()` — connect to platform and begin receiving messages.
   - `async stop()` — graceful disconnect.
   - `async send(OutboundMessage)` — deliver a message to the platform.
   - Channels publish inbound messages via `MessageBus.publish_inbound()`.

2. **Module boundaries** (enforced by `scripts/check_imports.py`):
   - `channels/*` must **never** import from `agent/loop`, `agent/tools/*`,
     or `agent/memory/*`.
   - `channels/*` must **never** import from `providers/*`.
   - Communication is exclusively via `bus/events.py` message types.

3. **ChannelManager** (`channels/manager.py`) is the sole orchestration point:
   - Instantiates channels based on `ChannelsConfig`.
   - Routes outbound messages to the correct channel.
   - Manages lifecycle (start/stop all channels).

4. **Channel configuration** lives in `nanobot/config/schema.py` as nested
   Pydantic models under `ChannelsConfig`.  Each channel has an `enabled: bool`
   gate and platform-specific settings.

5. **New channels** are added by:
   1. Creating `nanobot/channels/<platform>.py` implementing `BaseChannel`.
   2. Adding a config model (`<Platform>Config`) in `schema.py`.
   3. Adding the config field to `ChannelsConfig`.
   4. Registering in `ChannelManager._create_channels()`.
   5. No changes to agent/, providers/, or bus/ required.

## Consequences

### Positive

- Clean separation: channel bugs cannot corrupt agent state.
- New channels require zero changes outside `channels/` and `config/`.
- Import boundary enforcement prevents accidental coupling.

### Negative

- Rich platform features (reactions, threads, message editing) require
  metadata conventions in `OutboundMessage` rather than typed APIs.
- Testing channels requires mocking platform SDKs.

### Neutral

- `MessageBus` remains the sole bridge between channels and agent.
- Channel-specific streaming (progressive message updates) is controlled
  by `channels.send_progress` config flag.
