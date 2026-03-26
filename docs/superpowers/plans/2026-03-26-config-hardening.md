# Config Refactor Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the config single-model refactor (PR #71) with comprehensive tests, migrate memory tests to the new MemoryConfig pattern, and clean up the RolloutConfig intermediary.

**Architecture:** Add completeness and round-trip tests for AgentConfig, convert memory tests from `rollout_overrides` dicts to typed `MemoryConfig`, and eliminate the `rollout_overrides` dict path entirely so RolloutConfig only accepts `MemoryConfig`.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest, SQLite (memory subsystem)

---

## File Structure

### Files Created

| File | Responsibility | ~LOC |
|------|---------------|------|
| (none) | All changes go in existing files | |

### Files Modified

| File | Change |
|------|--------|
| `tests/test_config_hierarchical.py` | Add completeness test, round-trip test |
| `tests/test_reranker.py` | Convert `rollout_overrides` → `MemoryConfig` |
| `tests/test_store_helpers.py` | Convert `rollout_overrides` → `MemoryConfig` |
| `tests/test_store_branches.py` | Convert `rollout_overrides` → `MemoryConfig` |
| `tests/test_memory_metadata_policy.py` | Convert `rollout_overrides` → `MemoryConfig` |
| `tests/test_memory_cli_commands.py` | Convert `rollout_overrides` → `MemoryConfig` |
| `tests/contract/test_memory_wiring.py` | Convert `rollout_overrides` → `MemoryConfig` |
| `tests/integration/test_knowledge_graph_ingest.py` | Convert `rollout_overrides` → `MemoryConfig` |
| `tests/integration/test_profile_conflicts.py` | Convert `rollout_overrides` → `MemoryConfig` |
| `nanobot/memory/rollout.py` | Remove `overrides` dict parameter, accept only `MemoryConfig` |
| `nanobot/memory/store.py` | Remove `rollout_overrides` parameter, accept only `memory_config` |

---

## Task 1: Add completeness test — every AgentConfig field reachable from JSON

**Files:**
- Modify: `tests/test_config_hierarchical.py`

The spec promised `test_config_completeness` that verifies ALL fields on AgentConfig are reachable from a config JSON. Currently only a handful are spot-checked.

- [ ] **Step 1: Write the completeness test**

