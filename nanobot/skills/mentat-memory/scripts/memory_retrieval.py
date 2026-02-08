#!/usr/bin/env python3
"""
Weighted memory retrieval with multi-factor scoring.
Implements recency + importance + relevance based retrieval.
"""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass

import sys
sys.path.insert(0, str(Path(__file__).parent))
from memory_config import MEMORY_CONFIG


@dataclass
class RetrievalResult:
    """Container for retrieval results with scoring breakdown"""
    memory: dict
    score: float
    factors: dict  # {"recency": 0.8, "importance": 0.9, "relevance": 0.7}


class MemoryRetriever:
    """Multi-factor weighted memory retrieval system"""
    
    def __init__(self, memory_bank_path: Path):
        self.memory_bank_path = memory_bank_path
        self.memories = self._load_memories()
    
    def _load_memories(self) -> List[dict]:
        """Load all active memories from JSONL bank"""
        memories = []
        if not self.memory_bank_path.exists():
            return memories
        
        with open(self.memory_bank_path, "r") as f:
            for line in f:
                try:
                    mem = json.loads(line)
                    if mem.get("status") == "active":
                        memories.append(mem)
                except json.JSONDecodeError:
                    continue
        return memories
    
    def calculate_recency_score(self, memory: dict, decay_factor: Optional[float] = None) -> float:
        """
        Exponential decay based on age.
        decay_factor=0.995 means 0.5% decay per hour.
        """
        if decay_factor is None:
            decay_factor = MEMORY_CONFIG["DECAY_FACTOR"]
        
        try:
            mem_time = datetime.fromisoformat(memory["timestamp"])
            now = datetime.now(mem_time.tzinfo)  # Use same timezone
            hours_old = (now - mem_time).total_seconds() / 3600
            
            recency = decay_factor ** hours_old
            return max(0.0, min(1.0, recency))  # Clamp to [0, 1]
        except (KeyError, ValueError):
            return 0.0
    
    def calculate_importance_score(self, memory: dict) -> float:
        """
        Normalize importance (1-10) to 0-1 scale.
        """
        try:
            importance = memory.get("importance", 1)
            return importance / 10.0
        except (TypeError, ValueError):
            return 0.1
    
    def calculate_relevance_score(self, memory: dict, query: str) -> float:
        """
        Simplified relevance scoring (keyword overlap).
        
        Production: Use embeddings + cosine similarity.
        """
        query_lower = query.lower()
        content_lower = memory.get("content", "").lower()
        
        # Simple keyword matching
        query_words = set(query_lower.split())
        content_words = set(content_lower.split())
        
        if not query_words:
            return 0.0
        
        overlap = len(query_words & content_words)
        max_possible = len(query_words)
        
        relevance = overlap / max_possible
        
        # Boost if query substring appears in content
        if query_lower in content_lower:
            relevance = min(1.0, relevance + 0.3)
        
        # Check tags for additional relevance
        tags = memory.get("tags", {})
        for tag_category, tag_values in tags.items():
            if isinstance(tag_values, list):
                for tag in tag_values:
                    if tag.lower() in query_lower:
                        relevance = min(1.0, relevance + 0.2)
        
        return relevance
    
    def weighted_retrieval(
        self,
        query: str,
        top_k: int = 5,
        time_range: Optional[str] = None,  # "day", "week", "month", "year"
        w_recency: Optional[float] = None,
        w_importance: Optional[float] = None,
        w_relevance: Optional[float] = None
    ) -> List[RetrievalResult]:
        """
        Multi-factor weighted retrieval.
        
        Args:
            query: Search query
            top_k: Number of results
            time_range: Filter by time range
            w_recency, w_importance, w_relevance: Weights (should sum to 1.0)
        
        Returns:
            List of RetrievalResult objects, sorted by score
        """
        # Use config defaults if not specified
        weights = MEMORY_CONFIG["RETRIEVAL_WEIGHTS"]
        w_recency = w_recency if w_recency is not None else weights["recency"]
        w_importance = w_importance if w_importance is not None else weights["importance"]
        w_relevance = w_relevance if w_relevance is not None else weights["relevance"]
        
        # Filter by time range if specified
        candidates = self.memories
        if time_range:
            candidates = self._filter_by_time_range(candidates, time_range)
        
        if not candidates:
            return []
        
        # Score each memory
        results = []
        for mem in candidates:
            recency = self.calculate_recency_score(mem)
            importance = self.calculate_importance_score(mem)
            relevance = self.calculate_relevance_score(mem, query)
            
            # Weighted combination
            score = (w_recency * recency + 
                    w_importance * importance + 
                    w_relevance * relevance)
            
            results.append(RetrievalResult(
                memory=mem,
                score=score,
                factors={
                    "recency": recency,
                    "importance": importance,
                    "relevance": relevance
                }
            ))
        
        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        
        return results[:top_k]
    
    def _filter_by_time_range(self, memories: List[dict], time_range: str) -> List[dict]:
        """Filter memories by time range."""
        now = datetime.now()
        
        range_map = {
            "day": 1,
            "week": 7,
            "month": 30,
            "year": 365
        }
        
        days = range_map.get(time_range, 7)
        cutoff = now - timedelta(days=days)
        
        filtered = []
        for m in memories:
            try:
                mem_time = datetime.fromisoformat(m["timestamp"])
                # Make cutoff timezone-aware if memory has timezone
                if mem_time.tzinfo:
                    cutoff = cutoff.replace(tzinfo=mem_time.tzinfo)
                
                if mem_time >= cutoff:
                    filtered.append(m)
            except (KeyError, ValueError):
                continue
        
        return filtered
    
    def search_by_tags(self, tag_filters: dict, top_k: int = 10) -> List[dict]:
        """
        Search memories by tag filters.
        
        Args:
            tag_filters: Dict like {"domain": ["tech"], "type": ["issue"], "priority": ["high"]}
            top_k: Max results
        
        Returns:
            List of matching memories, sorted by importance
        """
        matches = []
        
        for mem in self.memories:
            tags = mem.get("tags", {})
            match = True
            
            # Check if all filter categories match
            for filter_cat, filter_vals in tag_filters.items():
                mem_tags = tags.get(filter_cat, [])
                if not isinstance(mem_tags, list):
                    mem_tags = [mem_tags]
                
                # Check if any filter value matches any memory tag
                if not any(fv in mem_tags for fv in filter_vals):
                    match = False
                    break
            
            if match:
                matches.append(mem)
        
        # Sort by importance (high to low)
        matches.sort(key=lambda m: m.get("importance", 0), reverse=True)
        
        return matches[:top_k]


# CLI interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Query the memory bank")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results")
    parser.add_argument("--time-range", choices=["day", "week", "month", "year"], help="Filter by time")
    parser.add_argument("--bank", default="memory/diary/2026/memories.jsonl", help="Path to memory bank")
    
    args = parser.parse_args()
    
    retriever = MemoryRetriever(Path(args.bank))
    results = retriever.weighted_retrieval(
        query=args.query,
        top_k=args.top_k,
        time_range=args.time_range
    )
    
    print(f"Top {len(results)} results for: '{args.query}'\n")
    for i, result in enumerate(results, 1):
        mem = result.memory
        print(f"{i}. [{result.score:.3f}] {mem['content']}")
        print(f"   Factors: R={result.factors['recency']:.2f} "
              f"I={result.factors['importance']:.2f} "
              f"S={result.factors['relevance']:.2f}")
        print(f"   Importance: {mem.get('importance', 'N/A')}/10")
        print(f"   Tags: {mem.get('tags', {})}")
        print(f"   Timestamp: {mem.get('timestamp', 'N/A')}")
        print()
