# Config Single Model Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken AgentDefaults + from_defaults() + AgentConfig three-step config pattern with a single hierarchical AgentConfig that parses directly from config JSON, eliminating the 48-entry manual mapping and the silent-drop failure mode.

**Architecture:** AgentConfig becomes a hierarchical Pydantic model with nested sections (MemoryConfig, MissionConfig). Memory fields move from flat `memory_*` prefixed fields to `config.memory.*`. The `from_defaults()` mapping and `AgentDefaults` class are deleted. `_build_rollout_overrides()` is deleted — MemoryStore receives `MemoryConfig` directly, and `RolloutConfig` builds its internal dict from the typed model instead of a raw dict.

**Tech Stack:** Python 3.10+, Pydantic v2, SQLite (memory subsystem), pytest

---

## File Structure

### Files Created

| File | Responsibility | ~LOC |
|------|---------------|------|
| `nanobot/config/memory.py` | MemorySectionWeights, RerankerConfig, VectorConfig, MemoryConfig | ~90 |
| `nanobot/config/mission.py` | MissionConfig | ~15 |
| `nanobot/config/agent.py` | Hierarchical AgentConfig (the single model) | ~90 |

### Files Modified

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | Remove AgentDefaults, AgentConfig, from_defaults(), RerankerConfig, VectorSyncConfig, MissionConfig, MemorySectionWeights. Keep all other classes. Update AgentsConfig.defaults type. |
| `nanobot/config/__init__.py` | No change needed (only exports Config, load_config, get_config_path) |
| `nanobot/config/loader.py` | Add flat-to-nested migration in `_migrate_config()` |
| `nanobot/memory/rollout.py` | Accept MemoryConfig instead of raw dict, build rollout dict from typed fields |
| `nanobot/memory/store.py` | Accept MemoryConfig instead of `rollout_overrides: dict` |
| `nanobot/agent/agent_factory.py` | Delete `_build_rollout_overrides()`, use `config.memory.*` and `config.mission.*` section access |
| `nanobot/agent/message_processor.py` | Change `config.memory_window` → `config.memory.window`, etc. |
| `nanobot/agent/turn_orchestrator.py` | No memory field access — only `context_window_tokens`, `planning_enabled`, `max_session_wall_time_seconds` (unchanged) |
| `nanobot/agent/agent_components.py` | Update AgentConfig import path |
| `nanobot/agent/loop.py` | Remove `memory_rollout_overrides` from stored state |
| `nanobot/cli/_shared.py` | Rewrite `_make_agent_config()` — use `AgentConfig.from_raw()` or direct construction |
| `nanobot/cli/memory.py` | Delete `_memory_rollout_overrides()`, pass `config.memory` section to MemoryStore |
| `nanobot/agent/agent_components.py` | Remove `memory_rollout_overrides` from `_InfraConfig` |
| `tests/helpers.py` | Update `_make_config()` to use new field paths |
| ~15 other test files | Update AgentConfig construction and field access |

---

## Task 1: Create MemoryConfig section model

**Files:**
- Create: `nanobot/config/memory.py`
- Test: `tests/test_config_memory_section.py`

This is the largest new file — it absorbs all memory-related fields from the old AgentDefaults and AgentConfig, plus the nested RerankerConfig, VectorSyncConfig, and MemorySectionWeights.

- [ ] **Step 1: Write the test**

```python
"""Tests for MemoryConfig section model."""

from __future__ import annotations

from nanobot.config.memory import MemoryConfig, MemorySectionWeights, RerankerConfig, VectorConfig


class TestMemoryConfigDefaults:
    def test_defaults(self):
        mc = MemoryConfig()
        assert mc.window == 100
        assert mc.retrieval_k == 6
        assert mc.token_budget == 900
        assert mc.md_token_cap == 1500
        assert mc.uncertainty_threshold == 0.6
        assert mc.enable_contradiction_check is True
        assert mc.rollout_mode == "enabled"
        assert mc.micro_extraction_enabled is False
        assert mc.micro_extraction_model is None
        assert mc.raw_turn_ingestion is True

    def test_nested_reranker(self):
        mc = MemoryConfig()
        assert isinstance(mc.reranker, RerankerConfig)
        assert mc.reranker.mode == "enabled"
        assert mc.reranker.alpha == 0.5

    def test_nested_vector(self):
        mc = MemoryConfig()
        assert isinstance(mc.vector, VectorConfig)
        assert mc.vector.user_id == "nanobot"
        assert mc.vector.verify_write is True

    def test_override(self):
        mc = MemoryConfig(window=50, rollout_mode="disabled")
        assert mc.window == 50
        assert mc.rollout_mode == "disabled"

    def test_nested_override(self):
        mc = MemoryConfig(reranker=RerankerConfig(mode="shadow", alpha=0.8))
        assert mc.reranker.mode == "shadow"
        assert mc.reranker.alpha == 0.8

    def test_camel_case_alias(self):
        mc = MemoryConfig.model_validate({"retrievalK": 10, "tokenBudget": 500})
        assert mc.retrieval_k == 10
        assert mc.token_budget == 500

    def test_section_weights(self):
        mc = MemoryConfig(
            section_weights={"chat": MemorySectionWeights(long_term=0.5, profile=0.3)}
        )
        assert mc.section_weights["chat"].long_term == 0.5


class TestRerankerConfig:
    def test_defaults(self):
        rc = RerankerConfig()
        assert rc.mode == "enabled"
        assert rc.alpha == 0.5
        assert rc.model == "onnx:ms-marco-MiniLM-L-6-v2"


class TestVectorConfig:
    def test_defaults(self):
        vc = VectorConfig()
        assert vc.user_id == "nanobot"
        assert vc.add_debug is False
        assert vc.verify_write is True
        assert vc.force_infer is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_memory_section.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nanobot.config.memory'`

- [ ] **Step 3: Create `nanobot/config/memory.py`**

