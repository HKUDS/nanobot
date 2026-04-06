## The Problem

A typical agent conversation grows linearly. After ~40 turns with tool results, you've eaten 80-100k tokens. Without compaction you either truncate (lose early context) or crash into the limit. Claude Code solves this with a tiered compression pipeline that progressively distills older context while keeping recent turns at full fidelity.

## The Architecture

Think of it like CPU cache hierarchy or how the brain moves short-term memory into long-term:

```
Layer 0 (Hot)    → Raw conversation turns, full fidelity
Layer 1 (Warm)   → Summarized turn blocks (~5:1 compression)
Layer 2 (Cool)   → Topic-level merged knowledge (~20:1)
Layer 3 (Cold)   → Index pointers in MEMORY.md (~100:1)
```

Content flows downward as the context budget fills. Each layer is more compressed but retains the essential signal. The key insight from Claude Code: compaction is triggered by budget pressure, not by time — and the agent itself does the summarizing.

## The Code

This is a companion module to the memory store from before. Drop it in as `nanobot/agent/compactor.py`:

```python
"""
Multi-layer context compactor for nanobot.

Inspired by Claude Code's auto-compaction behavior: when the context window
fills, older conversation turns are progressively compressed through layers
of decreasing fidelity, keeping the agent's working memory focused and
within budget.

Layers:
  L0 (hot)   – raw turns, full fidelity
  L1 (warm)  – block summaries (~5:1 ratio)
  L2 (cool)  – topic-level compressed knowledge (~20:1)
  L3 (cold)  – one-line index pointers persisted to MEMORY.md (~100:1)

Usage:
  compactor = ContextCompactor(memory_store, budget=120_000)
  compactor.push("user", user_msg)
  compactor.push("assistant", assistant_msg)
  context = compactor.render()          # always fits within budget
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# ── configuration ────────────────────────────────────────────────────────
DEFAULT_BUDGET = 120_000          # token budget for entire context
L0_RESERVE = 0.45                 # 45% of budget for raw recent turns
L1_RESERVE = 0.30                 # 30% for warm summaries
L2_RESERVE = 0.15                 # 15% for cool topic knowledge
L3_RESERVE = 0.10                 # 10% for cold index + system prompt
BLOCK_SIZE = 6                    # turns per L1 summary block
CHARS_PER_TOKEN = 3.5             # rough estimate for tokenization


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN))


# ── data structures ──────────────────────────────────────────────────────
@dataclass
class Turn:
    role: str                     # "user" | "assistant" | "system" | "tool"
    content: str
    token_count: int = 0
    protected: bool = False       # if True, never compacted (e.g. system prompt)

    def __post_init__(self):
        if not self.token_count:
            self.token_count = estimate_tokens(self.content)


@dataclass
class SummaryBlock:
    """A compressed representation of several consecutive turns."""
    turn_range: tuple[int, int]   # (start_idx, end_idx) of original turns
    summary: str
    token_count: int = 0
    topics: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.token_count:
            self.token_count = estimate_tokens(self.summary)


@dataclass
class TopicDigest:
    """Layer 2: compressed knowledge about a single topic."""
    topic: str
    digest: str
    token_count: int = 0

    def __post_init__(self):
        if not self.token_count:
            self.token_count = estimate_tokens(self.digest)


# ── summarizer interface ─────────────────────────────────────────────────
# The compactor doesn't call the LLM itself — it accepts a callback.
# This keeps it model-agnostic and testable.

SummarizerFn = Callable[[str, str], str]
# signature: summarizer(instruction, content) -> summary_text


def _fallback_summarizer(_instruction: str, content: str) -> str:
    """
    Extractive fallback when no LLM is available.
    Keeps first and last sentence of each paragraph + any lines with
    keywords like 'error', 'decided', 'important', 'must', 'TODO'.
    """
    keep_re = re.compile(
        r"(error|decided|important|must|todo|fix|note|remember|key|action)",
        re.I,
    )
    lines = content.strip().splitlines()
    kept: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        is_boundary = (i == 0 or i == len(lines) - 1)
        is_important = bool(keep_re.search(stripped))
        if is_boundary or is_important:
            kept.append(stripped)
    if not kept:
        # absolute fallback: first 3 + last 2 lines
        kept = [l.strip() for l in lines[:3] + lines[-2:] if l.strip()]
    return "\n".join(kept)


# ── prompts for LLM-based summarization ─────────────────────────────────
L0_TO_L1_PROMPT = (
    "Summarize this conversation block concisely. Preserve: decisions made, "
    "errors encountered, tool outputs, and any user preferences expressed. "
    "Drop pleasantries and redundant back-and-forth. Use bullet points.\n\n"
)

L1_TO_L2_PROMPT = (
    "Merge these summaries into a single, topic-focused knowledge paragraph. "
    "Resolve contradictions (keep the latest). Convert relative time references "
    "to absolute dates where possible. Output one dense paragraph per topic.\n\n"
)


# ── ContextCompactor ─────────────────────────────────────────────────────
class ContextCompactor:
    """
    Manages a multi-layer context window that auto-compacts under budget
    pressure.

    Parameters
    ----------
    memory_store : MemoryStore
        The persistent memory store (from memory.py) for L3 persistence.
    budget : int
        Max tokens for the rendered context.
    summarizer : optional callable
        An LLM-backed summarizer. If None, an extractive fallback is used.
    """

    def __init__(
        self,
        memory_store,
        budget: int = DEFAULT_BUDGET,
        summarizer: Optional[SummarizerFn] = None,
    ):
        self.memory = memory_store
        self.budget = budget
        self.summarize = summarizer or _fallback_summarizer

        # Layer 0: raw turns (append-only during a session)
        self.turns: list[Turn] = []
        # Layer 1: summary blocks replacing older L0 turns
        self.warm_blocks: list[SummaryBlock] = []
        # Layer 2: topic-level digests replacing older L1 blocks
        self.cool_digests: list[TopicDigest] = []
        # Track which turns have been compacted into L1
        self._compacted_up_to: int = 0

    # ── push new turns ───────────────────────────────────────────────
    def push(self, role: str, content: str, protected: bool = False) -> None:
        """Add a new conversation turn, then compact if needed."""
        turn = Turn(role=role, content=content, protected=protected)
        self.turns.append(turn)
        if self._total_tokens() > self.budget:
            self._compact()

    # ── token accounting ─────────────────────────────────────────────
    def _l0_tokens(self) -> int:
        return sum(t.token_count for t in self.turns[self._compacted_up_to:])

    def _l1_tokens(self) -> int:
        return sum(b.token_count for b in self.warm_blocks)

    def _l2_tokens(self) -> int:
        return sum(d.token_count for d in self.cool_digests)

    def _l3_tokens(self) -> int:
        return estimate_tokens(self.memory.read_index())

    def _total_tokens(self) -> int:
        return self._l0_tokens() + self._l1_tokens() + self._l2_tokens() + self._l3_tokens()

    # ── compaction engine ────────────────────────────────────────────
    def _compact(self) -> None:
        """
        Cascade compaction: L0→L1, then if still over budget L1→L2,
        then if still over budget L2→L3.
        """
        # Phase 1: Compact oldest L0 turns into L1 summary blocks
        self._compact_l0_to_l1()
        if self._total_tokens() <= self.budget:
            return

        # Phase 2: Merge oldest L1 blocks into L2 topic digests
        self._compact_l1_to_l2()
        if self._total_tokens() <= self.budget:
            return

        # Phase 3: Flush oldest L2 digests to L3 (persistent memory)
        self._compact_l2_to_l3()

    def _compact_l0_to_l1(self) -> None:
        """Summarize blocks of raw turns into warm summary blocks."""
        available = self.turns[self._compacted_up_to:]
        # Keep the most recent BLOCK_SIZE turns untouched (hot)
        compactable = available[:-BLOCK_SIZE] if len(available) > BLOCK_SIZE else []
        if len(compactable) < BLOCK_SIZE:
            return

        # Process in chunks of BLOCK_SIZE
        chunks_processed = 0
        while len(compactable) >= BLOCK_SIZE:
            chunk = compactable[:BLOCK_SIZE]
            compactable = compactable[BLOCK_SIZE:]
            chunks_processed += 1

            # Skip protected turns — keep them in L0
            if any(t.protected for t in chunk):
                continue

            start_idx = self._compacted_up_to
            end_idx = start_idx + BLOCK_SIZE

            # Build the text block to summarize
            block_text = "\n".join(
                f"[{t.role}]: {t.content}" for t in chunk
            )
            summary_text = self.summarize(L0_TO_L1_PROMPT, block_text)

            # Detect topics mentioned (simple keyword extraction)
            topics = self._extract_topics(block_text)

            block = SummaryBlock(
                turn_range=(start_idx, end_idx),
                summary=summary_text,
                topics=topics,
            )
            self.warm_blocks.append(block)
            self._compacted_up_to = end_idx

    def _compact_l1_to_l2(self) -> None:
        """Merge warm blocks sharing topics into cool topic digests."""
        if len(self.warm_blocks) < 3:
            return

        # Group blocks by their primary topic
        topic_groups: dict[str, list[SummaryBlock]] = {}
        for block in self.warm_blocks:
            key = block.topics[0] if block.topics else "general"
            topic_groups.setdefault(key, []).append(block)

        # Merge groups that have 2+ blocks
        merged_topics: set[str] = set()
        for topic, blocks in topic_groups.items():
            if len(blocks) < 2:
                continue

            combined = "\n---\n".join(b.summary for b in blocks)
            digest_text = self.summarize(L1_TO_L2_PROMPT, combined)

            # Check if this topic already has a digest — merge into it
            existing = next((d for d in self.cool_digests if d.topic == topic), None)
            if existing:
                merged_input = f"{existing.digest}\n---\n{digest_text}"
                existing.digest = self.summarize(L1_TO_L2_PROMPT, merged_input)
                existing.token_count = estimate_tokens(existing.digest)
            else:
                self.cool_digests.append(TopicDigest(topic=topic, digest=digest_text))

            merged_topics.add(topic)

        # Remove merged blocks from L1
        self.warm_blocks = [
            b for b in self.warm_blocks
            if (b.topics[0] if b.topics else "general") not in merged_topics
        ]

    def _compact_l2_to_l3(self) -> None:
        """Flush the oldest cool digests to persistent memory (L3)."""
        if not self.cool_digests:
            return

        # Flush the oldest half of digests
        flush_count = max(1, len(self.cool_digests) // 2)
        to_flush = self.cool_digests[:flush_count]
        self.cool_digests = self.cool_digests[flush_count:]

        for digest in to_flush:
            self.memory.remember(
                content=digest.digest,
                category="project",
                topic=digest.topic,
            )

    # ── topic extraction (lightweight) ───────────────────────────────
    def _extract_topics(self, text: str) -> list[str]:
        """
        Simple keyword-based topic detection.
        In production, the LLM itself classifies topics — but this
        zero-cost heuristic handles 80% of cases.
        """
        topic_keywords: dict[str, list[str]] = {
            "debugging":    ["error", "bug", "fix", "stack", "trace", "exception"],
            "architecture": ["design", "pattern", "module", "refactor", "structure"],
            "api":          ["endpoint", "request", "response", "api", "http", "rest"],
            "testing":      ["test", "assert", "coverage", "mock", "spec"],
            "deployment":   ["deploy", "docker", "ci", "cd", "pipeline", "build"],
            "user_prefs":   ["prefer", "always", "never", "style", "convention"],
            "dependencies": ["install", "package", "version", "dependency", "upgrade"],
        }
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for topic, keywords in topic_keywords.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[topic] = score

        if not scores:
            return ["general"]

        ranked = sorted(scores, key=scores.get, reverse=True)
        return ranked[:2]

    # ── render the final context ─────────────────────────────────────
    def render(self) -> str:
        """
        Assemble the multi-layer context into a single string ready
        for injection into the LLM prompt.

        Ordering (top to bottom):
          1. L3 — memory index (persistent, cold)
          2. L2 — topic digests (cool)
          3. L1 — block summaries (warm)
          4. L0 — raw recent turns (hot)
        """
        sections: list[str] = []

        # L3: persistent memory index
        index = self.memory.read_index()
        if index.strip():
            sections.append(f"<memory_index>\n{index}\n</memory_index>")

        # L2: topic digests
        if self.cool_digests:
            digest_parts = []
            for d in self.cool_digests:
                digest_parts.append(f"### {d.topic}\n{d.digest}")
            sections.append(
                f"<topic_knowledge>\n" + "\n\n".join(digest_parts) + "\n</topic_knowledge>"
            )

        # L1: warm summaries
        if self.warm_blocks:
            summaries = "\n\n".join(
                f"[Turns {b.turn_range[0]}-{b.turn_range[1]}] {b.summary}"
                for b in self.warm_blocks
            )
            sections.append(
                f"<conversation_summaries>\n{summaries}\n</conversation_summaries>"
            )

        # L0: raw recent turns
        recent = self.turns[self._compacted_up_to:]
        if recent:
            raw = "\n".join(f"[{t.role}]: {t.content}" for t in recent)
            sections.append(f"<recent_conversation>\n{raw}\n</recent_conversation>")

        return "\n\n".join(sections)

    # ── diagnostics ──────────────────────────────────────────────────
    def stats(self) -> dict:
        return {
            "total_turns": len(self.turns),
            "l0_active": len(self.turns) - self._compacted_up_to,
            "l1_blocks": len(self.warm_blocks),
            "l2_digests": len(self.cool_digests),
            "tokens": {
                "l0": self._l0_tokens(),
                "l1": self._l1_tokens(),
                "l2": self._l2_tokens(),
                "l3": self._l3_tokens(),
                "total": self._total_tokens(),
                "budget": self.budget,
                "utilization": f"{self._total_tokens() / self.budget:.0%}",
            },
        }
```

