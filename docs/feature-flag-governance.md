# Feature Flag Governance

> Process for adding, managing, and retiring feature flags in Nanobot.

## Current Flags

All flags live in `FeaturesConfig` ([nanobot/config/schema.py](../nanobot/config/schema.py))
and default to **enabled** (`True`). They act as master kill-switches that override
per-agent settings in `AgentConfig`.

| Flag | Added | Purpose | Status |
|------|-------|---------|--------|
| `planning_enabled` | v0.1.0 | Plan step before tool execution | Stable |
| `verification_enabled` | v0.1.0 | Self-critique verification pass | Stable |
| `delegation_enabled` | v0.1.0 | Multi-agent delegation | Stable |
| `memory_enabled` | v0.1.0 | Memory consolidation + retrieval | Stable |
| `skills_enabled` | v0.1.0 | Skill auto-discovery | Stable |
| `streaming_enabled` | v0.1.0 | Token-by-token streaming | Stable |

## Flag Lifecycle

```
Proposed → Experimental → Stable → Deprecated → Removed
```

1. **Proposed**: Described in an ADR or PR. Not yet in code.
2. **Experimental**: Added to `FeaturesConfig` with `False` default. Opt-in only.
   Must include a rollback plan and monitoring criteria.
3. **Stable**: Default changed to `True`. Feature considered production-ready.
   Requires: ≥2 weeks in experimental, tests covering both states, no regressions.
4. **Deprecated**: Scheduled for removal. Default remains `True` but a deprecation
   warning is logged on startup if explicitly set. Update `CHANGELOG.md`.
5. **Removed**: Flag and all conditional code paths deleted. Requires an ADR if
   the removal changes public behavior.

## Adding a New Flag

1. Add the field to `FeaturesConfig` in `nanobot/config/schema.py` with default `False`.
2. Wire it through `AgentConfig.from_defaults()` (see existing pattern for `planning_enabled`).
3. Gate the feature in agent code with `if self.config.<flag_name>:`.
4. Add tests for both flag states (enabled and disabled).
5. Update this document's Current Flags table.
6. Update `docs/operating-policies.md` Feature Flags section.
7. Add to `CHANGELOG.md` under `[Unreleased]`.

## Rules

- **Maximum active flags**: Keep the total under 12. If adding a flag would exceed
  this, deprecate or remove an existing one first.
- **No nested flags**: A flag must not depend on another flag being enabled.
  Each flag gates exactly one capability.
- **No flag in hot path**: Flag checks happen at initialisation or turn start,
  never inside tight loops or per-token callbacks.
- **Test both states**: Every flag must have at least one test with the flag
  disabled and one with it enabled.
- **Cleanup deadline**: Experimental flags that haven't moved to Stable within
  3 months should be removed or re-evaluated.

## Configuration

Flags are set in `~/.nanobot/config.json`:

```json
{
  "features": {
    "planning_enabled": false,
    "streaming_enabled": false
  }
}
```

Or via environment variables:

```bash
NANOBOT_FEATURES__PLANNING_ENABLED=false
```