```python
"""Memory subsystem configuration models."""

from __future__ import annotations

from pydantic import Field

from nanobot.config.schema import Base


class MemorySectionWeights(Base):
    """Per-section token budget weights for one retrieval intent.

    Values are normalised to sum to 1.0 at allocation time — only relative
    ratios matter. An empty dict means 'use DEFAULT_SECTION_WEIGHTS'.
    """

    long_term: float = Field(default=0.0, ge=0.0)
    profile: float = Field(default=0.0, ge=0.0)
    semantic: float = Field(default=0.0, ge=0.0)
    episodic: float = Field(default=0.0, ge=0.0)
    reflection: float = Field(default=0.0, ge=0.0)
    graph: float = Field(default=0.0, ge=0.0)
    unresolved: float = Field(default=0.0, ge=0.0)


class RerankerConfig(Base):
    """Cross-encoder re-ranker tuning."""

    mode: str = "enabled"  # enabled | shadow | disabled
    alpha: float = 0.5  # Blend weight 0.0-1.0
    model: str = "onnx:ms-marco-MiniLM-L-6-v2"


class VectorConfig(Base):
    """Vector sync adapter tuning."""

    user_id: str = "nanobot"
    add_debug: bool = False
    verify_write: bool = True
    force_infer: bool = False


class MemoryConfig(Base):
    """Memory subsystem configuration — all memory-related fields in one section."""

    # Core
    window: int = 100
    retrieval_k: int = 6
    token_budget: int = 900
    md_token_cap: int = 1500  # max tokens for memory snapshot injection; 0 = unlimited
    uncertainty_threshold: float = 0.6
    enable_contradiction_check: bool = True
    conflict_auto_resolve_gap: float = 0.25

    # Rollout feature flags
    rollout_mode: str = "enabled"  # enabled | shadow | disabled
    type_separation_enabled: bool = True
    router_enabled: bool = True
    reflection_enabled: bool = True
    shadow_mode: bool = False
    shadow_sample_rate: float = 0.2
    vector_health_enabled: bool = True
    auto_reindex_on_empty_vector: bool = True
    history_fallback_enabled: bool = False
    fallback_allowed_sources: list[str] = Field(
        default_factory=lambda: ["profile", "events", "vector_search"]
    )
    fallback_max_summary_chars: int = 280

    # Rollout gates
    rollout_gate_min_recall_at_k: float = 0.55
    rollout_gate_min_precision_at_k: float = 0.25
    rollout_gate_max_avg_context_tokens: float = 1400.0
    rollout_gate_max_history_fallback_ratio: float = 0.05

    # Section weights (keyed by intent name)
    section_weights: dict[str, MemorySectionWeights] = Field(default_factory=dict)

    # Micro-extraction (per-turn lightweight memory extraction)
    micro_extraction_enabled: bool = False  # Feature gate (opt-in)
    micro_extraction_model: str | None = None  # None = use "gpt-4o-mini"

    # Raw turn ingestion
    raw_turn_ingestion: bool = True

    # Subsections
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    vector: VectorConfig = Field(default_factory=VectorConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_memory_section.py -v`
Expected: all PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 6: Commit**

```bash
git add nanobot/config/memory.py tests/test_config_memory_section.py
git commit -m "feat(config): add MemoryConfig section model

Hierarchical Pydantic model absorbing all memory-related fields from
AgentDefaults/AgentConfig. Includes nested RerankerConfig, VectorConfig,
and MemorySectionWeights. Foundation for single-model config refactor."
```

---

## Task 2: Create MissionConfig file and new hierarchical AgentConfig

**Files:**
- Create: `nanobot/config/mission.py`
- Create: `nanobot/config/agent.py`
- Modify: `tests/test_config_memory_section.py` (add AgentConfig tests)

MissionConfig is tiny. AgentConfig is the core of the refactor — it replaces both old AgentDefaults and old AgentConfig with a single hierarchical model.

- [ ] **Step 1: Write the tests**

Add to `tests/test_config_memory_section.py` (rename later) or create a new test file:

```python
"""Tests for the new hierarchical AgentConfig."""

from __future__ import annotations

from nanobot.config.agent import AgentConfig
from nanobot.config.memory import MemoryConfig, RerankerConfig
from nanobot.config.mission import MissionConfig


class TestMissionConfig:
    def test_defaults(self):
        mc = MissionConfig()
        assert mc.max_concurrent == 3
        assert mc.max_iterations == 15
        assert mc.result_max_chars == 4000


class TestAgentConfigHierarchical:
    def test_defaults(self):
        ac = AgentConfig(workspace="/tmp/test", model="test")
        assert ac.workspace == "/tmp/test"
        assert ac.model == "test"
        assert isinstance(ac.memory, MemoryConfig)
        assert isinstance(ac.mission, MissionConfig)
        assert ac.memory.window == 100
        assert ac.mission.max_concurrent == 3

    def test_nested_memory_override(self):
        ac = AgentConfig(
            workspace="/tmp/test",
            model="test",
            memory=MemoryConfig(window=50, rollout_mode="disabled"),
        )
        assert ac.memory.window == 50
        assert ac.memory.rollout_mode == "disabled"

    def test_feature_flags(self):
        ac = AgentConfig(workspace="/tmp/test", model="test")
        assert ac.planning_enabled is True
        assert ac.delegation_enabled is True
        assert ac.memory_enabled is True
        assert ac.skills_enabled is True
        assert ac.streaming_enabled is True

    def test_from_raw_flat(self):
        ac = AgentConfig.from_raw({"workspace": "/tmp/test", "model": "test", "maxTokens": 4096})
        assert ac.max_tokens == 4096

    def test_from_raw_nested(self):
        ac = AgentConfig.from_raw({
            "workspace": "/tmp/test",
            "model": "test",
            "memory": {"window": 50, "reranker": {"mode": "shadow"}},
        })
        assert ac.memory.window == 50
        assert ac.memory.reranker.mode == "shadow"

    def test_from_raw_with_overrides(self):
        ac = AgentConfig.from_raw(
            {"workspace": "/tmp/test", "model": "base"},
            model="override",
        )
        assert ac.model == "override"

    def test_workspace_path(self):
        ac = AgentConfig(workspace="~/test", model="test")
        assert ac.workspace_path.name == "test"

    def test_camel_case_json(self):
        ac = AgentConfig.model_validate({
            "workspace": "/tmp/t",
            "model": "test",
            "maxTokens": 16384,
            "memory": {"tokenBudget": 500},
        })
        assert ac.max_tokens == 16384
        assert ac.memory.token_budget == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config_hierarchical.py -v`
