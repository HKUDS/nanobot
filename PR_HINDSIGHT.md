# Optional Hindsight integration for semantic agent memory

## Summary

This PR adds **optional** integration with [Hindsight](https://github.com/vectorize-io/hindsight) — a semantic memory service for AI agents. When enabled, nanobot uses Hindsight for **recall** (retrieve relevant memories by query), optional **reflect** (summaries from memory), and **retain** (store conversation turns). This complements the existing file-based memory (MEMORY.md, daily notes) without changing behavior when Hindsight is disabled.

## Changes

- **`nanobot/agent/hindsight_client.py`** (new): Thin async wrapper around the `hindsight-client` library. Exposes `recall()`, `reflect()`, and `retain()` with timeouts and graceful handling of missing dependency or server errors. All Hindsight calls are best-effort (errors are logged, not raised).
- **`nanobot/agent/context.py`**:
  - `ContextBuilder` accepts optional `hindsight_config`. `build_system_prompt()` accepts optional `hindsight_context` and appends a "Hindsight (learned memory)" section when non-empty.
  - `build_messages()` is now **async**. When Hindsight is enabled, it calls `recall()` (and optionally `reflect()`) for the current user message, then injects the result into the system prompt. Adds `session_key` for per-session memory banks and `_hindsight_bank_id()` helper.
- **`nanobot/agent/loop.py`**:
  - New `_retain_fire_and_forget()` helper; after saving the session, when Hindsight is enabled, schedules a non-blocking `retain()` with the user/assistant exchange.
  - `AgentLoop` accepts optional `hindsight_config` and passes it to `ContextBuilder`. All `build_messages()` call sites now `await` it.
- **`nanobot/config/schema.py`**:
  - New `HindsightConfig` with `enabled`, `base_url`, `bank_id`, `use_reflect`, `bank_id_per_session`.
  - `Config` gains `hindsight: HindsightConfig` (default: disabled).
- **`nanobot/cli/commands.py`**: Both `gateway` and `agent` commands pass `hindsight_config=config.hindsight` into `AgentLoop`.
- **`pyproject.toml`**: New optional dependency group `hindsight` with `hindsight-client>=0.4.0`. Install with `pip install nanobot-ai[hindsight]`.
- **`docs/hindsight-integration.md`** (new): English documentation for configuration, parameters, and running Hindsight with Docker/OpenRouter.

## Design notes

- **Optional dependency**: `hindsight-client` is only required when `hindsight.enabled` is true. If enabled but the package is missing, a warning is logged and recall/reflect/retain are no-ops.
- **No blocking on Hindsight**: Recall/reflect run before the LLM call (with timeouts). Retain runs in a fire-and-forget task so response latency is not affected.
- **Backward compatible**: Default config keeps Hindsight disabled; existing deployments are unchanged.
- **Session-scoped banks**: Optional `bank_id_per_session` uses `nanobot:{session_key}` as the Hindsight bank ID for per-conversation memory.

## Testing

- Config load: `hindsight` section is optional and defaults to disabled.
- With `enabled: false` (default), no HTTP calls to Hindsight and no "Hindsight (learned memory)" block in the prompt.
- With `enabled: true` and a running Hindsight server (and `pip install nanobot-ai[hindsight]`), the agent receives recall (and optionally reflect) in the system prompt and each turn is retained after the reply.

## Documentation

See `docs/hindsight-integration.md` for setup, config reference, and an example of running Hindsight in Docker with OpenRouter.
