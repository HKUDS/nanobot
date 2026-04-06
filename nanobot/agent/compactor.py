"""Multi-layer context compactor (budget-triggered L0→L1→L2→L3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from nanobot.agent.memory import MemoryStore

# Configuration (character-based token estimate; no extra deps)
DEFAULT_BUDGET = 120_000
BLOCK_SIZE = 6
CHARS_PER_TOKEN = 3.5
_MAX_COMPACT_ROUNDS = 12

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

SummarizerFn = Callable[[str, str], str]


def estimate_tokens(text: str) -> int:
    """Rough token count from character length (matches plan2 heuristic)."""
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


@dataclass
class Turn:
    """One conversation turn in the hot layer."""

    role: str
    content: str
    token_count: int = 0
    protected: bool = False

    def __post_init__(self) -> None:
        if not self.token_count:
            self.token_count = estimate_tokens(self.content)


@dataclass
class SummaryBlock:
    """Compressed representation of several consecutive turns (warm layer)."""

    turn_range: tuple[int, int]
    summary: str
    token_count: int = 0
    topics: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.token_count:
            self.token_count = estimate_tokens(self.summary)


@dataclass
class TopicDigest:
    """Topic-level digest (cool layer)."""

    topic: str
    digest: str
    token_count: int = 0

    def __post_init__(self) -> None:
        if not self.token_count:
            self.token_count = estimate_tokens(self.digest)


def _fallback_summarizer(_instruction: str, content: str) -> str:
    """Extractive fallback when no LLM summarizer is wired."""
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
        is_boundary = i == 0 or i == len(lines) - 1
        is_important = bool(keep_re.search(stripped))
        if is_boundary or is_important:
            kept.append(stripped)
    if not kept:
        kept = [ln.strip() for ln in lines[:3] + lines[-2:] if ln.strip()]
    return "\n".join(kept)


class ContextCompactor:
    """
    Tiered context window: compact older material when total estimate exceeds
    *budget*. L3 reads the persistent memory index via *memory_store.read_index*.
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        budget: int = DEFAULT_BUDGET,
        summarizer: Optional[SummarizerFn] = None,
    ) -> None:
        self.memory = memory_store
        self.budget = max(1, budget)
        self.summarize: SummarizerFn = summarizer or _fallback_summarizer

        self.turns: list[Turn] = []
        self.warm_blocks: list[SummaryBlock] = []
        self.cool_digests: list[TopicDigest] = []
        self._compacted_up_to: int = 0

    def push(self, role: str, content: str, protected: bool = False) -> None:
        """Append a turn and run compaction if over budget."""
        self.turns.append(
            Turn(role=role, content=content, protected=protected),
        )
        rounds = 0
        while self._total_tokens() > self.budget and rounds < _MAX_COMPACT_ROUNDS:
            before = self._compacted_up_to
            self._compact()
            rounds += 1
            if self._compacted_up_to == before and not self.warm_blocks:
                break

    def _l0_tokens(self) -> int:
        return sum(
            t.token_count for t in self.turns[self._compacted_up_to :]
        )

    def _l1_tokens(self) -> int:
        return sum(b.token_count for b in self.warm_blocks)

    def _l2_tokens(self) -> int:
        return sum(d.token_count for d in self.cool_digests)

    def _l3_tokens(self) -> int:
        return estimate_tokens(self.memory.read_index())

    def _total_tokens(self) -> int:
        return (
            self._l0_tokens()
            + self._l1_tokens()
            + self._l2_tokens()
            + self._l3_tokens()
        )

    def _compact(self) -> None:
        self._compact_l0_to_l1()
        if self._total_tokens() <= self.budget:
            return
        self._compact_l1_to_l2()
        if self._total_tokens() <= self.budget:
            return
        self._compact_l2_to_l3()

    def _compact_l0_to_l1(self) -> None:
        available = self.turns[self._compacted_up_to :]
        if len(available) <= BLOCK_SIZE:
            return
        compactable = available[:-BLOCK_SIZE]
        if len(compactable) < BLOCK_SIZE:
            return

        chunk = compactable[:BLOCK_SIZE]
        start_idx = self._compacted_up_to
        end_idx = start_idx + BLOCK_SIZE

        block_text = "\n".join(
            f"[{t.role}]: {t.content}" for t in chunk
        )
        if any(t.protected for t in chunk):
            summary_text = block_text
        else:
            summary_text = self.summarize(L0_TO_L1_PROMPT, block_text)

        topics = self._extract_topics(block_text)
        self.warm_blocks.append(
            SummaryBlock(
                turn_range=(start_idx, end_idx),
                summary=summary_text,
                topics=topics,
            ),
        )
        self._compacted_up_to = end_idx

    def _compact_l1_to_l2(self) -> None:
        if len(self.warm_blocks) < 3:
            return

        topic_groups: dict[str, list[SummaryBlock]] = {}
        for block in self.warm_blocks:
            key = block.topics[0] if block.topics else "general"
            topic_groups.setdefault(key, []).append(block)

        merged_topics: set[str] = set()
        for topic, blocks in topic_groups.items():
            if len(blocks) < 2:
                continue

            combined = "\n---\n".join(b.summary for b in blocks)
            digest_text = self.summarize(L1_TO_L2_PROMPT, combined)

            existing = next(
                (d for d in self.cool_digests if d.topic == topic),
                None,
            )
            if existing:
                merged_input = f"{existing.digest}\n---\n{digest_text}"
                existing.digest = self.summarize(L1_TO_L2_PROMPT, merged_input)
                existing.token_count = estimate_tokens(existing.digest)
            else:
                self.cool_digests.append(
                    TopicDigest(topic=topic, digest=digest_text),
                )

            merged_topics.add(topic)

        self.warm_blocks = [
            b
            for b in self.warm_blocks
            if (b.topics[0] if b.topics else "general") not in merged_topics
        ]

    def _compact_l2_to_l3(self) -> None:
        if not self.cool_digests:
            return

        flush_count = max(1, len(self.cool_digests) // 2)
        to_flush = self.cool_digests[:flush_count]
        self.cool_digests = self.cool_digests[flush_count:]

        for digest in to_flush:
            self.memory.remember(
                content=digest.digest,
                category="project",
                topic=digest.topic,
            )

    def _extract_topics(self, text: str) -> list[str]:
        topic_keywords: dict[str, list[str]] = {
            "debugging": [
                "error", "bug", "fix", "stack", "trace", "exception",
            ],
            "architecture": [
                "design", "pattern", "module", "refactor", "structure",
            ],
            "api": [
                "endpoint", "request", "response", "api", "http", "rest",
            ],
            "testing": [
                "test", "assert", "coverage", "mock", "spec",
            ],
            "deployment": [
                "deploy", "docker", "ci", "cd", "pipeline", "build",
            ],
            "user_prefs": [
                "prefer", "always", "never", "style", "convention",
            ],
            "dependencies": [
                "install", "package", "version", "dependency", "upgrade",
            ],
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

    def render(self) -> str:
        """Single string for injection: L3 → L2 → L1 → L0."""
        sections: list[str] = []

        index = self.memory.read_index()
        if index.strip():
            sections.append(f"<memory_index>\n{index}\n</memory_index>")

        if self.cool_digests:
            digest_parts = [
                f"### {d.topic}\n{d.digest}" for d in self.cool_digests
            ]
            sections.append(
                "<topic_knowledge>\n"
                + "\n\n".join(digest_parts)
                + "\n</topic_knowledge>",
            )

        if self.warm_blocks:
            summaries = "\n\n".join(
                f"[Turns {b.turn_range[0]}-{b.turn_range[1]}] {b.summary}"
                for b in self.warm_blocks
            )
            sections.append(
                f"<conversation_summaries>\n{summaries}\n</conversation_summaries>",
            )

        recent = self.turns[self._compacted_up_to :]
        if recent:
            raw = "\n".join(
                f"[{t.role}]: {t.content}" for t in recent
            )
            sections.append(
                f"<recent_conversation>\n{raw}\n</recent_conversation>",
            )

        return "\n\n".join(sections)

    def stats(self) -> dict[str, Any]:
        total = self._total_tokens()
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
                "total": total,
                "budget": self.budget,
                "utilization": f"{min(1.0, total / self.budget):.0%}",
            },
        }
