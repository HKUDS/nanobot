# Feature: Per-Provider Generation Config

## Summary

Support `maxTokens`, `contextWindowTokens`, `temperature`, and `reasoningEffort` at the provider level, so that switching providers/models automatically applies the correct generation parameters without manually updating global `agents.defaults`.

## Motivation

Currently, generation parameters (`maxTokens`, `contextWindowTokens`, `temperature`, `reasoningEffort`) are only configurable under `agents.defaults` — a single global setting shared by all providers. This creates several problems:

1. **Manual parameter lookup on every model switch** — When switching from a 200K-context model (e.g., Claude) to a 32K model (e.g., some DeepSeek variants), users must manually look up and update `contextWindowTokens` and `maxTokens` in `agents.defaults`.
2. **No per-provider optimization** — Different providers/models have different optimal settings. A one-size-fits-all approach means either under-utilizing capable models or risking API errors from exceeding limits.
3. **Fallback mismatch** — When provider fallback occurs, the global generation settings may be inappropriate for the fallback provider's model.

## Proposed Design

### 1. Extend `ProviderConfig` with optional generation fields

```python
# schema.py

class ProviderGenerationConfig(Base):
    """Per-provider generation settings (all optional, override agents.defaults)."""
    max_tokens: int | None = None
    context_window_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None


class ProviderConfig(Base):
    """LLM provider configuration."""
    api_key: str | None = None
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None
    generation: ProviderGenerationConfig | None = None  # NEW
```

### 2. Merge logic: provider-level overrides global defaults

When creating a provider, merge generation settings with priority: **provider > agents.defaults**

```python
# nanobot.py / cli/commands.py

defaults = config.agents.defaults
pg = provider_config.generation if provider_config and provider_config.generation else None

provider.generation = GenerationSettings(
    temperature=pg.temperature if pg and pg.temperature is not None else defaults.temperature,
    max_tokens=pg.max_tokens if pg and pg.max_tokens is not None else defaults.max_tokens,
    reasoning_effort=pg.reasoning_effort if pg and pg.reasoning_effort is not None else defaults.reasoning_effort,
)
```

For `context_window_tokens`, same merge logic applies wherever it's consumed (memory compaction, etc.).

### 3. Example config

```json
{
  "agents": {
    "defaults": {
      "model": "minimax-m2.5",
      "provider": "tencent-coding-plan",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-xxx",
      "apiBase": "http://localhost:8080/v1",
      "generation": {
        "maxTokens": 16384,
        "contextWindowTokens": 200000,
        "temperature": 0.2
      }
    },
    "tencent-coding-plan": {
      "apiKey": "xxx",
      "apiBase": "https://api.lkeap.cloud.tencent.com/coding/v3",
      "generation": {
        "maxTokens": 8192,
        "contextWindowTokens": 65536
      }
    },
    "openrouter": {
      "apiKey": "sk-or-xxx",
      "generation": {
        "maxTokens": 32768,
        "contextWindowTokens": 128000
      }
    }
  }
}
```

## Files to Modify

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | Add `ProviderGenerationConfig` class; add `generation` field to `ProviderConfig` |
| `nanobot/nanobot.py` | Merge provider-level generation config when creating provider |
| `nanobot/cli/commands.py` | Same merge logic for CLI path |
| `nanobot/agent/memory.py` | Use merged `context_window_tokens` for compaction decisions |

## Backward Compatibility

- Fully backward compatible — all new fields are optional with `None` defaults
- If no `generation` is set on a provider, behavior is identical to current version (falls back to `agents.defaults`)
- No config migration needed

## Open Questions

- Should `context_window_tokens` also be part of `ProviderGenerationConfig`, or should it live separately since it's not a generation parameter per se (it's used for memory compaction, not sent to the API)?
- Should we also support per-model overrides (e.g., different settings for `claude-opus` vs `claude-sonnet` under the same provider)?