Expected: FAIL — modules not found

- [ ] **Step 3: Create `nanobot/config/mission.py`**

```python
"""Mission subsystem configuration."""

from __future__ import annotations

from nanobot.config.schema import Base


class MissionConfig(Base):
    """Background mission tuning."""

    max_concurrent: int = 3
    max_iterations: int = 15
    result_max_chars: int = 4000
```

- [ ] **Step 4: Create `nanobot/config/agent.py`**

```python
"""Unified agent runtime configuration — single hierarchical model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from nanobot.config.memory import MemoryConfig
from nanobot.config.mission import MissionConfig
from nanobot.config.schema import Base


class AgentConfig(Base):
    """Unified agent runtime configuration.

    This is the single config model — it IS the config file schema AND the
    runtime model. No manual mapping, no ``AgentDefaults``, no ``from_defaults()``.

    Nested sections (``memory``, ``mission``) group related fields and are
    passed directly to their consuming subsystems.
    """

    # Core
    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.1
    max_iterations: int = 40
    context_window_tokens: int = 128_000

    # Nested sections
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    mission: MissionConfig = Field(default_factory=MissionConfig)

    # Feature flags (applied from Config.features kill-switches)
    planning_enabled: bool = True
    verification_mode: str = "on_uncertainty"  # always | on_uncertainty | off
    delegation_enabled: bool = True
    memory_enabled: bool = True
    skills_enabled: bool = True
    streaming_enabled: bool = True

    # Tools
    shell_mode: str = "denylist"  # allowlist | denylist
    restrict_to_workspace: bool = True
    tool_result_max_chars: int = 2000
    tool_result_context_tokens: int = 500
    tool_summary_model: str = ""  # LLM for summarising large tool results; empty = main model
    vision_model: str = "gpt-4o-mini"

    # Summary/Compression
    summary_model: str | None = None  # None = use main model

    # Session
    message_timeout: int = 300  # Per-message timeout (seconds); 0 = no timeout
    max_session_cost_usd: float = 0.0  # 0 = disabled
    max_session_wall_time_seconds: int = 0  # 0 = disabled

    # Delegation
    max_delegation_depth: int = 8  # Max total delegations per turn (0 = unlimited)

    # Knowledge graph
    graph_enabled: bool = False

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser()

    @classmethod
    def from_raw(cls, raw: dict[str, Any], **overrides: Any) -> AgentConfig:
        """Construct from config file data with overrides applied last."""
        data = dict(raw)
        data.update(overrides)
        return cls.model_validate(data)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_hierarchical.py tests/test_config_memory_section.py -v`
Expected: all PASS

- [ ] **Step 6: Run lint and typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 7: Commit**

```bash
git add nanobot/config/mission.py nanobot/config/agent.py tests/test_config_hierarchical.py
git commit -m "feat(config): add hierarchical AgentConfig with nested sections

Single model replaces AgentDefaults + from_defaults() + old AgentConfig.
Memory and mission fields are now nested sections. from_raw() replaces
from_defaults() with direct Pydantic validation — no manual mapping."
```

---

## Task 3: Update schema.py — remove old classes, rewire AgentsConfig

**Files:**
- Modify: `nanobot/config/schema.py` (lines 136-416 — remove AgentDefaults, old AgentConfig, from_defaults, and moved models)
- Modify: `nanobot/config/schema.py` (line 421 — change AgentsConfig.defaults type)

This task removes the old dual-schema classes from schema.py and points `AgentsConfig.defaults` at the new `AgentConfig`. The models that moved to their own files (RerankerConfig, VectorSyncConfig, MissionConfig, MemorySectionWeights) are deleted from schema.py but re-exported for any remaining importers.

- [ ] **Step 1: Update `nanobot/config/schema.py`**

Remove these classes entirely:
- `VectorSyncConfig` (lines 136-142) — replaced by `VectorConfig` in `config/memory.py`
- `RerankerConfig` (lines 145-150) — moved to `config/memory.py`
- `MissionConfig` (lines 153-158) — moved to `config/mission.py`
- `MemorySectionWeights` (lines 161-174) — moved to `config/memory.py`
- `AgentDefaults` (lines 177-237) — deleted entirely
- `AgentConfig` (lines 240-416) — replaced by `config/agent.py`

Update `AgentsConfig` (line 418-422):
```python
from nanobot.config.agent import AgentConfig

class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentConfig = Field(default_factory=AgentConfig)
    routing: RoutingConfig = Field(default_factory=lambda: RoutingConfig())
```

Add backward-compat re-exports at the bottom of schema.py for any importers that haven't been updated yet:
```python
# Re-exports for backward compatibility during refactor
from nanobot.config.memory import (  # noqa: E402, F401
    MemoryConfig,
    MemorySectionWeights,
    RerankerConfig,
    VectorConfig,
)
from nanobot.config.mission import MissionConfig  # noqa: E402, F401
from nanobot.config.agent import AgentConfig  # noqa: E402, F401
```

Also remove the `# size-exception` comment on line 2 — the file will be well under 500 LOC after these deletions.

- [ ] **Step 2: Run lint and typecheck to find broken imports**

Run: `make lint && make typecheck`
Expected: many type errors in files importing `AgentDefaults` or old field names. This is expected — we fix them in subsequent tasks.

- [ ] **Step 3: Commit**

