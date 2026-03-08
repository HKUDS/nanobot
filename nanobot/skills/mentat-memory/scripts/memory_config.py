#!/usr/bin/env python3
"""
Configuration for memory enhancement features.
Centralized feature flags and settings for memory system.
"""

MEMORY_CONFIG = {
    # Feature flags
    "ENABLE_STRUCTURED_EXTRACTION": True,  # Phase 1 - ACTIVE
    "ENABLE_CONSOLIDATION": True,  # Phase 2 (default off until tested)
    "ENABLE_WEIGHTED_RETRIEVAL": True,  # Phase 2
    "ENABLE_EMBEDDINGS": True,  # Phase 2 (optional)
    "ENABLE_DECAY": True,  # Phase 3
    
    # Extraction settings
    "MIN_IMPORTANCE_THRESHOLD": 4,  # Only extract memories with importance ≥ 4
    "MAX_MEMORIES_PER_DAY": 20,  # Prevent explosion
    
    # Consolidation settings
    "SIMILARITY_THRESHOLD": 0.75,  # Cosine similarity threshold for "similar"
    "CONSOLIDATION_TOP_K": 3,  # Check against top-3 similar memories
    
    # Retrieval settings
    "RETRIEVAL_WEIGHTS": {
        "recency": 0.3,
        "importance": 0.3,
        "relevance": 0.4
    },
    "DECAY_FACTOR": 0.995,  # 0.5% per hour
    
    # Pruning settings
    "PRUNING_ENABLED": False,
    "PRUNING_AGE_DAYS": 90,
    "PRUNING_MIN_ACCESS_COUNT": 2,
    "PRUNING_MAX_IMPORTANCE": 3,
    
    # Storage
    "MEMORY_BANK_PATH": "memory/diary/2026/memories.jsonl",
    "USE_SQLITE": False,  # Switch to SQLite if JSONL becomes slow
}
