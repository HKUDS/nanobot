"""Run the 20 evaluation questions through the live agent CLI and score results.

Usage:
    python3 scripts/eval_agent_live.py [--timeout 60]

Each question is sent via `nanobot agent -m "<question>"` and the response
is checked for expected keywords.  Results are printed as a scorecard.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

QUESTIONS: list[tuple[str, list[str]]] = [
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
    (
        "What caused the deployment failure and how was it resolved?",
        ["eu-west-1", "policy", "us-east-1"],
    ),
    # Q11: Redis incident timeline (multi-step episodic)
    ("What happened during the Redis incident?", ["redis", "eviction", "oom", "maxmemory"]),
    # Q12: Cross-entity people + roles
    (
        "Who are Alice and Bob and what do they do?",
        ["alice", "platform", "bob", "infrastructure"],
    ),
    # Q13: Rejected alternatives (negation/absence)
    (
        "What memory backend alternatives were considered and rejected?",
        ["elasticsearch", "rejected"],
    ),
    # Q14: Tech stack (multi-entity graph)
    (
        "What databases does the nanobot project use?",
        ["postgresql", "redis", "qdrant", "neo4j"],
    ),
    # Q15: Deployment tooling
    (
        "What tools are used for infrastructure and deployment?",
        ["terraform", "github actions"],
    ),
    # Q16: Reflection from Redis incident
    (
        "What did we learn from the caching incidents?",
        ["resource limit", "eviction", "monitoring"],
    ),
    # Q17: SLA and production constraints
    ("What are the production SLA requirements?", ["99.9%", "uptime", "5-minute"]),
    # Q18: Post-mortem collaboration (cross-entity graph)
    (
        "Who worked together on the Redis post-mortem?",
        ["carlos", "bob", "post-mortem"],
    ),
    # Q19: Coding preferences
    ("What Python coding style does the user prefer?", ["type hints", "exception"]),
    # Q20: Knowledge graph architecture
    ("How does the knowledge graph integration work?", ["neo4j", "docker", "graph"]),
]


def _kw_match(kw: str, text: str) -> bool:
    kl = kw.lower()
    return kl in text or kl.replace("-", " ") in text or kl.replace(" ", "-") in text


def run_agent_question(question: str, timeout: int, qnum: int) -> tuple[str, float]:
    """Send a question to the agent CLI and return (response, elapsed_seconds)."""
    env = os.environ.copy()
    env["NANOBOT_GRAPH_ENABLED"] = "true"

    start = time.time()
    result = subprocess.run(
        [
            sys.executable, "-m", "nanobot", "agent",
            "-m", question,
            "--no-markdown",
            "--timeout", str(timeout),
            "--no-logs",
            "-s", f"cli:eval-q{qnum}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout + 30,
        env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    elapsed = time.time() - start
    output = result.stdout.strip()
    if result.returncode != 0 and not output:
        output = f"[ERROR rc={result.returncode}] {result.stderr.strip()[:500]}"
    return output, elapsed


def main() -> None:
    timeout = 60
    if "--timeout" in sys.argv:
        idx = sys.argv.index("--timeout")
        timeout = int(sys.argv[idx + 1])

    print("=" * 80)
    print("LIVE AGENT EVALUATION — 20 Memory Questions")
    print(f"Timeout per question: {timeout}s")
    print("=" * 80)

    results: list[dict] = []
    total_recall = 0.0
    perfect = 0
    graph_mentions = 0

    for i, (question, expected) in enumerate(QUESTIONS, 1):
        print(f"\n{'─' * 70}")
        print(f"Q{i:02d}: {question}")
        print(f"{'─' * 70}")

        try:
            response, elapsed = run_agent_question(question, timeout, i)
        except subprocess.TimeoutExpired:
            response = "[TIMEOUT]"
            elapsed = float(timeout)

        resp_lower = response.lower()
        hits = [kw for kw in expected if _kw_match(kw, resp_lower)]
        misses = [kw for kw in expected if not _kw_match(kw, resp_lower)]
        recall = len(hits) / len(expected) if expected else 1.0
        total_recall += recall
        if recall == 1.0:
            perfect += 1

        has_graph_content = any(
            term in resp_lower
            for term in ["graph", "neo4j", "triple", "entity graph", "knowledge graph"]
        )
        if has_graph_content:
            graph_mentions += 1

        status = "✓ PERFECT" if recall == 1.0 else f"✗ {recall:.0%}"
        print(f"\n  Agent ({elapsed:.1f}s):")
        # Print first 500 chars of response
        for line in response[:800].split("\n"):
            print(f"    {line}")
        if len(response) > 800:
            print(f"    ... [{len(response)} chars total]")
        print(f"\n  Keywords: {status}")
        print(f"    Hits:   {hits}")
        if misses:
            print(f"    Misses: {misses}")

        results.append({
            "q": i,
            "question": question,
            "expected": expected,
            "hits": hits,
            "misses": misses,
            "recall": recall,
            "elapsed": round(elapsed, 1),
            "response_len": len(response),
        })

    # ── Summary ──
    avg_recall = total_recall / len(QUESTIONS)
    avg_time = sum(r["elapsed"] for r in results) / len(results)

    print("\n" + "=" * 80)
    print("SCORECARD")
    print("=" * 80)
    print(f"  Questions:      {len(QUESTIONS)}")
    print(f"  Perfect (100%): {perfect}/{len(QUESTIONS)}")
    print(f"  Average recall: {avg_recall:.2%}")
    print(f"  Graph mentions: {graph_mentions}/{len(QUESTIONS)}")
    print(f"  Avg response:   {avg_time:.1f}s")
    print()

    # Per-question summary table
    print(f"  {'Q':>3}  {'Recall':>7}  {'Time':>6}  {'Status'}")
    print(f"  {'─'*3}  {'─'*7}  {'─'*6}  {'─'*20}")
    for r in results:
        status = "✓" if r["recall"] == 1.0 else f"✗ miss: {r['misses']}"
        print(f"  Q{r['q']:02d}  {r['recall']:>6.0%}  {r['elapsed']:>5.1f}s  {status}")

    print(f"\n  OVERALL: {avg_recall:.2%} recall, {perfect}/{len(QUESTIONS)} perfect")

    # Save JSON results
    out_path = Path(__file__).resolve().parent.parent / "artifacts" / "live_eval_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "avg_recall": round(avg_recall, 4),
        "perfect": perfect,
        "total": len(QUESTIONS),
        "graph_mentions": graph_mentions,
        "avg_elapsed": round(avg_time, 1),
        "results": results,
    }, indent=2) + "\n")
    print(f"\n  Results saved to {out_path}")


if __name__ == "__main__":
    main()