```bash
git add nanobot/config/schema.py
git commit -m "refactor(config): remove AgentDefaults and old AgentConfig from schema.py

AgentsConfig.defaults now points to the new hierarchical AgentConfig.
Old classes (RerankerConfig, VectorSyncConfig, MissionConfig,
MemorySectionWeights) moved to their own files. Re-exports added for
transitional compatibility."
```

---

## Task 4: Add config migration for flat-to-nested keys

**Files:**
- Modify: `nanobot/config/loader.py` (add migration in `_migrate_config()`)
- Test: `tests/test_config_migration.py`

Existing config.json files use flat camelCase keys like `"memoryWindow": 100` under `agents.defaults`. The new schema expects `"memory": {"window": 100}`. The migration converts the old format.

- [ ] **Step 1: Write the test**

```python
"""Tests for config migration from flat to nested format."""

from __future__ import annotations

from nanobot.config.loader import _migrate_config


class TestFlatToNestedMigration:
    def test_flat_memory_keys_migrated(self):
        data = {
            "agents": {
                "defaults": {
                    "model": "gpt-4o",
                    "memoryWindow": 50,
                    "memoryRetrievalK": 10,
                    "memoryTokenBudget": 500,
                    "memoryRolloutMode": "disabled",
                    "memoryReflectionEnabled": False,
                }
            }
        }
        result = _migrate_config(data)
        defaults = result["agents"]["defaults"]
        assert "memoryWindow" not in defaults
        assert defaults["memory"]["window"] == 50
        assert defaults["memory"]["retrievalK"] == 10
        assert defaults["memory"]["tokenBudget"] == 500
        assert defaults["memory"]["rolloutMode"] == "disabled"
        assert defaults["memory"]["reflectionEnabled"] is False

    def test_nested_format_untouched(self):
        data = {
            "agents": {
                "defaults": {
                    "model": "gpt-4o",
                    "memory": {"window": 50},
                }
            }
        }
        result = _migrate_config(data)
        assert result["agents"]["defaults"]["memory"]["window"] == 50

    def test_reranker_migrated(self):
        data = {
            "agents": {
                "defaults": {
                    "reranker": {"mode": "shadow", "alpha": 0.8},
                }
            }
        }
        result = _migrate_config(data)
        defaults = result["agents"]["defaults"]
        assert "reranker" not in defaults  # moved under memory
        assert defaults["memory"]["reranker"]["mode"] == "shadow"

    def test_vector_sync_migrated(self):
        data = {
            "agents": {
                "defaults": {
                    "vectorSync": {"userId": "test"},
                    "vectorRawTurnIngestion": False,
                }
            }
        }
        result = _migrate_config(data)
        defaults = result["agents"]["defaults"]
        assert "vectorSync" not in defaults
        assert defaults["memory"]["vector"]["userId"] == "test"
        assert defaults["memory"]["rawTurnIngestion"] is False

    def test_mission_migrated(self):
        data = {
            "agents": {
                "defaults": {
                    "mission": {"maxConcurrent": 5},
                }
            }
        }
        result = _migrate_config(data)
        # mission stays at top level of defaults (it's already a section)
        assert result["agents"]["defaults"]["mission"]["maxConcurrent"] == 5

    def test_rollout_gate_keys_migrated(self):
        data = {
            "agents": {
                "defaults": {
                    "memoryRolloutGateMinRecallAtK": 0.7,
                    "memoryRolloutGateMinPrecisionAtK": 0.3,
                }
            }
        }
        result = _migrate_config(data)
        mem = result["agents"]["defaults"]["memory"]
        assert mem["rolloutGateMinRecallAtK"] == 0.7
        assert mem["rolloutGateMinPrecisionAtK"] == 0.3

    def test_max_tool_iterations_renamed(self):
        """maxToolIterations → maxIterations at agent level."""
        data = {
            "agents": {
                "defaults": {
                    "maxToolIterations": 30,
                }
            }
        }
        result = _migrate_config(data)
        assert result["agents"]["defaults"]["maxIterations"] == 30
        assert "maxToolIterations" not in result["agents"]["defaults"]

    def test_memory_section_weights_migrated(self):
        data = {
            "agents": {
                "defaults": {
                    "memorySectionWeights": {"chat": {"longTerm": 0.5}},
                }
            }
        }
        result = _migrate_config(data)
        mem = result["agents"]["defaults"]["memory"]
        assert mem["sectionWeights"]["chat"]["longTerm"] == 0.5

    def test_empty_data(self):
        assert _migrate_config({}) == {}

    def test_no_defaults(self):
        data = {"agents": {}}
        assert _migrate_config(data) == {"agents": {}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_migration.py -v`
Expected: FAIL — migration doesn't handle nested format yet

- [ ] **Step 3: Implement the migration in `nanobot/config/loader.py`**

Replace the existing `_migrate_config()` function with an expanded version that handles all flat-to-nested conversions. The flat key mapping is:

```python
# Flat camelCase key → (nested section, nested key)
_MEMORY_FLAT_KEYS: dict[str, str] = {
    "memoryWindow": "window",
    "memoryRetrievalK": "retrievalK",
    "memoryTokenBudget": "tokenBudget",
    "memoryMdTokenCap": "mdTokenCap",
    "memoryUncertaintyThreshold": "uncertaintyThreshold",
    "memoryEnableContradictionCheck": "enableContradictionCheck",
    "memoryConflictAutoResolveGap": "conflictAutoResolveGap",
    "memoryRolloutMode": "rolloutMode",
    "memoryTypeSeparationEnabled": "typeSeparationEnabled",
    "memoryRouterEnabled": "routerEnabled",
    "memoryReflectionEnabled": "reflectionEnabled",
    "memoryShadowMode": "shadowMode",
    "memoryShadowSampleRate": "shadowSampleRate",
    "memoryVectorHealthEnabled": "vectorHealthEnabled",
    "memoryAutoReindexOnEmptyVector": "autoReindexOnEmptyVector",
    "memoryHistoryFallbackEnabled": "historyFallbackEnabled",
    "memoryFallbackAllowedSources": "fallbackAllowedSources",
    "memoryFallbackMaxSummaryChars": "fallbackMaxSummaryChars",
    "memoryRolloutGateMinRecallAtK": "rolloutGateMinRecallAtK",
    "memoryRolloutGateMinPrecisionAtK": "rolloutGateMinPrecisionAtK",
    "memoryRolloutGateMaxAvgMemoryContextTokens": "rolloutGateMaxAvgContextTokens",
    "memoryRolloutGateMaxHistoryFallbackRatio": "rolloutGateMaxHistoryFallbackRatio",
    "memorySectionWeights": "sectionWeights",
    "microExtractionEnabled": "microExtractionEnabled",
    "microExtractionModel": "microExtractionModel",
}
```

