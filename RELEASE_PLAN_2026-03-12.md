# Release Plan (2026-03-12)

This round includes multiple reliability changes. Based on the two latest issues, the recommended versioning is to split by function into two post releases.

## 1) Scope Mapping

### Feature A: ACP -> outbound progress aggregation + Telegram outbound batching/final dedupe

- Related issue:
  - `docs/issue/2026-03-12-telegram-outbound-batching-and-final-dedupe.md`
- Main touched files:
  - `nanobot/dispatch/acp.py`
  - `nanobot/channels/telegram.py`
  - `nanobot/channels/manager.py`
  - `tests/test_telegram_channel.py`
  - `tests/test_slash_model_agent_commands.py`

### Feature B: MessageBus inbound/outbound mixed jsonl logging + per-runtime file rotation

- Related issue:
  - `docs/issue/2026-03-12-inbound-outbound-jsonl-runtime-rotation.md`
- Main touched files:
  - `nanobot/bus/queue.py`
  - `nanobot/config/schema.py`
  - `nanobot/cli/commands.py`
  - `tests/test_message_bus_inbound_outbound_log.py`
  - `tests/test_commands.py`

## 2) Proposed Version Split

### v0.1.4.post4 (Feature A first)

Release focus: user-facing chat-streaming experience and duplicate suppression.

- ACP progress callback chain fixed and coalesced (`_ProgressCoalescer`)
- Channel-level outbound batching for Telegram (idle timeout + kind switch flush)
- Final-message dedupe with similarity threshold and "final longer => keep" protection
- Added/expanded tests for progress forwarding, coalescing, batching, and final dedupe

Rationale:

- This group directly improves end-user message experience (fewer floods, fewer duplicates).
- It should be released first because impact is visible and immediate.

### v0.1.4.post5 (Feature B second)

Release focus: observability and runtime auditability.

- Added `dispatch.inboundOutboundLogEnabled` (default off)
- Inbound + outbound unified jsonl persistence in MessageBus
- Per-startup log file rotation (`inbound_outbound-YYYYMMDD-HHMMSS-ffffff.jsonl`)
- Explicit `bus.close()` lifecycle hooks in gateway/agent exit paths
- Added/updated tests for config fallback, runtime rotation, and close-compatible command mocks

Rationale:

- This group is operational/diagnostic enhancement with lower direct UX risk.
- It is better as a follow-up release after user-facing behavior is stabilized.

## 3) One-Shot Alternative (if only one release is possible)

If release cadence only allows one package publish in this round, ship all changes together as:

- `v0.1.4.post4`

Then keep `v0.1.4.post5` reserved for the next incremental change.

## 4) Suggested Release Notes Headlines

- `v0.1.4.post4`: "Stabilize ACP/Telegram streaming with batching and final dedupe"
- `v0.1.4.post5`: "Add runtime-scoped inbound/outbound jsonl logging for audit and debugging"
