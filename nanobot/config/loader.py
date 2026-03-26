"""Configuration loading utilities."""

from __future__ import annotations

import json
import os
from pathlib import Path

from nanobot.config.schema import Config


def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".nanobot" / "config.json"


def get_data_dir() -> Path:
    """Get the nanobot data directory."""
    from nanobot.utils.paths import get_data_path

    return get_data_path()


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.chmod(path, 0o600)


# Mapping from flat camelCase keys under agents.defaults to their nested memory keys.
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


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    # Rename mem0 config keys → vector sync equivalents
    defaults = data.get("agents", {}).get("defaults", {})
    if defaults:
        if "mem0" in defaults and "vectorSync" not in defaults:
            defaults["vectorSync"] = defaults.pop("mem0")
        if "mem0RawTurnIngestion" in defaults and "vectorRawTurnIngestion" not in defaults:
            defaults["vectorRawTurnIngestion"] = defaults.pop("mem0RawTurnIngestion")
        sources = defaults.get("memoryFallbackAllowedSources")
        if isinstance(sources, list) and "memory" not in defaults:
            # Only rewrite source names before flat-to-nested migration runs;
            # after migration memoryFallbackAllowedSources won't exist at this level.
            defaults["memoryFallbackAllowedSources"] = [
                "vector_search" if s == "mem0_get_all" else s for s in sources
            ]

    # Flat-to-nested migration: only run when the nested "memory" key is absent.
    if defaults and "memory" not in defaults:
        memory: dict = {}

        # Migrate flat memory* keys into the nested memory dict.
        for flat_key, nested_key in _MEMORY_FLAT_KEYS.items():
            if flat_key in defaults:
                memory[nested_key] = defaults.pop(flat_key)

        # Move reranker from defaults into memory.reranker.
        if "reranker" in defaults:
            memory["reranker"] = defaults.pop("reranker")

        # Move vectorSync (already renamed from mem0) into memory.vector.
        if "vectorSync" in defaults:
            memory["vector"] = defaults.pop("vectorSync")

        # Move vectorRawTurnIngestion into memory.rawTurnIngestion.
        if "vectorRawTurnIngestion" in defaults:
            memory["rawTurnIngestion"] = defaults.pop("vectorRawTurnIngestion")

        if memory:
            defaults["memory"] = memory

    # Rename maxToolIterations → maxIterations at the defaults level.
    if defaults and "maxToolIterations" in defaults and "maxIterations" not in defaults:
        defaults["maxIterations"] = defaults.pop("maxToolIterations")

    return data