The implementation moves flat keys into a `"memory"` nested dict, moves `"reranker"` and `"vectorSync"` under `"memory"`, renames `"maxToolIterations"` → `"maxIterations"`, and handles the `vectorRawTurnIngestion` → `memory.rawTurnIngestion` rename. Keep the existing mem0 and restrictToWorkspace migrations.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_config_migration.py -v`
Expected: all PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 6: Commit**

```bash
git add nanobot/config/loader.py tests/test_config_migration.py
git commit -m "feat(config): add flat-to-nested migration in _migrate_config

Converts old flat memoryWindow/memoryRetrievalK/etc keys to nested
memory.window/memory.retrievalK format. Also migrates reranker and
vectorSync into memory section, and renames maxToolIterations."
```

---

## Task 5: Update RolloutConfig and MemoryStore to accept MemoryConfig

**Files:**
- Modify: `nanobot/memory/rollout.py` — accept `MemoryConfig | None` instead of `dict | None`
- Modify: `nanobot/memory/store.py` — change constructor signature
- Modify: `nanobot/cli/memory.py` — delete `_memory_rollout_overrides()`, pass MemoryConfig

RolloutConfig converts MemoryConfig fields into its internal dict format. MemoryStore passes MemoryConfig through. This eliminates both `_build_rollout_overrides()` and `_memory_rollout_overrides()`.

- [ ] **Step 1: Update `nanobot/memory/rollout.py`**

Change `__init__` to accept `MemoryConfig | None`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from nanobot.config.memory import MemoryConfig


class RolloutConfig:
    """Feature flag management for the memory subsystem."""

    ROLLOUT_MODES: ClassVar[set[str]] = {"enabled", "shadow", "disabled"}

    def __init__(
        self,
        overrides: dict[str, Any] | None = None,
        *,
        memory_config: MemoryConfig | None = None,
    ) -> None:
        self.rollout = self._load_defaults()
        if memory_config is not None:
            self.apply_overrides(self._config_to_overrides(memory_config))
        elif isinstance(overrides, dict):
            self.apply_overrides(overrides)

    @staticmethod
    def _config_to_overrides(mc: MemoryConfig) -> dict[str, Any]:
        """Convert a MemoryConfig to the rollout overrides dict format."""
        return {
            "memory_rollout_mode": mc.rollout_mode,
            "memory_type_separation_enabled": mc.type_separation_enabled,
            "memory_router_enabled": mc.router_enabled,
            "memory_reflection_enabled": mc.reflection_enabled,
            "memory_shadow_mode": mc.shadow_mode,
            "memory_shadow_sample_rate": mc.shadow_sample_rate,
            "memory_vector_health_enabled": mc.vector_health_enabled,
            "memory_auto_reindex_on_empty_vector": mc.auto_reindex_on_empty_vector,
            "memory_history_fallback_enabled": mc.history_fallback_enabled,
            "conflict_auto_resolve_gap": mc.conflict_auto_resolve_gap,
            "memory_fallback_allowed_sources": mc.fallback_allowed_sources
            or ["profile", "events", "vector_search"],
            "memory_fallback_max_summary_chars": mc.fallback_max_summary_chars,
            "rollout_gates": {
                "min_recall_at_k": mc.rollout_gate_min_recall_at_k,
                "min_precision_at_k": mc.rollout_gate_min_precision_at_k,
                "max_avg_memory_context_tokens": mc.rollout_gate_max_avg_context_tokens,
                "max_history_fallback_ratio": mc.rollout_gate_max_history_fallback_ratio,
            },
            "graph_enabled": False,  # graph_enabled is on AgentConfig, not MemoryConfig
            "reranker_mode": mc.reranker.mode,
            "reranker_alpha": mc.reranker.alpha,
            "reranker_model": mc.reranker.model,
            "vector_user_id": mc.vector.user_id,
            "vector_add_debug": mc.vector.add_debug,
            "vector_verify_write": mc.vector.verify_write,
            "vector_force_infer": mc.vector.force_infer,
        }
```

Note: `graph_enabled` lives on AgentConfig (not MemoryConfig) per the spec. It will need to be passed separately or set after construction. Check `_build_rollout_overrides` — it passes `config.graph_enabled`. The cleanest fix: add `graph_enabled` as a separate parameter to MemoryStore.

- [ ] **Step 2: Update `nanobot/memory/store.py` constructor**

Change the signature from `rollout_overrides: dict[str, Any] | None` to also accept `memory_config`:

```python
def __init__(
    self,
    workspace: Path,
    rollout_overrides: dict[str, Any] | None = None,
    *,
    memory_config: MemoryConfig | None = None,
    graph_enabled: bool = False,
    embedding_provider: str | None = None,
    vector_backend: str | None = None,
):
```

Pass to RolloutConfig:
```python
self._rollout_config = RolloutConfig(
    overrides=rollout_overrides,
    memory_config=memory_config,
)
# Apply graph_enabled if provided via memory_config path
if memory_config is not None:
    self._rollout_config.rollout["graph_enabled"] = graph_enabled
```

- [ ] **Step 3: Update `nanobot/cli/memory.py`**

Delete `_memory_rollout_overrides()` function entirely (lines 18-38). Replace all call sites with MemoryConfig-based construction:

