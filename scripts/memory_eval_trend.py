#!/usr/bin/env python3
"""Run deterministic memory retrieval evaluation for advisory trend reporting."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.memory import MemoryStore


def _load_seed_events(seed_path: Path) -> list[dict[str, Any]]:
    """Load seed events from a JSONL file.  Falls back to legacy fixtures."""
    if not seed_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in seed_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("id"):
                events.append(obj)
        except json.JSONDecodeError:
            continue
    return events


def _load_seed_profile(profile_path: Path) -> dict[str, Any] | None:
    """Load seed profile from a JSON file."""
    if not profile_path.exists():
        return None
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic memory eval benchmark for CI")
    parser.add_argument(
        "--workspace", required=True, help="Workspace path for temporary memory files"
    )
    parser.add_argument("--cases-file", required=True, help="Benchmark cases JSON file")
    parser.add_argument(
        "--seed-events",
        default="case/memory_seed_events.jsonl",
        help="JSONL file with seed events (default: case/memory_seed_events.jsonl)",
    )
    parser.add_argument(
        "--seed-profile",
        default="case/memory_seed_profile.json",
        help="JSON file with seed profile (default: case/memory_seed_profile.json)",
    )
    parser.add_argument(
        "--baseline-file", required=False, default="", help="Baseline thresholds JSON file"
    )
    parser.add_argument("--output-file", required=True, help="Latest evaluation output JSON")
    parser.add_argument(
        "--history-file", required=True, help="Append-only history JSON file for trends"
    )
    parser.add_argument("--summary-file", required=True, help="Markdown summary output path")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--embedding-provider", default="hash")
    parser.add_argument("--vector-backend", default="json")
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="(Deprecated, ignored) Previously failed run on baseline violations",
    )
    return parser.parse_args()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path, default=[])
    raw = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise ValueError("cases file must be a JSON array or {'cases': [...]} object")
    out: list[dict[str, Any]] = []
    for item in raw:
        if (
            isinstance(item, dict)
            and isinstance(item.get("query"), str)
            and item.get("query", "").strip()
        ):
            out.append(item)
    if not out:
        raise ValueError("cases file contains no valid benchmark cases")
    return out


def _prepare_workspace(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    (path / "memory").mkdir(parents=True, exist_ok=True)


def _compare_with_baseline(
    summary: dict[str, Any], kpis: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check_min(metric: str, actual: float, threshold: float) -> None:
        checks.append(
            {
                "metric": metric,
                "actual": round(actual, 4),
                "threshold": threshold,
                "direction": "min",
                "pass": actual >= threshold,
            }
        )

    def check_max(metric: str, actual: float, threshold: float) -> None:
        checks.append(
            {
                "metric": metric,
                "actual": round(actual, 4),
                "threshold": threshold,
                "direction": "max",
                "pass": actual <= threshold,
            }
        )

    if "min_recall_at_k" in baseline:
        check_min(
            "recall_at_k",
            float(summary.get("recall_at_k", 0.0)),
            float(baseline["min_recall_at_k"]),
        )
    if "min_precision_at_k" in baseline:
        check_min(
            "precision_at_k",
            float(summary.get("precision_at_k", 0.0)),
            float(baseline["min_precision_at_k"]),
        )
    if "min_retrieval_hit_rate" in baseline:
        check_min(
            "retrieval_hit_rate",
            float(kpis.get("retrieval_hit_rate", 0.0)),
            float(baseline["min_retrieval_hit_rate"]),
        )
    if "max_contradiction_rate_per_100_messages" in baseline:
        check_max(
            "contradiction_rate_per_100_messages",
            float(kpis.get("contradiction_rate_per_100_messages", 0.0)),
            float(baseline["max_contradiction_rate_per_100_messages"]),
        )

    passed = all(item["pass"] for item in checks) if checks else True
    return {"passed": passed, "checks": checks}


def _render_summary(payload: dict[str, Any]) -> str:
    evaluation = payload["evaluation"]
    summary = evaluation.get("summary", {})
    observability = payload["observability"]
    kpis = observability.get("kpis", {})
    baseline = payload.get("baseline_comparison", {})

    lines = [
        "## Memory Eval CI Report",
        "",
        f"- Generated at: `{payload.get('generated_at', '')}`",
        f"- Cases evaluated: `{evaluation.get('cases', 0)}`",
        f"- Recall@k: `{summary.get('recall_at_k', 0.0)}`",
        f"- Precision@k: `{summary.get('precision_at_k', 0.0)}`",
        f"- Retrieval hit rate: `{kpis.get('retrieval_hit_rate', 0.0)}`",
        "",
    ]

    checks = baseline.get("checks", [])
    if checks:
        lines.append("### Baseline Checks")
        lines.append("")
        lines.append("| Metric | Actual | Threshold | Rule | Pass |")
        lines.append("|---|---:|---:|---|:---:|")
        for item in checks:
            rule = ">=" if item.get("direction") == "min" else "<="
            mark = "✅" if item.get("pass") else "❌"
            lines.append(
                f"| {item.get('metric')} | {item.get('actual')} | {item.get('threshold')} | {rule} | {mark} |"
            )
        lines.append("")
        lines.append(f"**Overall:** {'PASS ✅' if baseline.get('passed', True) else 'FAIL ❌'}")

    history = payload.get("history", [])
    if history:
        recent = history[-5:]
        lines.append("")
        lines.append("### Recent Trend")
        lines.append("")
        lines.append("| Timestamp | Recall@k | Precision@k | Hit Rate |")
        lines.append("|---|---:|---:|---:|")
        for row in recent:
            lines.append(
                f"| {row.get('generated_at', '')} | {row.get('recall_at_k', 0.0)} | {row.get('precision_at_k', 0.0)} | {row.get('retrieval_hit_rate', 0.0)} |"
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    cases_path = Path(args.cases_file).expanduser().resolve()
    baseline_path = Path(args.baseline_file).expanduser().resolve() if args.baseline_file else None
    output_path = Path(args.output_file).expanduser().resolve()
    history_path = Path(args.history_file).expanduser().resolve()
    summary_path = Path(args.summary_file).expanduser().resolve()

    cases = _load_cases(cases_path)
    _prepare_workspace(workspace)

    # Load seed events from JSONL file (covers all 25 eval cases).
    seed_events_path = Path(args.seed_events).expanduser().resolve()
    seed_events = _load_seed_events(seed_events_path)
    if not seed_events:
        print(f"WARNING: No seed events loaded from {seed_events_path}", file=sys.stderr)

    store = MemoryStore(
        workspace,
        embedding_provider=args.embedding_provider,
        vector_backend=args.vector_backend,
    )

    # Seed the profile (preferences, constraints, conflicts, relationships).
    seed_profile_path = Path(args.seed_profile).expanduser().resolve()
    seed_profile = _load_seed_profile(seed_profile_path)
    if seed_profile:
        store.profile_mgr.write_profile(seed_profile)

    from nanobot.memory.event import MemoryEvent

    store.ingester.append_events([MemoryEvent.from_dict(e) for e in seed_events])

    evaluation = asyncio.run(
        store.eval_runner.evaluate_retrieval_cases(
            cases,
            default_top_k=max(1, int(args.top_k)),
            recency_half_life_days=30.0,
            embedding_provider=args.embedding_provider,
        )
    )
    observability = store.eval_runner.get_observability_report()

    summary_metrics = evaluation.get("summary", {}) if isinstance(evaluation, dict) else {}
    kpis = observability.get("kpis", {}) if isinstance(observability, dict) else {}

    baseline_payload = _read_json(baseline_path, default={}) if baseline_path else {}
    baseline_compare = _compare_with_baseline(
        summary_metrics, kpis, baseline_payload if isinstance(baseline_payload, dict) else {}
    )

    history = _read_json(history_path, default=[])
    if not isinstance(history, list):
        history = []

    now = datetime.now(timezone.utc).isoformat()
    history.append(
        {
            "generated_at": now,
            "recall_at_k": float(summary_metrics.get("recall_at_k", 0.0)),
            "precision_at_k": float(summary_metrics.get("precision_at_k", 0.0)),
            "retrieval_hit_rate": float(kpis.get("retrieval_hit_rate", 0.0)),
        }
    )
    history = history[-50:]

    payload = {
        "generated_at": now,
        "evaluation": evaluation,
        "observability": observability,
        "baseline": baseline_payload,
        "baseline_comparison": baseline_compare,
        "history": history,
    }

    _write_json(output_path, payload)
    _write_json(history_path, history)

    summary_markdown = _render_summary(payload)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary_markdown, encoding="utf-8")
    print(summary_markdown)

    # Advisory only — always exit 0 regardless of threshold comparison.
    return 0


if __name__ == "__main__":
    sys.exit(main())
