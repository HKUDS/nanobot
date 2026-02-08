# nanobot/agent/tools/memory_box/bench.py
"""
memory_box.bench

Production benchmark + correctness harness for `MemoryStore`.

This module is intended to be:
- **Deterministic** (seeded RNG, reproducible runs)
- **Black-box** (tests `MemoryStore` via public APIs only)
- **Meaningful** (measures both performance and retrieval quality)
- **Safe to run** (optional `--clean` to delete the workspace)

What this bench DOES
--------------------
1) Data generation (N items)
   - Writes `--items` synthetic memory entries through `MemoryStore.remember()`.
   - Each entry contains:
       * 2 tags from a small controlled vocab (#tag)
       * 1 person token from a small controlled vocab (@person)
       * 1 unique keyword token per entry (ground-truth key for retrieval)
   - Optionally adds ambiguity/noise (`--hard`) by injecting shared tokens into many entries.

2) Retrieval quality (Q queries)
   - Positive queries:
       * Query by the unique token (and optionally with typos: `--typo_rate`)
       * Metrics:
           - Recall@K   : fraction where expected id appears in top-K
           - Top-1 acc  : fraction where expected id is rank-1
           - MRR        : mean reciprocal rank of the expected id
   - Mixed queries:
       * Same unique token PLUS structured filters:
           kind:..., scope:..., #tag, @person
       * Ensures query parsing and filter semantics are correct under FTS ranking.
   - Negative queries:
       * Random tokens not present in the corpus
       * Metric:
           - True-negative rate: fraction returning 0 hits

3) Invariants / behavioral contracts
   - Promote invariant:
       * promote(remove=True) must move an item to scope:long such that:
           - `scope:long <token>` finds it
           - `scope:daily <token>` does NOT find it
   - Soft-forget invariant:
       * After soft_forget(id):
           - active recall must NOT return the id
           - include_trash recall MUST return the id
       * After restore(id):
           - active recall MUST return the id again

4) Agent tag-hygiene (Source-D style)
   - `vocab()` returns non-empty tag/person frequency tables.
   - `suggest_tags(text)` prefers reusing existing tags when overlap exists.
   - Stopword-only text yields no suggested tags.

Performance outputs
-------------------
- Mean write latency (ms)
- Mean query latency (ms) for each query class:
    pos(uniq), mixed, neg, and (optionally) tag-only density probe

Why scores can be "too perfect"
------------------------------
If your corpus includes truly UNIQUE tokens and queries use those tokens exactly,
a correct FTS-backed system should achieve ~100% Recall@K and Top-1.

To make the benchmark non-trivial, enable:
- `--hard`              : injects shared tokens into many items (ambiguity)
- `--typo_rate 0.05`    : injects single-character typos in positive queries

Recommended runs
----------------
Quick sanity (small, fast):
  python -m nanobot.agent.tools.memory_box.bench --clean --items 2000 --queries 400 --seed 0

Non-trivial quality (ambiguity + typos):
  python -m nanobot.agent.tools.memory_box.bench --clean --hard --typo_rate 0.10

Stress (bigger):
  python -m nanobot.agent.tools.memory_box.bench \\
    --workspace ./tmp/memory_box_bench --clean \\
    --items 20000 --queries 2000 --k 5 --neg_frac 0.50 --promote_frac 0.05 \\
    --hard --hard_shared_frac 0.60 --typo_rate 0.10

Notes / pitfalls
----------------
- Run from the project root (e.g. `/docker/nanobot`) so imports resolve cleanly.
- Do NOT name any module `types.py` in this package; it can shadow stdlib `types`
  depending on CWD, causing `MappingProxyType` import errors.
- When FTS5 is unavailable, `MemoryStore` falls back to file scan recall; this
  bench still runs but performance and ranking quality will differ.

Author: Arghya Ranjan Das
"""


from __future__ import annotations

import argparse
import random
import string
import time
import shutil
from pathlib import Path
from statistics import mean

from .store import MemoryStore


_ADJ = [
    "amber", "brisk", "calm", "dapper", "eager", "fuzzy", "gentle", "hazy",
    "ivory", "jolly", "kind", "lunar", "mellow", "nimble", "opal", "plucky",
]
_NOUN = [
    "lantern", "river", "atlas", "garden", "puzzle", "comet", "bicycle", "orchid",
    "canyon", "harbor", "kettle", "meadow", "notebook", "paradox", "compass", "teapot",
]
_NAMES = ["alex", "sam", "taylor", "jordan", "casey", "morgan", "riley", "quinn", "sky", "jamie"]


