"""Run agent questions and capture answers for evaluation.

This script bypasses the Rich CLI to get clean text output.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nanobot.agent.memory.store import MemoryStore


def run_retrieval_eval() -> None:
    # Enable knowledge graph if Neo4j is reachable (can be overridden via env).
    os.environ.setdefault("NANOBOT_GRAPH_ENABLED", "true")

    workspace = Path.home() / ".nanobot" / "workspace"
    store = MemoryStore(workspace)

    questions = [
        # Q1: Direct fact lookup
        ("What deployment region is currently active?", ["us-east-1"]),
        # Q2: Entity-centric
        ("Who is Carlos and what does he work on?", ["carlos", "platform"]),
        # Q3: Constraint recall
        ("What constraints apply to shell commands?", ["destructive", "validate"]),
        # Q4: Cross-entity / relationship
        ("Who is involved in rollout decisions?", ["carlos", "platform-team"]),
        # Q5: Temporal / supersession
        ("What was the old deployment region before the correction?", ["eu-west-1"]),
        # Q6: Reflection retrieval
        ("Any insights about rollout gates?", ["rollout", "tighten", "gates"]),
        # Q7: Open tasks
        ("What tasks are currently open?", ["relevance-lift", "finalize"]),
        # Q8: Decision pending
        ("Are there any decisions pending my input?", ["history-fallback", "config-precedence"]),
        # Q9: Preferences
        ("What are user preferences for response style?", ["concise", "bullet"]),
        # Q10: Multi-hop (knowledge graph target)
        ("What caused the deployment failure and how was it resolved?",
         ["eu-west-1", "policy", "us-east-1"]),
        # Q11: Redis incident timeline (multi-step episodic)
        ("What happened during the Redis incident?",
         ["redis", "eviction", "oom", "maxmemory"]),
        # Q12: Cross-entity people + roles
        ("Who are Alice and Bob and what do they do?",
         ["alice", "platform", "bob", "infrastructure"]),
        # Q13: Rejected alternatives (negation/absence)
        ("What memory backend alternatives were considered and rejected?",
         ["elasticsearch", "rejected"]),
        # Q14: Tech stack (multi-entity graph)
        ("What databases does the nanobot project use?",
         ["postgresql", "redis", "qdrant", "neo4j"]),
        # Q15: Deployment tooling
        ("What tools are used for infrastructure and deployment?",
         ["terraform", "github actions"]),
        # Q16: Reflection from Redis incident
        ("What did we learn from the caching incidents?",
         ["resource limit", "eviction", "monitoring"]),
        # Q17: SLA and production constraints
        ("What are the production SLA requirements?",
         ["99.9%", "uptime", "5-minute"]),
        # Q18: Post-mortem collaboration (cross-entity graph)
        ("Who worked together on the Redis post-mortem?",
         ["carlos", "bob", "post-mortem"]),
        # Q19: Coding preferences
        ("What Python coding style does the user prefer?",
         ["type hints", "exception"]),
        # Q20: Knowledge graph architecture
        ("How does the knowledge graph integration work?",
         ["neo4j", "docker", "graph"]),
    ]

    print("=" * 80)
    print("MEMORY RETRIEVAL EVALUATION")
    print(f"Events loaded: {len(store.read_events())}")
    profile = store.read_profile()
    print(f"Profile sections: {list(profile.keys())}")
    print("=" * 80)

    results = []
    total_score = 0

    for i, (query, expected_keywords) in enumerate(questions, 1):
        print(f"\n--- Q{i}: {query}")

        # Run retrieval
        retrieved = store.retrieve(query, top_k=6)

        # Build memory context (budget must be large enough to include
        # profile + BM25 events + entity graph section).
        context = store.get_memory_context(
            query=query,
            retrieval_k=6,
            token_budget=2000,
        )

        # Check keyword recall (normalize hyphens ↔ spaces for fuzzy match)
        context_lower = context.lower()

        def _kw_match(kw: str, text: str) -> bool:
            kl = kw.lower()
            return kl in text or kl.replace("-", " ") in text or kl.replace(" ", "-") in text

        hits = [kw for kw in expected_keywords if _kw_match(kw, context_lower)]
        misses = [kw for kw in expected_keywords if not _kw_match(kw, context_lower)]
        recall = len(hits) / len(expected_keywords) if expected_keywords else 1.0

        # Show results
        print(f"  Retrieved: {len(retrieved)} events")
        for r in retrieved[:3]:
            score = r.get("score", 0)
            summary = r.get("summary", "")[:80]
            print(f"    [{score:.3f}] {summary}")

        print(f"  Keyword hits: {hits}")
        if misses:
            print(f"  Keyword misses: {misses}")
        print(f"  Recall@k: {recall:.2f}")

        # Check if graph context was included
        if "Entity Graph" in context:
            print("  [GRAPH] Entity graph context included!")
            # Extract graph lines
            for line in context.split("\n"):
                if line.startswith("- ") and "→" in line:
                    print(f"    {line}")

        results.append({
            "question": query,
            "retrieved_count": len(retrieved),
            "recall": recall,
            "hits": hits,
            "misses": misses,
            "has_graph": "Entity Graph" in context,
        })
        total_score += recall

    # Summary
    avg_recall = total_score / len(questions)
    print("\n" + "=" * 80)
    print("SUMMARY")
    print(f"  Questions: {len(questions)}")
    print(f"  Average recall: {avg_recall:.2f}")
    perfect = sum(1 for r in results if r["recall"] == 1.0)
    print(f"  Perfect recall: {perfect}/{len(questions)}")
    graph_count = sum(1 for r in results if r["has_graph"])
    print(f"  Graph context used: {graph_count}/{len(questions)}")
    print("=" * 80)

    # Per-question summary
    for i, r in enumerate(results, 1):
        status = "✓" if r["recall"] == 1.0 else "✗"
        g = " [G]" if r["has_graph"] else ""
        print(f"  Q{i} {status} recall={r['recall']:.2f} hits={r['hits']}{g}")
        if r["misses"]:
            print(f"       misses={r['misses']}")


if __name__ == "__main__":
    run_retrieval_eval()