```python
# Before:
store = MemoryStore(
    config.workspace_path,
    rollout_overrides=_memory_rollout_overrides(config),
)

# After:
from nanobot.config.agent import AgentConfig

ac = config.agents.defaults  # now an AgentConfig with nested memory
store = MemoryStore(
    config.workspace_path,
    memory_config=ac.memory,
    graph_enabled=ac.graph_enabled,
)
```

Apply this pattern to all MemoryStore constructions in memory.py (lines ~51-54, ~120, ~157, ~182).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_store_helpers.py tests/test_store_branches.py tests/test_reranker.py tests/contract/test_memory_wiring.py -v`
Expected: PASS — existing tests still use `rollout_overrides=` which is still accepted

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 6: Commit**

```bash
git add nanobot/memory/rollout.py nanobot/memory/store.py nanobot/cli/memory.py
git commit -m "refactor(memory): accept MemoryConfig in RolloutConfig and MemoryStore

RolloutConfig.\_config_to_overrides() converts MemoryConfig to the
internal rollout dict format. MemoryStore constructor accepts
memory_config as a typed alternative to rollout_overrides. CLI memory
commands updated to pass config.memory directly."
```

---

## Task 6: Update agent_factory.py — the primary consumer

**Files:**
- Modify: `nanobot/agent/agent_factory.py`
- Modify: `nanobot/agent/agent_components.py`

This is the highest-impact change. Delete `_build_rollout_overrides()`. Change all 56+ flat field accesses to section accesses.

- [ ] **Step 1: Update import in `agent_factory.py`**

Change:
```python
from nanobot.config.schema import AgentConfig
```
To:
```python
from nanobot.config.agent import AgentConfig
```

- [ ] **Step 2: Delete `_build_rollout_overrides()` (lines 70-102)**

Remove the entire function.

- [ ] **Step 3: Update `build_agent()` — memory wiring section**

Replace the rollout_overrides construction and MemoryStore call:

```python
# Before:
rollout_overrides = _build_rollout_overrides(config)
...
store = MemoryStore(workspace, rollout_overrides=rollout_overrides, ...)

# After:
store = MemoryStore(
    workspace,
    memory_config=config.memory,
    graph_enabled=config.graph_enabled,
    ...
)
```

- [ ] **Step 4: Update `_build_tools()` — mission field accesses**

```python
# Before:
max_iterations=config.mission_max_iterations,
max_concurrent=config.mission_max_concurrent,
result_max_chars=config.mission_result_max_chars,

# After:
max_iterations=config.mission.max_iterations,
max_concurrent=config.mission.max_concurrent,
result_max_chars=config.mission.result_max_chars,
```

- [ ] **Step 5: Update `_wire_memory()` — memory field accesses**

```python
# Before:
config.memory_window
config.memory_enable_contradiction_check

# After:
config.memory.window
config.memory.enable_contradiction_check
```

- [ ] **Step 6: Update `build_agent()` — remaining field accesses**

Update memory retrieval config accesses:
```python
# Before:
config.memory_retrieval_k
config.memory_token_budget
config.memory_uncertainty_threshold

# After:
config.memory.retrieval_k
config.memory.token_budget
config.memory.uncertainty_threshold
```

Other fields like `config.max_tokens`, `config.verification_mode`, `config.max_delegation_depth` stay the same (they're top-level on AgentConfig).

- [ ] **Step 7: Update `_InfraConfig` in `agent_components.py`**

Remove `memory_rollout_overrides: dict` field from `_InfraConfig`. Remove the corresponding assignment in `build_agent()`.

- [ ] **Step 8: Update AgentConfig import in `agent_components.py`**

```python
# Before:
from nanobot.config.schema import AgentConfig

# After:
from nanobot.config.agent import AgentConfig
```

- [ ] **Step 9: Run lint and typecheck**

Run: `make lint && make typecheck`
Fix any remaining type errors in these files.

- [ ] **Step 10: Commit**

```bash
git add nanobot/agent/agent_factory.py nanobot/agent/agent_components.py
git commit -m "refactor(agent): use hierarchical config sections in agent_factory

Delete _build_rollout_overrides() — pass config.memory directly to
MemoryStore. Mission fields accessed via config.mission.* section.
Memory fields accessed via config.memory.* section."
```

---

## Task 7: Update remaining agent/ consumers

**Files:**
- Modify: `nanobot/agent/message_processor.py`
- Modify: `nanobot/agent/loop.py`
- Modify: `nanobot/agent/turn_orchestrator.py`

- [ ] **Step 1: Update `message_processor.py` imports and field accesses**

```python
# Import change:
from nanobot.config.agent import AgentConfig

# Field access changes (7 accesses):
# Before → After
self.config.memory_window           → self.config.memory.window
self.config.memory_enabled          → self.config.memory_enabled  # stays (top-level flag)
self.config.streaming_enabled       → self.config.streaming_enabled  # stays
self.config.memory_enable_contradiction_check → self.config.memory.enable_contradiction_check
self.config.tool_result_max_chars   → self.config.tool_result_max_chars  # stays
```

- [ ] **Step 2: Update `loop.py`**

Remove `self.memory_rollout_overrides = components.infra.memory_rollout_overrides` — this field is no longer stored.

Update AgentConfig import if needed.

- [ ] **Step 3: Update `turn_orchestrator.py`**

Update import (if it imports AgentConfig from schema). Field accesses (`context_window_tokens`, `planning_enabled`, `max_session_wall_time_seconds`) are all top-level and don't change.

- [ ] **Step 4: Run lint and typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/message_processor.py nanobot/agent/loop.py nanobot/agent/turn_orchestrator.py
git commit -m "refactor(agent): update message_processor and loop for nested config

memory_window → memory.window, memory_enable_contradiction_check →
memory.enable_contradiction_check. Remove memory_rollout_overrides
from loop.py."
```

---

## Task 8: Update CLI consumers

**Files:**
- Modify: `nanobot/cli/_shared.py`

- [ ] **Step 1: Rewrite `_make_agent_config()`**