```python
class TestConfigCompleteness:
    """Verify every AgentConfig field is reachable from JSON config data."""

    def test_all_top_level_fields_settable(self):
        """Every top-level field on AgentConfig can be set via from_raw()."""
        data = {
            "workspace": "/test/ws",
            "model": "test-model",
            "maxTokens": 4096,
            "temperature": 0.5,
            "maxIterations": 20,
            "contextWindowTokens": 64_000,
            "planningEnabled": False,
            "verificationMode": "always",
            "delegationEnabled": False,
            "memoryEnabled": False,
            "skillsEnabled": False,
            "streamingEnabled": False,
            "shellMode": "allowlist",
            "restrictToWorkspace": False,
            "toolResultMaxChars": 500,
            "toolResultContextTokens": 100,
            "toolSummaryModel": "gpt-4o-mini",
            "visionModel": "gpt-4o",
            "summaryModel": "gpt-4o-mini",
            "messageTimeout": 60,
            "maxSessionCostUsd": 1.5,
            "maxSessionWallTimeSeconds": 600,
            "maxDelegationDepth": 3,
            "graphEnabled": True,
        }
        ac = AgentConfig.from_raw(data)
        assert ac.workspace == "/test/ws"
        assert ac.model == "test-model"
        assert ac.max_tokens == 4096
        assert ac.temperature == 0.5
        assert ac.max_iterations == 20
        assert ac.context_window_tokens == 64_000
        assert ac.planning_enabled is False
        assert ac.verification_mode == "always"
        assert ac.delegation_enabled is False
        assert ac.memory_enabled is False
        assert ac.skills_enabled is False
        assert ac.streaming_enabled is False
        assert ac.shell_mode == "allowlist"
        assert ac.restrict_to_workspace is False
        assert ac.tool_result_max_chars == 500
        assert ac.tool_result_context_tokens == 100
        assert ac.tool_summary_model == "gpt-4o-mini"
        assert ac.vision_model == "gpt-4o"
        assert ac.summary_model == "gpt-4o-mini"
        assert ac.message_timeout == 60
        assert ac.max_session_cost_usd == 1.5
        assert ac.max_session_wall_time_seconds == 600
        assert ac.max_delegation_depth == 3
        assert ac.graph_enabled is True

    def test_all_memory_fields_settable(self):
        """Every MemoryConfig field is reachable via nested JSON."""
        data = {
            "workspace": "/tmp/t",
            "model": "test",
            "memory": {
                "window": 50,
                "retrievalK": 10,
                "tokenBudget": 500,
                "mdTokenCap": 800,
                "uncertaintyThreshold": 0.3,
                "enableContradictionCheck": False,
                "conflictAutoResolveGap": 0.5,
                "rolloutMode": "shadow",
                "typeSeparationEnabled": False,
                "routerEnabled": False,
                "reflectionEnabled": False,
                "shadowMode": True,
                "shadowSampleRate": 0.5,
                "vectorHealthEnabled": False,
                "autoReindexOnEmptyVector": False,
                "historyFallbackEnabled": True,
                "fallbackAllowedSources": ["profile"],
                "fallbackMaxSummaryChars": 100,
                "rolloutGateMinRecallAtK": 0.7,
                "rolloutGateMinPrecisionAtK": 0.4,
                "rolloutGateMaxAvgContextTokens": 2000.0,
                "rolloutGateMaxHistoryFallbackRatio": 0.1,
                "sectionWeights": {},
                "microExtractionEnabled": True,
                "microExtractionModel": "gpt-4o-mini",
                "rawTurnIngestion": False,
                "reranker": {"mode": "shadow", "alpha": 0.8, "model": "custom/model"},
                "vector": {
                    "userId": "custom",
                    "addDebug": True,
                    "verifyWrite": False,
                    "forceInfer": True,
                },
            },
        }
        ac = AgentConfig.from_raw(data)
        m = ac.memory
        assert m.window == 50
        assert m.retrieval_k == 10
        assert m.token_budget == 500
        assert m.md_token_cap == 800
        assert m.uncertainty_threshold == 0.3
        assert m.enable_contradiction_check is False
        assert m.conflict_auto_resolve_gap == 0.5
        assert m.rollout_mode == "shadow"
        assert m.type_separation_enabled is False
        assert m.router_enabled is False
        assert m.reflection_enabled is False
        assert m.shadow_mode is True
        assert m.shadow_sample_rate == 0.5
        assert m.vector_health_enabled is False
        assert m.auto_reindex_on_empty_vector is False
        assert m.history_fallback_enabled is True
        assert m.fallback_allowed_sources == ["profile"]
        assert m.fallback_max_summary_chars == 100
        assert m.rollout_gate_min_recall_at_k == 0.7
        assert m.rollout_gate_min_precision_at_k == 0.4
        assert m.rollout_gate_max_avg_context_tokens == 2000.0
        assert m.rollout_gate_max_history_fallback_ratio == 0.1
        assert m.micro_extraction_enabled is True
        assert m.micro_extraction_model == "gpt-4o-mini"
        assert m.raw_turn_ingestion is False
        assert m.reranker.mode == "shadow"
        assert m.reranker.alpha == 0.8
        assert m.reranker.model == "custom/model"
        assert m.vector.user_id == "custom"
        assert m.vector.add_debug is True
        assert m.vector.verify_write is False
        assert m.vector.force_infer is True

    def test_all_mission_fields_settable(self):
        """Every MissionConfig field is reachable via nested JSON."""
        data = {
            "workspace": "/tmp/t",
            "model": "test",
            "mission": {
                "maxConcurrent": 5,
                "maxIterations": 30,
                "resultMaxChars": 8000,
            },
        }
        ac = AgentConfig.from_raw(data)
        assert ac.mission.max_concurrent == 5
        assert ac.mission.max_iterations == 30
        assert ac.mission.result_max_chars == 8000
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /c/Users/C95071414/Documents/nanobot-config-hardening && python -m pytest tests/test_config_hierarchical.py::TestConfigCompleteness -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_config_hierarchical.py
git commit -m "test: add config completeness test — every field reachable from JSON"
```

---

## Task 2: Add round-trip test — JSON → AgentConfig → JSON, no data loss

**Files:**
- Modify: `tests/test_config_hierarchical.py`

- [ ] **Step 1: Write the round-trip test**

