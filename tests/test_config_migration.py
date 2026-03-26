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
        assert "reranker" not in defaults
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

    def test_mission_stays_at_top_level(self):
        data = {
            "agents": {
                "defaults": {
                    "mission": {"maxConcurrent": 5},
                }
            }
        }
        result = _migrate_config(data)
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

    def test_mem0_then_vector_migration(self):
        """mem0 rename happens first, then vectorSync moves under memory."""
        data = {
            "agents": {
                "defaults": {
                    "mem0": {"userId": "custom"},
                    "mem0RawTurnIngestion": False,
                }
            }
        }
        result = _migrate_config(data)
        defaults = result["agents"]["defaults"]
        assert "mem0" not in defaults
        assert "vectorSync" not in defaults
        assert defaults["memory"]["vector"]["userId"] == "custom"
        assert defaults["memory"]["rawTurnIngestion"] is False
