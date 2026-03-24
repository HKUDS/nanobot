"""LLM + heuristic extraction of structured memory events.

``MemoryExtractor`` converts raw conversation messages into structured
memory event dicts suitable for storage in ``events.jsonl``.  The pipeline:

1. **Heuristic pre-filter** — skip short/trivial messages to avoid LLM calls.
2. **LLM extraction** — ask the provider to identify entities, facts, and
   events from conversation context; output structured JSON via tool-call.
3. **Coercion + validation** — normalize extracted events (timestamps,
   entity lists, salience scores, TTL) into the canonical event schema.

Extracted events are consumed by ``MemoryStore.consolidate()`` which
persists them and updates the active knowledge snapshot.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.context.prompt_loader import prompts

from .constants import _SAVE_EVENTS_TOOL

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

# Words to skip when extracting single-capitalized-word entities
_COMMON_WORDS = frozenset(
    {
        "the",
        "this",
        "that",
        "then",
        "than",
        "they",
        "them",
        "there",
        "these",
        "those",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "also",
        "and",
        "but",
        "for",
        "from",
        "into",
        "just",
        "like",
        "not",
        "only",
        "some",
        "such",
        "very",
        "will",
        "with",
        "would",
        "could",
        "should",
        "about",
        "after",
        "before",
        "been",
        "being",
        "have",
        "here",
        "more",
        "most",
        "much",
        "over",
        "same",
        "still",
        "each",
        "even",
        "every",
        "other",
    }
)


class MemoryExtractor:
    """LLM + heuristic extraction component extracted from MemoryStore."""

    def __init__(
        self,
        *,
        to_str_list: Any,
        coerce_event: Any,
        utc_now_iso: Any,
    ):
        self.to_str_list = to_str_list
        self.coerce_event = coerce_event
        self.utc_now_iso = utc_now_iso
        self.last_extraction_source: str = ""

    @staticmethod
    def default_profile_updates() -> dict[str, list[str]]:
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }

    @staticmethod
    def parse_tool_args(args: Any) -> dict[str, Any] | None:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        return args if isinstance(args, dict) else None

    @staticmethod
    def count_user_corrections(messages: list[dict[str, Any]]) -> int:
        correction_patterns = (
            "that's wrong",
            "that is wrong",
            "you are wrong",
            "incorrect",
            "actually",
            "correction",
            "update that",
            "not true",
            "let me correct",
            "i meant",
        )
        count = 0
        for message in messages:
            if str(message.get("role", "")).lower() != "user":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            lowered = content.lower()
            if any(pattern in lowered for pattern in correction_patterns):
                count += 1
        return count

    @staticmethod
    def _clean_phrase(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value.strip().strip(".,;:!?\"'()[]{}"))
        cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def extract_explicit_preference_corrections(self, content: str) -> list[tuple[str, str]]:
        text = str(content or "").strip()
        if not text:
            return []

        matches: list[tuple[str, str]] = []
        patterns = (
            (
                r"(?:correction\s*[:,-]?\s*)?(?:i\s+(?:now\s+)?)?(?:prefer|want|use)\s+(.+?)\s*(?:,|;|\s+but)?\s*not\s+(.+?)(?:[.!?]|$)",
                "new_old",
            ),
            (
                r"(?:correction\s*[:,-]?\s*)?(?:not\s+)(.+?)\s*(?:,|;|\s+but)\s*(?:i\s+(?:now\s+)?)?(?:prefer|want|use)\s+(.+?)(?:[.!?]|$)",
                "old_new",
            ),
        )

        for pattern, order in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                if order == "new_old":
                    new_value = self._clean_phrase(match.group(1))
                    old_value = self._clean_phrase(match.group(2))
                else:
                    old_value = self._clean_phrase(match.group(1))
                    new_value = self._clean_phrase(match.group(2))
                if not new_value or not old_value:
                    continue
                if self._clean_phrase(new_value).lower() == self._clean_phrase(old_value).lower():
                    continue
                matches.append((new_value, old_value))

        dedup: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for new_value, old_value in matches:
            key = (new_value.lower(), old_value.lower())
            if key in seen:
                continue
            seen.add(key)
            dedup.append((new_value, old_value))
        return dedup

    def extract_explicit_fact_corrections(self, content: str) -> list[tuple[str, str]]:
        text = str(content or "").strip()
        if not text:
            return []

        matches: list[tuple[str, str]] = []
        patterns = (
            r"(?:correction\s*[:,-]?\s*)?(?:actually\s+)?([a-zA-Z0-9_\- ]{2,80}?)\s+is\s+(.+?)\s*(?:,|;|\s+but)?\s*not\s+(.+?)(?:[.!?]|$)",
            r"(?:correction\s*[:,-]?\s*)?(?:actually\s+)?([a-zA-Z0-9_\- ]{2,80}?)\s+is\s+not\s+(.+?)\s*(?:,|;|\s+but)\s*(?:it(?:'s| is)|is)\s+(.+?)(?:[.!?]|$)",
        )

        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                subject = self._clean_phrase(match.group(1))
                if (
                    "prefer" in subject.lower()
                    or "want" in subject.lower()
                    or "use" in subject.lower()
                ):
                    continue

                if "is not" in pattern:
                    old_value = self._clean_phrase(match.group(2))
                    new_value = self._clean_phrase(match.group(3))
                else:
                    new_value = self._clean_phrase(match.group(2))
                    old_value = self._clean_phrase(match.group(3))

                if not subject or not new_value or not old_value:
                    continue

                new_fact = f"{subject} is {new_value}"
                old_fact = f"{subject} is {old_value}"
                if self._clean_phrase(new_fact).lower() == self._clean_phrase(old_fact).lower():
                    continue
                matches.append((new_fact, old_fact))

        dedup: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for new_value, old_value in matches:
            key = (new_value.lower(), old_value.lower())
            if key in seen:
                continue
            seen.add(key)
            dedup.append((new_value, old_value))
        return dedup

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """Extract likely entity names from text via capitalized phrases and quoted strings."""
        entities: list[str] = []
        seen: set[str] = set()
        # Quoted strings (single or double)
        for match in re.finditer(r"""['"]([A-Za-z0-9_\- ]{2,60})['"]""", text):
            val = match.group(1).strip()
            if val.lower() not in seen:
                seen.add(val.lower())
                entities.append(val)
        # Capitalized multi-word phrases (e.g. "Google Chrome", "Project Alpha")
        for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
            val = match.group(1).strip()
            if val.lower() not in seen:
                seen.add(val.lower())
                entities.append(val)
        # Single capitalized words that aren't sentence starters (preceded by space)
        for match in re.finditer(r"(?<=\s)([A-Z][a-z]{2,})\b", text):
            val = match.group(1).strip()
            if val.lower() not in seen and val.lower() not in _COMMON_WORDS:
                seen.add(val.lower())
                entities.append(val)
        return entities[:10]

    _TYPE_CONFIDENCE: dict[str, float] = {
        "preference": 0.70,
        "constraint": 0.65,
        "decision": 0.55,
        "task": 0.50,
        "relationship": 0.60,
        "fact": 0.45,
    }

    # ------------------------------------------------------------------
    # Heuristic triple extraction
    # ------------------------------------------------------------------

    # Pattern → (subject group, predicate, object group)
    _TRIPLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"(\b\w[\w\s]{0,30}?)\s+works?\s+on\s+(\b\w[\w\s]{0,30})", re.I), "WORKS_ON"),
        (
            re.compile(r"(\b\w[\w\s]{0,30}?)\s+works?\s+with\s+(\b\w[\w\s]{0,30})", re.I),
            "WORKS_WITH",
        ),
        (re.compile(r"(\b\w[\w\s]{0,30}?)\s+uses?\s+(\b\w[\w\s]{0,30})", re.I), "USES"),
        (
            re.compile(
                r"(\b\w[\w\s]{0,30}?)\s+(?:is|are)\s+(?:in|at|from)\s+(\b\w[\w\s]{0,30})", re.I
            ),
            "LOCATED_IN",
        ),
        (
            re.compile(r"(\b\w[\w\s]{0,30}?)\s+(?:caused|causes)\s+(\b\w[\w\s]{0,30})", re.I),
            "CAUSED_BY",
        ),
        (
            re.compile(r"(\b\w[\w\s]{0,30}?)\s+depends?\s+on\s+(\b\w[\w\s]{0,30})", re.I),
            "DEPENDS_ON",
        ),
        (re.compile(r"(\b\w[\w\s]{0,30}?)\s+owns?\s+(\b\w[\w\s]{0,30})", re.I), "OWNS"),
        (
            re.compile(
                r"(\b\w[\w\s]{0,30}?)\s+(?:is|are)\s+constrained\s+by\s+(\b\w[\w\s]{0,30})", re.I
            ),
            "CONSTRAINED_BY",
        ),
    ]

    @classmethod
    def _extract_triples_heuristic(
        cls,
        summary: str,
        entities: list[str],
        event_type: str,
    ) -> list[dict[str, str | float]]:
        """Extract subject-predicate-object triples from text via patterns.

        Also infers triples from entity pairs when the event type implies a
        relationship (e.g. *relationship* → WORKS_WITH between first two entities).
        """
        triples: list[dict[str, str | float]] = []
        seen: set[tuple[str, str, str]] = set()

        # Pattern-based extraction
        for pattern, predicate in cls._TRIPLE_PATTERNS:
            for match in pattern.finditer(summary):
                subj = match.group(1).strip()
                obj = match.group(2).strip()
                if not subj or not obj or len(subj) < 2 or len(obj) < 2:
                    continue
                key = (subj.lower(), predicate, obj.lower())
                if key not in seen:
                    seen.add(key)
                    triples.append(
                        {
                            "subject": subj,
                            "predicate": predicate,
                            "object": obj,
                            "confidence": 0.55,
                        }
                    )

        # Infer from entity pairs + event type
        _type_predicates: dict[str, str] = {
            "relationship": "WORKS_WITH",
            "task": "WORKS_ON",
            "decision": "RELATED_TO",
        }
        if event_type in _type_predicates and len(entities) >= 2:
            pred = _type_predicates[event_type]
            subj, obj = entities[0], entities[1]
            key = (subj.lower(), pred, obj.lower())
            if key not in seen:
                seen.add(key)
                triples.append(
                    {
                        "subject": subj,
                        "predicate": pred,
                        "object": obj,
                        "confidence": 0.45,
                    }
                )

        return triples[:10]

    def heuristic_extract_events(
        self,
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        updates = self.default_profile_updates()
        events: list[dict[str, Any]] = []

        type_hints = [
            ("preference", ("prefer", "i like", "i dislike", "my preference")),
            ("constraint", ("must", "cannot", "can't", "do not", "never")),
            ("decision", ("decided", "we will", "let's", "plan is")),
            ("task", ("todo", "next step", "please", "need to")),
            ("relationship", ("is my", "works with", "project lead", "manager")),
        ]

        for offset, message in enumerate(old_messages):
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            if message.get("role") != "user":
                continue
            text = content.strip()
            if len(text) < 8:
                continue
            lowered = text.lower()

            event_type = "fact"
            for candidate, needles in type_hints:
                if any(needle in lowered for needle in needles):
                    event_type = candidate
                    break

            summary = text if len(text) <= 220 else text[:217] + "..."
            entities = self._extract_entities(text)
            confidence = self._TYPE_CONFIDENCE.get(event_type, 0.45)
            triples = self._extract_triples_heuristic(text, entities, event_type)
            source_span = [source_start + offset, source_start + offset]
            event = self.coerce_event(
                {
                    "timestamp": message.get("timestamp") or self.utc_now_iso(),
                    "type": event_type,
                    "summary": summary,
                    "entities": entities,
                    "salience": 0.55,
                    "confidence": confidence,
                    "triples": triples,
                },
                source_span=source_span,
            )
            if event:
                events.append(event)

            if event_type == "preference":
                updates["preferences"].append(summary)
            elif event_type == "constraint":
                updates["constraints"].append(summary)
            elif event_type == "relationship":
                updates["relationships"].append(summary)
            else:
                updates["stable_facts"].append(summary)

        for key in updates:
            updates[key] = list(dict.fromkeys(updates[key]))
        return events[:20], updates

    async def extract_structured_memory(
        self,
        provider: LLMProvider,
        model: str,
        current_profile: dict[str, Any],
        lines: list[str],
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        prompt = (
            "Extract structured memory from this conversation and call save_events. "
            "Only include actionable long-term information.\n\n"
            "## Current Profile\n"
            f"{json.dumps(current_profile, ensure_ascii=False)}\n\n"
            "## Conversation\n"
            f"{chr(10).join(lines)}"
        )
        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": prompts.get("extractor"),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_EVENTS_TOOL,
                model=model,
            )
            if response.has_tool_calls:
                args = self.parse_tool_args(response.tool_calls[0].arguments)
                if args:
                    _raw_events = args.get("events")
                    raw_events: list[Any] = _raw_events if isinstance(_raw_events, list) else []
                    _raw_updates = args.get("profile_updates")
                    raw_updates: dict[str, Any] = (
                        _raw_updates if isinstance(_raw_updates, dict) else {}
                    )
                    updates = self.default_profile_updates()
                    for key in updates:
                        updates[key] = self.to_str_list(raw_updates.get(key))

                    events: list[dict[str, Any]] = []
                    for _, item in enumerate(raw_events):
                        if not isinstance(item, dict):
                            continue
                        source_span = item.get("source_span")
                        if (
                            not isinstance(source_span, list)
                            or len(source_span) != 2
                            or not all(isinstance(x, int) for x in source_span)
                        ):
                            source_span = [
                                source_start,
                                source_start + max(len(old_messages) - 1, 0),
                            ]
                        event = self.coerce_event(item, source_span=source_span)
                        if event:
                            events.append(event)
                        if len(events) >= 40:
                            break
                    self.last_extraction_source = "llm"
                    return events, updates
        except Exception:  # crash-barrier: LLM extraction + parsing
            logger.exception(
                "Structured event extraction failed, falling back to heuristic extraction"
            )

        self.last_extraction_source = "heuristic"
        return self.heuristic_extract_events(old_messages, source_start=source_start)
