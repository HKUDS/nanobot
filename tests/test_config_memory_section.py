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
        assert mc.graph_enabled is False

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

    def test_snake_case_keys(self):
        mc = MemoryConfig.model_validate({"retrieval_k": 10, "token_budget": 500})
        assert mc.retrieval_k == 10
        assert mc.token_budget == 500

    def test_section_weights(self):
        mc = MemoryConfig(
            section_weights={"chat": MemorySectionWeights(long_term=0.5, profile=0.3)}
        )
        assert mc.section_weights["chat"].long_term == 0.5


class TestGraphEnabled:
    def test_graph_enabled_default_false(self):
        """graph_enabled defaults to False in MemoryConfig."""
        mc = MemoryConfig()
        assert mc.graph_enabled is False

    def test_graph_enabled_from_json(self):
        """graph_enabled can be set via JSON config."""
        mc = MemoryConfig.model_validate({"graph_enabled": True})
        assert mc.graph_enabled is True


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