```python
from nanobot.config.agent import AgentConfig


def _make_agent_config(config: Config) -> AgentConfig:
    """Build an ``AgentConfig`` from the root ``Config``.

    Feature flags from ``config.features`` act as master kill-switches:
    when a flag is ``False``, the corresponding ``AgentConfig`` field is
    forced off regardless of the per-agent default.
    """
    # config.agents.defaults is already an AgentConfig
    ac = config.agents.defaults

    overrides: dict[str, object] = {
        "restrict_to_workspace": config.tools.restrict_to_workspace,
    }

    # Apply feature-flag overrides (only disable, never force-enable)
    feat = config.features
    if not feat.planning_enabled:
        overrides["planning_enabled"] = False
    if not feat.verification_enabled:
        overrides["verification_mode"] = "off"
    if not feat.delegation_enabled:
        overrides["delegation_enabled"] = False
    if not feat.memory_enabled:
        overrides["memory_enabled"] = False
    if not feat.skills_enabled:
        overrides["skills_enabled"] = False
    if not feat.streaming_enabled:
        overrides["streaming_enabled"] = False

    if overrides:
        ac = ac.model_copy(update=overrides)
    return ac
```

- [ ] **Step 2: Update `_make_provider()` accesses**

```python
# Before:
config.agents.defaults.max_session_cost_usd

# After (still works — AgentConfig has this field at top level):
config.agents.defaults.max_session_cost_usd
```

No change needed for `_make_provider()` — it accesses `config.agents.defaults.model` and `config.agents.defaults.max_session_cost_usd`, which are top-level AgentConfig fields.

- [ ] **Step 3: Remove old AgentConfig import**

Remove `from nanobot.config.schema import AgentConfig` if present, replace with `from nanobot.config.agent import AgentConfig`. Or rely on the re-export in schema.py (either works, but direct import is cleaner).

- [ ] **Step 4: Run lint and typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 5: Commit**

```bash
git add nanobot/cli/_shared.py
git commit -m "refactor(cli): use model_copy for feature-flag kill-switches

_make_agent_config now uses config.agents.defaults directly (already an
AgentConfig) and applies kill-switches via model_copy. No more
from_defaults() call."
```

---

## Task 9: Update all test files

**Files:**
- Modify: `tests/helpers.py`
- Modify: `tests/test_feature_flags.py`
- Modify: `tests/test_config_cascade.py`
- Modify: `tests/test_agent_factory.py`
- Modify: `tests/test_capability_wiring.py`
- Modify: `tests/golden/test_golden_scenarios.py`
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/test_config_factory_wiring.py`
- Modify: `tests/integration/test_delegation_child_agent.py`
- Modify: `tests/integration/test_answer_verifier.py`
- Modify: `tests/integration/test_session_persistence.py`
- Modify: `tests/contract/test_routing_invariant.py`

This is the widest-reaching task. The pattern is consistent across all files:

**Pattern A — Direct AgentConfig construction (most files):**
```python
# Before:
config = AgentConfig(
    workspace=str(tmp_path),
    model="test-model",
    memory_window=10,
    ...
)

# After:
from nanobot.config.agent import AgentConfig
from nanobot.config.memory import MemoryConfig

config = AgentConfig(
    workspace=str(tmp_path),
    model="test-model",
    memory=MemoryConfig(window=10),
    ...
)
```

**Pattern B — from_defaults usage (test_feature_flags.py, test_config_cascade.py):**
```python
# Before:
defaults = AgentDefaults(model="gpt-4o", workspace="/tmp/ws")
ac = AgentConfig.from_defaults(defaults)

# After:
ac = AgentConfig(model="gpt-4o", workspace="/tmp/ws")
# Or:
ac = AgentConfig.from_raw({"model": "gpt-4o", "workspace": "/tmp/ws"})
```

**Pattern C — Flat reranker/vector field access (test_config_cascade.py):**
```python
# Before:
assert ac.reranker_mode == "enabled"
assert ac.vector_user_id == "nanobot"

# After:
assert ac.memory.reranker.mode == "enabled"
assert ac.memory.vector.user_id == "nanobot"
```

**Pattern D — MagicMock spec (test_routing_invariant.py):**
```python
# Before:
config = MagicMock(spec=AgentConfig)
config.memory_window = 10

# After:
config = MagicMock(spec=AgentConfig)
config.memory = MagicMock()
config.memory.window = 10
```

- [ ] **Step 1: Update `tests/helpers.py`**

```python
from nanobot.config.agent import AgentConfig
from nanobot.config.memory import MemoryConfig


def _make_config(tmp_path: Path, **overrides: object) -> AgentConfig:
    """Build a minimal AgentConfig for tests."""
    memory_kw: dict[str, object] = {}
    # Extract memory-specific overrides into nested MemoryConfig
    memory_keys = {"memory_window", "memory_enabled"}  # memory_enabled stays top-level
    for key in list(overrides):
        if key == "memory_window":
            memory_kw["window"] = overrides.pop(key)
        elif key.startswith("reranker_"):
            # reranker_mode → reranker.mode handled in MemoryConfig
            pass  # handle if needed

    defaults: dict[str, object] = dict(
        workspace=str(tmp_path),
        model="test-model",
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    if memory_kw:
        defaults["memory"] = MemoryConfig(**memory_kw)  # type: ignore[arg-type]
    defaults.update(overrides)
    return AgentConfig(**defaults)  # type: ignore[arg-type]
```

Actually, cleaner approach — just accept `memory` as a keyword:
```python
def _make_config(tmp_path: Path, **overrides: object) -> AgentConfig:
    """Build a minimal AgentConfig for tests."""
    defaults: dict[str, object] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory=MemoryConfig(window=10),
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)  # type: ignore[arg-type]
```

- [ ] **Step 2: Update `tests/test_feature_flags.py`**

Replace `AgentDefaults` + `from_defaults()` tests with direct `AgentConfig` construction:
```python
from nanobot.config.agent import AgentConfig

