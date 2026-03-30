# ADR-006: Configuration Strategy

## Status

Accepted

## Date

2026-03-12

## Context

Nanobot's configuration was originally loaded from a single JSON file
(`~/.nanobot/config.json`).  Over time, ad-hoc `os.getenv("NANOBOT_*")` calls
accumulated in multiple modules (litellm_provider.py, memory/store.py,
memory/mem0_adapter.py) — roughly 20 direct reads — creating a fragmented
configuration surface.

Operators deploying via Docker or CI need environment-variable-based
configuration without editing JSON files.  Developers need sane defaults
that "just work" locally.

## Decision

1. **Three-tier configuration cascade** (highest priority wins):

   | Tier | Source | Use case |
   |------|--------|----------|
   | 1 | `NANOBOT_*` environment variables | Docker, CI, secrets |
   | 2 | `.env` file in working directory | Local dev convenience |
   | 3 | `~/.nanobot/config.json` (via `load_config()`) | Persistent user prefs |
   | 4 | Schema defaults in `nanobot/config/schema.py` | Sane zero-config |

   Implemented via `pydantic-settings` `SettingsConfigDict` on the root
   `Config(BaseSettings)` class: `env_prefix="NANOBOT_"`,
   `env_nested_delimiter="__"`, `env_file=".env"`.

2. **Typed sub-models for cross-cutting concerns:**

   - `FeaturesConfig` — top-level feature flags (planning, verification,
     delegation, memory, skills, streaming).  Act as master kill-switches
     that override per-agent settings.
   - `LLMConfig` — LLM call tuning (timeout_s, max_retries).  Replaces
     scattered `NANOBOT_LLM_TIMEOUT_S` / `NANOBOT_LLM_MAX_RETRIES` env reads.

> **Note:** The `from_defaults()` pattern was replaced by hierarchical `AgentConfig`
> during the config single-model refactor (2026-03-26).

3. **Feature flags flow** from root `Config.features` through `_make_agent_config()`
   into `AgentConfig` fields, then into `AgentLoop` behaviour:

   | Flag | AgentConfig field | Effect |
   |------|------------------|--------|
   | `planning_enabled` | `planning_enabled` | Skip planning prompt |
   | `verification_enabled` | `verification_mode="off"` | Skip self-critique |
   | `memory_enabled` | `memory_enabled` | Zero-out memory params, skip consolidation |
   | `skills_enabled` | `skills_enabled` | Skip skill tool discovery |
   | `streaming_enabled` | `streaming_enabled` | Suppress progress callbacks |

4. **`.env.example`** documents all supported variables.

5. **Legacy env vars** (the 20 ad-hoc `os.getenv` calls in store.py,
   mem0_adapter.py, litellm_provider.py) remain supported for backward
   compatibility.  Consolidation into the schema is a future task tracked
   in `.env.example` under the "Legacy" section.

## Consequences

### Positive

- Single source of truth for configuration defaults (schema.py).
- Operators can configure entirely via env vars or `.env`.
- Feature flags enable safe rollout and A/B testing of capabilities.
- `.env.example` serves as self-documenting reference.

### Negative

- Two config paths coexist (schema-based and legacy env reads) until
  consolidation is complete.
- `pydantic-settings` becomes a hard dependency.

### Neutral

- `load_config()` / `save_config()` interface unchanged.
- JSON config file format unchanged.