def _bar(i: int, n: int, desc: str) -> None:
    w = 28
    frac = 0.0 if n <= 0 else i / n
    fill = int(w * frac)
    s = "[" + ("#" * fill) + ("." * (w - fill)) + f"] {int(100 * frac):3d}% {desc}"
    print("\r" + s, end="", flush=True)
    if i >= n:
        print()


def _rand_text(k: int = 10) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(k))


def _rand_tag() -> str:
    return f"{random.choice(_ADJ)}_{random.choice(_NOUN)}"


def _make_vocab(n_tags: int = 12, n_people: int = 6) -> tuple[list[str], list[str]]:
    tags = sorted({_rand_tag() for _ in range(max(1, n_tags * 3))})[:n_tags]
    people = random.sample(_NAMES, k=min(len(_NAMES), max(1, n_people)))
    return tags, people


def _maybe_typo(s: str, p: float, rng: random.Random) -> str:
    """With probability p, introduce one small typo into the string."""
    if not s or rng.random() > p:
        return s
    i = rng.randrange(len(s))
    c = rng.choice(string.ascii_lowercase)
    return s[:i] + c + s[i + 1 :]


def run_bench(
    workspace: Path,
    n_items: int,
    n_queries: int,
    seed: int,
    *,
    k: int = 5,
    neg_frac: float = 0.35,
    promote_frac: float = 0.05,
    promote_remove: bool = True,
    hard: bool = False,
    hard_shared_frac: float = 0.30,
    typo_rate: float = 0.0,
) -> int:
    rng = random.Random(seed)

    m = MemoryStore(workspace)
    tags, ppl = _make_vocab(n_tags=12, n_people=6)

    ids: list[str] = []
    t_write: list[float] = []

    # ground truth map: unique token -> id
    token_to_id: dict[str, str] = {}
    id_to_meta: dict[str, dict[str, str]] = {}

    # HARD MODE: shared tokens used by many items to create ambiguity
    shared_tokens = [f"s_{_rand_text(6)}" for _ in range(12)] if hard else []

    for i in range(n_items):
        _bar(i, n_items, "writing")

        tag1 = rng.choice(tags)
        tag2 = rng.choice(tags)
        person = rng.choice(ppl)

        uniq = f"u_{i}_{_rand_text(10)}"

        # Add ambiguity if hard-mode:
        extra = ""
        if hard and (rng.random() < hard_shared_frac):
            extra = " " + " ".join(rng.sample(shared_tokens, k=rng.randint(1, 3)))

        txt = (
            f"note: {_rand_text(12)} {_rand_text(12)} "
            f"{uniq}{extra} "
            f"#{tag1} #{tag2} @{person}"
        )

        t0 = time.perf_counter()
        mid = m.remember(txt, kind="note", scope="daily")
        t_write.append(time.perf_counter() - t0)

        ids.append(mid)
        token_to_id[uniq] = mid
        id_to_meta[mid] = {"tag1": tag1, "tag2": tag2, "person": person, "uniq": uniq}

    _bar(n_items, n_items, "writing")

    # Promote
    n_promote = max(0, int(round(promote_frac * n_items)))
    promoted = []
    for i, mid in enumerate(ids[:n_promote]):
        _bar(i, max(1, n_promote), "promoting")
        m.promote(mid, remove=promote_remove)
        promoted.append(mid)
    _bar(n_promote, max(1, n_promote), "promoting")

    # Query sets
    n_neg = int(round(neg_frac * n_queries))
    n_pos = max(0, n_queries - n_neg)

    all_tokens = list(token_to_id.keys())
    pos_tokens = [rng.choice(all_tokens) for _ in range(n_pos)]
    neg_tokens = [f"zz_{_rand_text(12)}_{_rand_text(12)}" for _ in range(n_neg)]
    mixed_tokens = pos_tokens[: max(1, len(pos_tokens) // 2)] if pos_tokens else []

    def _eval_positive(q: str, expected_id: str) -> tuple[bool, bool, float]:
        hits = m.recall(q, limit=k)
        if not hits:
            return (False, False, 0.0)
        top1 = (hits[0].id == expected_id)
        for r, h in enumerate(hits, start=1):
            if h.id == expected_id:
                return (True, top1, 1.0 / r)
        return (False, top1, 0.0)

    def _eval_negative(q: str) -> bool:
        hits = m.recall(q, limit=k)
        return len(hits) == 0

    # Run tests
    t_q_pos, t_q_mix, t_q_neg = [], [], []
    found = top1 = 0
    mrr_sum = 0.0
    found_mix = top1_mix = 0
    mrr_mix_sum = 0.0
    tn = 0

    # pos (uniq)
    for i, tok in enumerate(pos_tokens):
        _bar(i, max(1, len(pos_tokens)), "recall+ (uniq)")
        expected = token_to_id[tok]
        q = _maybe_typo(tok, typo_rate, rng)
        t0 = time.perf_counter()
        ok_k, ok_1, rr = _eval_positive(q, expected)
        t_q_pos.append(time.perf_counter() - t0)
        found += int(ok_k); top1 += int(ok_1); mrr_sum += rr
    _bar(len(pos_tokens), max(1, len(pos_tokens)), "recall+ (uniq)")

    # mixed
    for i, tok in enumerate(mixed_tokens):
        _bar(i, max(1, len(mixed_tokens)), "recall+ (mixed)")
        expected = token_to_id[tok]
        meta = id_to_meta[expected]
        tag = meta["tag1"] if (rng.random() < 0.5) else meta["tag2"]
        person = meta["person"]
        scope = "long" if (expected in promoted and promote_remove) else "daily"
        q = f"kind:note scope:{scope} #{tag} @{person} {_maybe_typo(tok, typo_rate, rng)}"
        t0 = time.perf_counter()
        ok_k, ok_1, rr = _eval_positive(q, expected)
        t_q_mix.append(time.perf_counter() - t0)
        found_mix += int(ok_k); top1_mix += int(ok_1); mrr_mix_sum += rr
    _bar(len(mixed_tokens), max(1, len(mixed_tokens)), "recall+ (mixed)")

    # neg
    for i, tok in enumerate(neg_tokens):
        _bar(i, max(1, len(neg_tokens)), "recall- (neg)")
        t0 = time.perf_counter()
        ok = _eval_negative(tok)
        t_q_neg.append(time.perf_counter() - t0)
        tn += int(ok)
    _bar(len(neg_tokens), max(1, len(neg_tokens)), "recall- (neg)")

    # Invariants
    promote_ok = None
    if promoted:
        midp = promoted[len(promoted) // 2]
        tokp = id_to_meta[midp]["uniq"]
        hits_long = m.recall(f"scope:long {tokp}", limit=k)
        got_long = any(h.id == midp for h in hits_long)
        if promote_remove:
            hits_daily = m.recall(f"scope:daily {tokp}", limit=k)
            got_daily = any(h.id == midp for h in hits_daily)
            promote_ok = (got_long and (not got_daily))
        else:
            promote_ok = got_long

    # soft_forget/restore
    mid_sample = ids[n_items // 2]
    tok_sample = id_to_meta[mid_sample]["uniq"]
    m.soft_forget(mid_sample)
    gone_from_active = all(h.id != mid_sample for h in m.recall(tok_sample, limit=k, include_trash=False))
    visible_in_trash = any(h.id == mid_sample for h in m.recall(tok_sample, limit=k, include_trash=True))
    m.restore(mid_sample)
    back_in_active = any(h.id == mid_sample for h in m.recall(tok_sample, limit=k, include_trash=False))

    # Source-D tests: vocab + suggest_tags
    v = m.vocab(rows=min(5000, n_items), include_trash=False)
    vocab_ok = ("tags" in v and "people" in v and len(v["tags"]) > 0 and len(v["people"]) > 0)

    mid0 = ids[n_items // 3]
    meta0 = id_to_meta[mid0]
    tag_a = meta0["tag1"]
    tag_b = meta0["tag2"]
    person0 = meta0["person"]

    parts_a = tag_a.split("_")
    parts_b = tag_b.split("_")
    text_for_suggest = f"note: discuss {parts_a[0]} {parts_a[1]} {parts_b[0]} with {person0} today okay"
    sug = m.suggest_tags(text_for_suggest, max_tags=2, min_count=1)
    suggest_ok = ((tag_a in sug) or (tag_b in sug))

    stop_only = "note: okay yes today tomorrow now later"
    sug2 = m.suggest_tags(stop_only, max_tags=2, min_count=1)
    stop_ok = (sug2 == [])

    # Report
    def _safe_div(a: float, b: float) -> float:
        return a / b if b else 0.0

    print("\n--- results ---")
    print(f"workspace: {workspace.resolve()}")
    print(f"seed: {seed}")
    print(f"items: {n_items}, queries: {n_queries}, k: {k}")
    print(f"promote_frac: {promote_frac:.3f} (n={n_promote}), promote_remove: {promote_remove}")
    print(f"neg_frac: {neg_frac:.3f} (neg={n_neg}, pos={n_pos})")
    print(f"hard_mode: {hard} (shared_frac={hard_shared_frac:.2f}, typo_rate={typo_rate:.2f})")

    print(f"\nwrite mean ms: {1000 * mean(t_write):.2f}")

    if t_q_pos:
        print(f"pos(uniq) mean ms: {1000 * mean(t_q_pos):.2f}")
        print(f"pos(uniq) Recall@{k}: {found}/{len(pos_tokens)} = {_safe_div(found, len(pos_tokens)):.2%}")
        print(f"pos(uniq) Top-1 acc:  {top1}/{len(pos_tokens)} = {_safe_div(top1, len(pos_tokens)):.2%}")
        print(f"pos(uniq) MRR:        {_safe_div(mrr_sum, len(pos_tokens)):.4f}")

    if t_q_mix:
        print(f"\nmixed mean ms: {1000 * mean(t_q_mix):.2f}")
        print(f"mixed Recall@{k}: {found_mix}/{len(mixed_tokens)} = {_safe_div(found_mix, len(mixed_tokens)):.2%}")
        print(f"mixed Top-1 acc:  {top1_mix}/{len(mixed_tokens)} = {_safe_div(top1_mix, len(mixed_tokens)):.2%}")
        print(f"mixed MRR:        {_safe_div(mrr_mix_sum, len(mixed_tokens)):.4f}")

    if t_q_neg:
        print(f"\nneg mean ms: {1000 * mean(t_q_neg):.2f}")
        print(f"neg TrueNeg rate: {tn}/{len(neg_tokens)} = {_safe_div(tn, len(neg_tokens)):.2%}")

    print("\n--- invariants ---")
    if promote_ok is None:
        print("promote invariant: (skipped; n_promote=0)")
    else:
        print(f"promote invariant (scope correctness): {promote_ok}")

    print(
        "soft_forget/restore:"
        f" gone_from_active={gone_from_active}"
        f" visible_in_trash={visible_in_trash}"
        f" back_in_active={back_in_active}"
    )

    print("\n--- source-D (agent tag hygiene) ---")
    print(f"vocab_ok: {vocab_ok}")
    print(f"suggest_reuse_ok: {suggest_ok}  (suggested={sug})")
    print(f"stopwords_ok: {stop_ok}  (stop_suggested={sug2})")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="./tmp/memory_box_bench", help="workspace folder (default: ./tmp/memory_box_bench)")
    ap.add_argument("--items", type=int, default=2000)
    ap.add_argument("--queries", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)

    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--neg_frac", type=float, default=0.35)
    ap.add_argument("--promote_frac", type=float, default=0.05)

    ap.add_argument("--promote_remove", action="store_true")
    ap.add_argument("--no_promote_remove", action="store_true")

    ap.add_argument("--hard", action="store_true", help="enable ambiguity/noise so results are not trivially perfect")
    ap.add_argument("--hard_shared_frac", type=float, default=0.30, help="fraction of items given shared tokens (hard mode)")
    ap.add_argument("--typo_rate", type=float, default=0.00, help="probability of 1-char typo in positive tokens")

    ap.add_argument("--clean", action="store_true", help="delete workspace before run")

    args = ap.parse_args()

    ws = Path(args.workspace)
    promote_remove = True
    if args.no_promote_remove:
        promote_remove = False
    if args.promote_remove:
        promote_remove = True

    if args.clean and ws.exists():
        shutil.rmtree(ws)

    ws.mkdir(parents=True, exist_ok=True)

    return run_bench(
        ws,
        args.items,
        args.queries,
        args.seed,
        k=args.k,
        neg_frac=args.neg_frac,
        promote_frac=args.promote_frac,
        promote_remove=promote_remove,
        hard=args.hard,
        hard_shared_frac=args.hard_shared_frac,
        typo_rate=args.typo_rate,
    )


if __name__ == "__main__":
    raise SystemExit(main())
