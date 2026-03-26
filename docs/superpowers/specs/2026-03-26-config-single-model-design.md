# Config System Refactor — Single Hierarchical Model

**Date:** 2026-03-26
**Status:** Draft
**Problem:** The three-step config wiring pattern (AgentDefaults → from_defaults mapping → AgentConfig) silently drops fields, causing at least 2 confirmed bugs. 14 of 51 AgentConfig fields are silently locked to hardcoded defaults.

---

## Context

### The Current Architecture (broken)

```
config.json → AgentDefaults (nested, 38 fields)
                    ↓
              from_defaults() — 48 manual mapping entries
                    ↓
              AgentConfig (flat, 51+ fields)
```

**Failure modes:**
1. Add field to AgentConfig but forget AgentDefaults → silently uses default
2. Add field to AgentDefaults but forget mapping dict → silently uses default
3. Adding fields to AgentDefaults can break the agent (ddf5035 incident)
4. 14 fields currently unreachable from config file

**Root cause:** The two-model pattern with manual mapping is a recognized anti-pattern ("dual schema drift"). The mapping is enforced by a docstring, not by code.

### Industry Best Practice

The Python ecosystem consensus (pydantic-settings, FastAPI, Hydra) is:
- **Single model tree** matching the config file structure
- **Nested sub-models** for grouped fields (memory, mission, etc.)
- **Components receive their section**, not the whole config
- **No manual mapping** — the model IS the schema

---

## Design

### Principle: One Model, No Mapping

`AgentConfig` is a hierarchical Pydantic model that:
1. IS the config file schema (parsed directly from JSON)
2. IS the runtime model (accessed by components)
3. Uses nested sub-models for field grouping
4. Eliminates AgentDefaults and from_defaults() entirely

### Config Section Models

Each section is a focused Pydantic model in its own file:

**`config/memory.py`** (~60 LOC):
```python
class RerankerConfig(Base):
    mode: str = "enabled"
    alpha: float = 0.5
    model: str = "onnx:ms-marco-MiniLM-L-6-v2"

class VectorConfig(Base):
    user_id: str = "nanobot"
    add_debug: bool = False
    verify_write: bool = True
    force_infer: bool = False
    raw_turn_ingestion: bool = True

class MemoryConfig(Base):
    enabled: bool = True
    window: int = 100
    retrieval_k: int = 6
    token_budget: int = 900
    md_token_cap: int = 1500
    uncertainty_threshold: float = 0.6
    enable_contradiction_check: bool = True
    conflict_auto_resolve_gap: float = 0.25

    # Rollout
    rollout_mode: str = "enabled"
    type_separation_enabled: bool = True
    router_enabled: bool = True
    reflection_enabled: bool = True
    shadow_mode: bool = False
    shadow_sample_rate: float = 0.2
    vector_health_enabled: bool = True
    auto_reindex_on_empty_vector: bool = True
    history_fallback_enabled: bool = False
    fallback_allowed_sources: list[str] = ["profile", "events", "vector_search"]
    fallback_max_summary_chars: int = 280
    rollout_gate_min_recall_at_k: float = 0.55
    rollout_gate_min_precision_at_k: float = 0.25
    rollout_gate_max_avg_context_tokens: float = 1400.0
    rollout_gate_max_history_fallback_ratio: float = 0.05
    section_weights: dict = Field(default_factory=dict)

    # Micro-extraction
    micro_extraction_enabled: bool = False
    micro_extraction_model: str | None = None

    # Subsections
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    vector: VectorConfig = Field(default_factory=VectorConfig)
```

**`config/mission.py`** (~15 LOC):
```python
class MissionConfig(Base):
    max_concurrent: int = 3
    max_iterations: int = 15
    result_max_chars: int = 4000
```

**`config/features.py`** (~15 LOC):
```python
class FeaturesConfig(Base):
    planning_enabled: bool = True
    verification_enabled: bool = True
    delegation_enabled: bool = True
    streaming_enabled: bool = True
```

**`config/agent.py`** (~80 LOC):
```python
class AgentConfig(Base):
    # Core
    workspace: str = "~/.nanobot/workspace"
    model: str = "gpt-4o-mini"
    max_tokens: int = 8192
    temperature: float = 0.1
    max_iterations: int = 40

    # Sections
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    mission: MissionConfig = Field(default_factory=MissionConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)

    # Tools
    shell_mode: str = "denylist"
    restrict_to_workspace: bool = True
    tool_result_max_chars: int = 2000
    tool_result_context_tokens: int = 500
    tool_summary_model: str = ""
    vision_model: str = "gpt-4o-mini"

    # Verification
    verification_mode: str = "on_uncertainty"

    # Delegation
    delegation_enabled: bool = True
    max_delegation_depth: int = 8

    # Session
    message_timeout: int = 300
    max_session_cost_usd: float = 0.0
    max_session_wall_time_seconds: int = 0

    # Skills
    skills_enabled: bool = True

    # Streaming
    streaming_enabled: bool = True

    # Summary/Compression
    summary_model: str | None = None
    context_window_tokens: int = 128_000

    # Graph
    graph_enabled: bool = False

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser()

    @classmethod
    def from_raw(cls, raw: dict, **overrides) -> AgentConfig:
        """Construct from config file data with overrides applied last."""
        data = dict(raw)
        data.update(overrides)
        return cls(**data)
```

### What Gets Deleted

