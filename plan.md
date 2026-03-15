# Refactor Discord Channel to `discord.py` With Minimal Blast Radius

## Summary

Replace the internals of `nanobot/channels/discord.py` from the current custom Gateway + raw REST client to `discord.py` so the Discord adapter relies on a maintained library instead of bespoke protocol handling. The intent is to reduce transport-specific maintenance risk and simplify future Discord compatibility work while preserving the existing channel boundary, config shape, bus contract, and user-facing Discord behavior.

This remains a transport swap only. The Discord adapter should fail cleanly if the `discord.py` client cannot be constructed or started, and it should not carry a custom HTTP fallback path.

## Key Changes

- Keep `DiscordChannel` as the built-in `discord` adapter and keep its public contract:
  - `start()`, `stop()`, and `send()` signatures unchanged.
  - Inbound bus messages still use `channel="discord"`, `chat_id=channel_id`, and metadata containing at least `message_id`, `guild_id`, and `reply_to`.
  - Outbound routing still uses `OutboundMessage(channel="discord", chat_id=..., reply_to=..., media=...)`.
- Replace custom transport state with `discord.py` primitives:
  - Remove manual websocket heartbeat/identify/reconnect code.
  - Remove the raw `httpx` Discord transport path used for message sends.
  - Instantiate and own a `discord.Client` subclass or thin wrapper inside `DiscordChannel`.
  - Run it with async lifecycle (`await client.start(token)` / `await client.close()`), not `client.run()`.
- Handle client construction and startup errors explicitly:
  - Wrap client creation in a guarded initialization path.
  - If intents are invalid, the token is missing, or `discord.py` raises during client setup/startup, log a clear error and leave the channel non-running.
  - `send()` should no-op with a warning when the client was never initialized or is no longer ready, rather than trying a non-`discord.py` fallback.
- Preserve current config compatibility, with one simplification:
  - Keep `enabled`, `token`, `allow_from`, `intents`, and `group_policy`.
  - Keep `gateway_url` accepted for backward compatibility but deprecated/ignored, since `discord.py` manages the gateway internally.
  - Continue treating `intents` as the source of truth by converting the existing integer bitmask into a `discord.Intents` object internally.
- Keep inbound behavior stable:
  - Ignore bot-authored messages.
  - Continue DMs when `allow_from` passes.
  - Continue guild-channel policy: `"mention"` requires bot mention, `"open"` accepts all.
  - Download inbound attachments to `get_media_dir("discord")`, preserve the `[attachment: ...]` content markers, and pass file paths via `media`.
  - Start typing when a qualifying inbound message is handed off to the bus, and stop typing when the outbound send completes.
- Keep outbound behavior stable without extra transport branches:
  - Resolve the destination via the `discord.py` client only.
  - Use cached channel objects where available; if a channel cannot be resolved through the client, log and drop the outbound message.
  - Send long responses in chunks using existing `split_message`.
  - Upload local files using `discord.File`.
  - Preserve reply behavior when `reply_to` is present; disable pinging the replied user to match current behavior.
  - If attachments fail, continue the current fallback pattern of surfacing failed attachment names in text.
- Limit surface-area changes outside the Discord adapter:
  - `ChannelManager`, bus event types, agent loop, message tool, and config schema should not require behavior changes.
  - `pyproject.toml` adds `discord.py` as the Discord transport dependency.
  - Do not remove `websockets` globally in this pass because `whatsapp.py` still uses it.

## Public Interfaces / Compatibility

- No intentional changes to the bus schemas or channel registry.
- No intentional changes to `channels.discord` config keys consumed by users.
- `gateway_url` becomes compatibility-only:
  - Existing configs still load.
  - New implementation ignores the field.
  - README should stop presenting it as meaningful configuration.
- Runtime prerequisite remains the same from the user’s perspective:
  - Bot token required.
  - Message content intent must be enabled in the Discord developer portal for content-based handling.

## Test Plan

- Add a dedicated Discord channel test module with fakes/mocks around the `discord.py` client boundary.
- Cover startup and lifecycle:
  - missing token logs and does not start
  - client construction failure logs and leaves the channel non-running
  - startup failure from `client.start(...)` logs and exits cleanly
  - `stop()` is safe when initialization only partially succeeded
- Cover inbound filtering:
  - bot messages ignored
  - DM message accepted when sender is allowlisted
  - guild message ignored in `"mention"` mode without a mention
  - guild message accepted in `"mention"` mode with a mention
  - guild message accepted in `"open"` mode
- Cover inbound payload shaping:
  - metadata includes `message_id`, `guild_id`, and `reply_to`
  - attachments are downloaded and surfaced in both `content` markers and `media`
  - oversized or failed attachments degrade to text markers instead of crashing
- Cover outbound behavior:
  - unresolved channel logs and skips send
  - text is chunked at Discord limits
  - replies use the provided `reply_to`
  - file uploads are attempted for each local media path
  - typing task is stopped after send, including failure paths
  - `send()` warns and returns when the client was never created or is not ready
- Run the existing channel-related suite that could catch blast-radius regressions:
  - base channel tests
  - message tool tests
  - any shared channel manager / command startup tests that exercise channel discovery and startup

## Assumptions

- Chosen scope: transport-only swap under the existing config and bus contract.
- No custom HTTP fallback should exist in the new adapter.
- Backward compatibility is preferred over config cleanup; deprecation of `gateway_url` is documentation-level only for now.
- Session semantics stay as they are today: Discord continues to key sessions by `discord:{channel_id}` rather than introducing thread-specific session scoping in this pass.