class TestFromDefaults:  # rename to TestAgentConfigConstruction
    def test_basic(self):
        ac = AgentConfig(model="gpt-4o", workspace="/tmp/ws")
        assert ac.model == "gpt-4o"
        assert ac.workspace == "/tmp/ws"

    def test_reranker(self):
        ac = AgentConfig(workspace="/tmp/ws", model="test")
        assert ac.memory.reranker.mode == "enabled"
        assert ac.memory.reranker.alpha == 0.5

    def test_vector(self):
        ac = AgentConfig(workspace="/tmp/ws", model="test")
        assert ac.memory.vector.user_id == "nanobot"
        assert ac.memory.vector.verify_write is True

    def test_from_raw_override(self):
        ac = AgentConfig.from_raw({"model": "gpt-4o", "workspace": "/tmp/ws"}, model="gpt-3.5")
        assert ac.model == "gpt-3.5"

    def test_graph_fields(self):
        ac = AgentConfig(workspace="/tmp/ws", model="test", graph_enabled=True)
        assert ac.graph_enabled is True
```

- [ ] **Step 3: Update `tests/test_config_cascade.py`**

Replace `AgentDefaults` imports and tests. Change flat field assertions to nested:
```python
# Before:
assert ac.reranker_mode == "enabled"
assert ac.vector_user_id == "nanobot"

# After:
assert ac.memory.reranker.mode == "enabled"
assert ac.memory.vector.user_id == "nanobot"
```

- [ ] **Step 4: Update integration test files**

For each integration test that constructs `AgentConfig(... memory_window=10, reranker_mode="disabled" ...)`:
```python
# Before:
config = AgentConfig(
    workspace=str(tmp_path),
    model=MODEL,
    memory_window=10,
    reranker_mode="disabled",
    graph_enabled=False,
)

# After:
from nanobot.config.memory import MemoryConfig, RerankerConfig

config = AgentConfig(
    workspace=str(tmp_path),
    model=MODEL,
    memory=MemoryConfig(
        window=10,
        reranker=RerankerConfig(mode="disabled"),
    ),
    graph_enabled=False,
)
```

Apply this pattern to:
- `tests/integration/conftest.py`
- `tests/integration/test_config_factory_wiring.py`
- `tests/integration/test_delegation_child_agent.py`
- `tests/integration/test_answer_verifier.py`
- `tests/integration/test_session_persistence.py`
- `tests/test_agent_factory.py`
- `tests/test_capability_wiring.py`
- `tests/golden/test_golden_scenarios.py`

- [ ] **Step 5: Update `tests/contract/test_routing_invariant.py` MagicMock**

```python
config = MagicMock(spec=AgentConfig)
config.memory = MagicMock()
config.memory.window = 10
config.memory.enable_contradiction_check = True
config.memory_enabled = False
config.streaming_enabled = False
config.tool_result_max_chars = 2000
```

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -x -v`
Fix any remaining failures.

- [ ] **Step 7: Commit**

```bash
git add tests/
git commit -m "test: update all tests for hierarchical AgentConfig

Replace AgentDefaults/from_defaults with direct AgentConfig construction.
Flat memory_* fields → nested memory=MemoryConfig(...). Flat reranker_*
fields → memory.reranker. All test patterns updated consistently."
```

---

## Task 10: Final validation and cleanup

**Files:**
- Modify: `nanobot/config/schema.py` — remove re-exports if all importers updated
- Possibly modify: any files flagged by `make check`

- [ ] **Step 1: Run full validation**

Run: `make check`
This runs: lint + typecheck + import-check + structure-check + prompt-check + test + integration

- [ ] **Step 2: Fix any failures**

Address lint errors, type errors, import boundary violations, or test failures.

- [ ] **Step 3: Clean up re-exports in schema.py**

If all importers now use direct imports from `config/agent.py` and `config/memory.py`, remove the backward-compat re-exports from schema.py. Verify with:
```bash
grep -r "from nanobot.config.schema import.*AgentConfig" nanobot/
grep -r "from nanobot.config.schema import.*AgentDefaults" nanobot/
grep -r "from nanobot.config.schema import.*RerankerConfig" nanobot/
grep -r "from nanobot.config.schema import.*VectorSyncConfig" nanobot/
grep -r "from nanobot.config.schema import.*MissionConfig" nanobot/
grep -r "from nanobot.config.schema import.*MemorySectionWeights" nanobot/
```

If any remain, update them to direct imports.

- [ ] **Step 4: Verify no `AgentDefaults` references remain**

```bash
grep -r "AgentDefaults" nanobot/ tests/
```

Should return zero results (except possibly in migration test comments or docs).

- [ ] **Step 5: Verify no `from_defaults` references remain**

```bash
grep -r "from_defaults" nanobot/ tests/
```

Should return zero results.

- [ ] **Step 6: Verify no `_build_rollout_overrides` references remain**

```bash
grep -r "_build_rollout_overrides\|_memory_rollout_overrides" nanobot/ tests/
```

Should return zero results.

- [ ] **Step 7: Run make check one final time**

Run: `make check`
Expected: all green

- [ ] **Step 8: Commit any cleanup**

```bash
git add -A
git commit -m "chore: final cleanup — remove re-exports and dead references"
```

---

## Post-Refactor: Fix micro-extraction SQLite thread-safety bug

After the config refactor is complete, fix the stashed SQLite thread-safety bug:

- [ ] **Step 1: Check stash**

```bash
git stash list
git stash show -p
```

- [ ] **Step 2: Apply the thread-safety fix**

In the micro-extraction code, replace `asyncio.to_thread(append_events)` with a direct call. SQLite connections cannot cross thread boundaries.

- [ ] **Step 3: Test micro-extraction**

Run relevant micro-extraction tests. The config wiring is now correct (micro_extraction fields are in MemoryConfig), so the original ddf5035 bug is resolved by the refactor itself.

- [ ] **Step 4: Commit**

```bash
git commit -m "fix: remove asyncio.to_thread for SQLite calls in micro_extractor

SQLite connections cannot cross thread boundaries. Direct call avoids
the threading issue while keeping the async interface."
```