- `AgentDefaults` class — replaced by AgentConfig directly
- `from_defaults()` method — no mapping needed
- `_build_rollout_overrides()` in agent_factory.py — pass `config.memory` directly
- 48 manual mapping entries — eliminated
- The size-exception comment on schema.py — file splits to <150 LOC each

### Consumer Changes

**agent_factory.py** (primary consumer, 56+ accesses):

Before:
```python
rollout_overrides = _build_rollout_overrides(config)  # 16 field extractions
memory = MemoryStore(
    workspace=config.workspace_path,
    rollout_overrides=rollout_overrides,
)
```

After:
```python
memory = MemoryStore(
    workspace=config.workspace_path,
    memory_config=config.memory,  # pass the section
)
```

Before:
```python
micro_extractor = MicroExtractor(
    provider=provider,
    ingester=memory.ingester,
    model=config.micro_extraction_model or "gpt-4o-mini",
    enabled=config.micro_extraction_enabled,
)
```

After:
```python
micro_extractor = MicroExtractor(
    provider=provider,
    ingester=memory.ingester,
    model=config.memory.micro_extraction_model or "gpt-4o-mini",
    enabled=config.memory.micro_extraction_enabled,
)
```

**message_processor.py** (7 accesses):

Before:
```python
if unconsolidated >= self.config.memory_window:
```

After:
```python
if unconsolidated >= self.config.memory.window:
```

**_make_agent_config() in cli/_shared.py**:

Before:
```python
def _make_agent_config(config: Config) -> AgentConfig:
    overrides = {"restrict_to_workspace": config.tools.restrict_to_workspace}
    if not feat.planning_enabled:
        overrides["planning_enabled"] = False
    ...
    return AgentConfig.from_defaults(config.agents.defaults, **overrides)
```

After:
```python
def _make_agent_config(config: Config) -> AgentConfig:
    overrides = {"restrict_to_workspace": config.tools.restrict_to_workspace}
    if not config.features.planning_enabled:
        overrides["features"] = {"planning_enabled": False}
    ...
    return AgentConfig.from_raw(config.agents.defaults.model_dump(), **overrides)
```

Actually, even simpler — if `agents.defaults` IS an `AgentConfig`:
```python
def _make_agent_config(config: Config) -> AgentConfig:
    ac = config.agents.defaults  # already an AgentConfig
    # Apply feature flag kill-switches as overrides
    ...
    return ac
```

### Config File Compatibility

The config file JSON structure stays the same. Pydantic's `alias_generator=to_camel` + `populate_by_name=True` handles camelCase/snake_case mapping automatically. Nested sections map naturally:

```json
{
  "agents": {
    "defaults": {
      "model": "openai/gpt-4o-mini",
      "memory": {
        "window": 100,
        "retrievalK": 6,
        "microExtractionEnabled": true,
        "reranker": {
          "mode": "enabled",
          "alpha": 0.5
        }
      },
      "mission": {
        "maxConcurrent": 3
      }
    }
  }
}
```

**Backward compatibility for flat keys:** If existing config files use flat `memoryWindow` instead of nested `memory.window`, we can handle this with a one-time migration in `_migrate_config()` or a Pydantic validator.

---

## File Impact

### Files Created

| File | Purpose | LOC estimate |
|---|---|---|
| `nanobot/config/memory.py` | MemoryConfig, RerankerConfig, VectorConfig | ~80 |
| `nanobot/config/mission.py` | MissionConfig | ~20 |
| `nanobot/config/features.py` | FeaturesConfig (already exists, may just move) | ~15 |
| `nanobot/config/agent.py` | AgentConfig (the single model) | ~100 |

### Files Modified

| File | Change scope |
|---|---|
| `nanobot/config/schema.py` | Remove AgentDefaults, AgentConfig, from_defaults(). Keep routing, channels, tools, etc. |
| `nanobot/agent/agent_factory.py` | 56+ field accesses → section accesses. Remove _build_rollout_overrides(). |
| `nanobot/agent/message_processor.py` | 7 field accesses → section accesses |
| `nanobot/agent/loop.py` | 1 field access |
| `nanobot/agent/turn_orchestrator.py` | 1 field access |
| `nanobot/agent/agent_components.py` | AgentConfig import path |
| `nanobot/cli/_shared.py` | _make_agent_config refactor |
| `nanobot/coordination/delegation.py` | DelegationConfig fields |
| `nanobot/memory/store.py` | Receive MemoryConfig instead of rollout_overrides dict |
| Tests (~25 files) | Update AgentConfig construction and field access |

### Files Deleted

| File | Reason |
|---|---|
| None | AgentDefaults removed from schema.py, not a separate file |

---

## Testing Strategy

- All existing tests updated to use new field paths
- New test: `test_config_completeness` — verify every field on AgentConfig is reachable from config file
- New test: `test_config_round_trip` — parse JSON → AgentConfig → JSON, verify no data loss
- `make check` must pass after refactor

---

## Decisions Log

| Decision | Choice | Rationale |
|---|---|---|
| Single model vs two models | Single model | Eliminates mapping, prevents silent drops |
| Nested vs flat | Nested sections | Matches JSON, enables section-based DI, splits schema.py |
| Backward compat | One-time migration for flat keys | Clean break, migration in _migrate_config |
| Feature flags location | Separate FeaturesConfig section | Kill-switches independent of agent defaults |
| Where to put micro_extraction | MemoryConfig section | It's a memory write feature |