```python
class TestConfigRoundTrip:
    """Verify JSON → AgentConfig → JSON loses no data."""

    def test_round_trip_preserves_all_fields(self):
        """model_validate → model_dump round-trip is lossless."""
        original = {
            "workspace": "/test/ws",
            "model": "test-model",
            "max_tokens": 4096,
            "temperature": 0.5,
            "max_iterations": 20,
            "context_window_tokens": 64_000,
            "planning_enabled": False,
            "verification_mode": "always",
            "delegation_enabled": False,
            "memory_enabled": False,
            "skills_enabled": False,
            "streaming_enabled": False,
            "shell_mode": "allowlist",
            "restrict_to_workspace": False,
            "tool_result_max_chars": 500,
            "tool_result_context_tokens": 100,
            "tool_summary_model": "gpt-4o-mini",
            "vision_model": "gpt-4o",
            "summary_model": "gpt-4o-mini",
            "message_timeout": 60,
            "max_session_cost_usd": 1.5,
            "max_session_wall_time_seconds": 600,
            "max_delegation_depth": 3,
            "graph_enabled": True,
            "memory": {
                "window": 50,
                "retrieval_k": 10,
                "token_budget": 500,
                "rollout_mode": "shadow",
                "micro_extraction_enabled": True,
                "micro_extraction_model": "gpt-4o-mini",
                "reranker": {"mode": "shadow", "alpha": 0.8, "model": "custom/m"},
                "vector": {"user_id": "custom", "add_debug": True},
            },
            "mission": {"max_concurrent": 5, "max_iterations": 30},
        }
        ac = AgentConfig(**original)
        dumped = ac.model_dump()

        # Every key in the original must be present with the same value
        for key, value in original.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, dict):
                        for sub_sub_key, sub_sub_value in sub_value.items():
                            assert dumped[key][sub_key][sub_sub_key] == sub_sub_value, (
                                f"{key}.{sub_key}.{sub_sub_key}"
                            )
                    else:
                        assert dumped[key][sub_key] == sub_value, f"{key}.{sub_key}"
            else:
                assert dumped[key] == value, key

    def test_camel_case_round_trip(self):
        """camelCase JSON → AgentConfig → camelCase JSON preserves keys."""
        camel_json = {
            "workspace": "/tmp/t",
            "model": "test",
            "maxTokens": 16384,
            "memory": {"tokenBudget": 500, "reranker": {"mode": "shadow"}},
            "mission": {"maxConcurrent": 5},
        }
        ac = AgentConfig.model_validate(camel_json)
        dumped = ac.model_dump(by_alias=True)
        assert dumped["maxTokens"] == 16384
        assert dumped["memory"]["tokenBudget"] == 500
        assert dumped["memory"]["reranker"]["mode"] == "shadow"
        assert dumped["mission"]["maxConcurrent"] == 5
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /c/Users/C95071414/Documents/nanobot-config-hardening && python -m pytest tests/test_config_hierarchical.py::TestConfigRoundTrip -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_config_hierarchical.py
git commit -m "test: add config round-trip test — JSON → AgentConfig → JSON lossless"
```

---

## Task 3: Convert memory tests from rollout_overrides to MemoryConfig

**Files:**
- Modify: `tests/test_reranker.py`
- Modify: `tests/test_store_helpers.py`
- Modify: `tests/test_store_branches.py`
- Modify: `tests/test_memory_metadata_policy.py`
- Modify: `tests/test_memory_cli_commands.py`
- Modify: `tests/contract/test_memory_wiring.py`
- Modify: `tests/integration/test_knowledge_graph_ingest.py`
- Modify: `tests/integration/test_profile_conflicts.py`

All these tests construct `MemoryStore(rollout_overrides={...})`. Convert them to use `MemoryStore(memory_config=MemoryConfig(...), graph_enabled=...)`.

The pattern in every case:

```python
# BEFORE:
from nanobot.memory.store import MemoryStore
store = MemoryStore(tmp_path, rollout_overrides={"graph_enabled": False, "reranker_mode": "shadow"})

# AFTER:
from nanobot.config.memory import MemoryConfig, RerankerConfig
from nanobot.memory.store import MemoryStore
store = MemoryStore(
    tmp_path,
    memory_config=MemoryConfig(reranker=RerankerConfig(mode="shadow")),
    graph_enabled=False,
)
```

Key mappings for the conversion:
- `"graph_enabled": True/False` → `graph_enabled=True/False` (separate param)
- `"reranker_mode": "shadow"` → `MemoryConfig(reranker=RerankerConfig(mode="shadow"))`
- `"reranker_alpha": 0.8` → `MemoryConfig(reranker=RerankerConfig(alpha=0.8))`
- `"reranker_model": "custom/model"` → `MemoryConfig(reranker=RerankerConfig(model="custom/model"))`
- `"memory_rollout_mode": "enabled"` → `MemoryConfig(rollout_mode="enabled")`
- `"memory_router_enabled": False` → `MemoryConfig(router_enabled=False)`
- `"rollout_gates": {"min_recall_at_k": 0.66}` → `MemoryConfig(rollout_gate_min_recall_at_k=0.66)`

