"""Memory subsystem configuration models."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from nanobot.config.base import Base


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
    md_token_cap: int = 1500
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
    micro_extraction_enabled: bool = False
    micro_extraction_model: str | None = None

    # Raw turn ingestion
    raw_turn_ingestion: bool = True

    # Knowledge graph
    graph_enabled: bool = False

    # Subsections
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    vector: VectorConfig = Field(default_factory=VectorConfig)

    def rollout_status(self) -> dict[str, Any]:
        """Return a snapshot of rollout-relevant fields for reporting."""
        return {
            "rollout_mode": self.rollout_mode,
            "type_separation_enabled": self.type_separation_enabled,
            "router_enabled": self.router_enabled,
            "reflection_enabled": self.reflection_enabled,
            "vector_health_enabled": self.vector_health_enabled,
            "auto_reindex_on_empty_vector": self.auto_reindex_on_empty_vector,
            "graph_enabled": self.graph_enabled,
            "reranker_mode": self.reranker.mode,
            "reranker_alpha": self.reranker.alpha,
            "reranker_model": self.reranker.model,
            "rollout_gates": {
                "min_recall_at_k": self.rollout_gate_min_recall_at_k,
                "min_precision_at_k": self.rollout_gate_min_precision_at_k,
                "max_avg_memory_context_tokens": self.rollout_gate_max_avg_context_tokens,
                "max_history_fallback_ratio": self.rollout_gate_max_history_fallback_ratio,
            },
        }