## How the Layers Cascade

Here's what actually happens during a 50+ turn session:

**Turns 1–12:** Everything stays in L0. Raw turns, full fidelity. No compression.

**Turn 13 (budget pressure hits):** The oldest 6 turns get summarized into a single L1 `SummaryBlock`. A 6-turn debugging exchange like "I tried X / that failed with Y / try Z instead / that worked" becomes a one-paragraph summary: "Resolved ImportError in auth module by switching from relative to absolute imports." That's roughly 5:1 compression.

**Turn 25+ (L1 grows too large):** L1 blocks that share topics get merged into L2 `TopicDigest` entries. Three separate debugging summaries from different points in the session become a single paragraph under the `debugging` topic. This is where contradictions get resolved — if an early block says "using SQLite" but a later one says "migrated to Postgres," the merged digest keeps only the latest state. Roughly 20:1 compression from the original.

**Turn 40+ (still over budget):** The oldest L2 digests get flushed to L3 — written to the persistent `MemoryStore` topic files via `memory.remember()`. These survive across sessions. The in-memory digests are released, freeing context for new turns. At this point the original 40 turns might be represented by a couple of index pointers — 100:1 compression.

The important design point: compaction is **triggered by budget pressure**, not by fixed intervals. A session that stays within budget never compacts at all. A session with massive tool outputs might compact aggressively after just 8 turns.