- [ ] **Step 1: Convert `tests/test_reranker.py`**

In `_make_store` helper and all individual test constructions, replace `rollout_overrides=` with `memory_config=` + `graph_enabled=`.

- [ ] **Step 2: Convert `tests/test_store_helpers.py` and `tests/test_store_branches.py`**

Both have a `_store()` helper function. Change the helper:

```python
# BEFORE:
def _store(tmp_path: Path, **overrides: object) -> MemoryStore:
    return MemoryStore(tmp_path, rollout_overrides=overrides or None, embedding_provider="hash")

# AFTER:
from nanobot.config.memory import MemoryConfig

def _store(tmp_path: Path, memory_config: MemoryConfig | None = None, **kw: object) -> MemoryStore:
    return MemoryStore(tmp_path, memory_config=memory_config, embedding_provider="hash")
```

Update all call sites accordingly.

- [ ] **Step 3: Convert `tests/test_memory_metadata_policy.py`**

Two MemoryStore constructions to convert (lines ~227-235 and ~361).

- [ ] **Step 4: Convert `tests/test_memory_cli_commands.py`**

The `FakeStore` class signature needs updating.

- [ ] **Step 5: Convert `tests/contract/test_memory_wiring.py`**

Single construction at line ~31.

- [ ] **Step 6: Convert integration tests**

`tests/integration/test_knowledge_graph_ingest.py` (two constructions) and `tests/integration/test_profile_conflicts.py` (one construction).

- [ ] **Step 7: Run all converted tests**

Run: `cd /c/Users/C95071414/Documents/nanobot-config-hardening && python -m pytest tests/test_reranker.py tests/test_store_helpers.py tests/test_store_branches.py tests/test_memory_metadata_policy.py tests/test_memory_cli_commands.py tests/contract/test_memory_wiring.py tests/integration/test_knowledge_graph_ingest.py tests/integration/test_profile_conflicts.py -v`

- [ ] **Step 8: Commit**

```bash
git add tests/
git commit -m "test: convert memory tests from rollout_overrides to MemoryConfig"
```

---

## Task 4: Remove rollout_overrides parameter from MemoryStore and RolloutConfig

**Files:**
- Modify: `nanobot/memory/rollout.py`
- Modify: `nanobot/memory/store.py`

Now that all callers use `memory_config=`, remove the old `rollout_overrides` dict path entirely.

- [ ] **Step 1: Update `nanobot/memory/rollout.py`**

Remove the `overrides` parameter from `__init__`. Only accept `memory_config`:

```python
class RolloutConfig:
    """Feature flag management for the memory subsystem."""

    ROLLOUT_MODES: ClassVar[set[str]] = {"enabled", "shadow", "disabled"}

    def __init__(self, *, memory_config: MemoryConfig | None = None) -> None:
        self.rollout = self._load_defaults()
        if memory_config is not None:
            self.apply_overrides(self._config_to_overrides(memory_config))
```

Keep `apply_overrides()` as an internal method — it's still used by `_config_to_overrides` path. But the public API is now only `memory_config`.

- [ ] **Step 2: Update `nanobot/memory/store.py`**

Remove the `rollout_overrides` parameter from `__init__`:

```python
def __init__(
    self,
    workspace: Path,
    *,
    memory_config: MemoryConfig | None = None,
    graph_enabled: bool = False,
    embedding_provider: str | None = None,
    vector_backend: str | None = None,
):
```

Update the RolloutConfig construction:

```python
self._rollout_config = RolloutConfig(memory_config=memory_config)
if memory_config is not None:
    self._rollout_config.rollout["graph_enabled"] = graph_enabled
```

- [ ] **Step 3: Run full test suite**

Run: `cd /c/Users/C95071414/Documents/nanobot-config-hardening && python -m pytest tests/ --ignore=tests/integration -q`

- [ ] **Step 4: Run lint and typecheck**

Run: `cd /c/Users/C95071414/Documents/nanobot-config-hardening && make lint && make typecheck`

- [ ] **Step 5: Commit**

```bash
git add nanobot/memory/rollout.py nanobot/memory/store.py
git commit -m "refactor: remove rollout_overrides dict — MemoryStore accepts only MemoryConfig"
```

---

## Task 5: Final validation

- [ ] **Step 1: Run `make check`**

Run: `cd /c/Users/C95071414/Documents/nanobot-config-hardening && make check`

- [ ] **Step 2: Verify no remaining `rollout_overrides` references**

```bash
grep -r "rollout_overrides" nanobot/ tests/
```

Should return zero results.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "chore: final hardening cleanup"
```