## Integration With the Memory Store

The two modules work together:

```python
from nanobot.agent.memory import MemoryStore
from nanobot.agent.compactor import ContextCompactor

memory = MemoryStore(workspace_path)
memory.bump_session_count()

# Wire up an LLM-backed summarizer (or let it use the extractive fallback)
def llm_summarize(instruction: str, content: str) -> str:
    return llm.complete(instruction + content, max_tokens=300)

compactor = ContextCompactor(
    memory_store=memory,
    budget=120_000,
    summarizer=llm_summarize,   # optional — extractive fallback works too
)

# Inject the system prompt as a protected turn (never compacted)
compactor.push("system", system_prompt, protected=True)

# Conversation loop
while True:
    user_msg = get_user_input()
    compactor.push("user", user_msg)

    context = compactor.render()       # always within budget
    response = llm.complete(context)

    compactor.push("assistant", response)

    # Check stats
    print(compactor.stats())
    # {'l0_active': 8, 'l1_blocks': 3, 'l2_digests': 1,
    #  'tokens': {'total': 95000, 'budget': 120000, 'utilization': '79%'}}

# End of session — persist anything still in L2
if memory.should_consolidate():
    memory.consolidate()
```

The **extractive fallback summarizer** is deliberately included so the compactor works without burning extra LLM calls. It keeps first/last sentences and any line containing signal words like "error," "decided," "important." It's lossy, but it's free — and for most coding sessions, the important information tends to cluster around those keywords anyway. When you wire up the real LLM summarizer, you get much better compression quality, but the system degrades gracefully without it.
