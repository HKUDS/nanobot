"""Memory system for persistent agent memory."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.memory_embeddings import (
    MemoryEmbedder,
    create_vector_backend,
    cosine_similarity,
)
from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


_SAVE_EVENTS_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_events",
            "description": "Extract structured memory events and profile updates from conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "events": {
                        "type": "array",
                        "description": "Notable events extracted from conversation.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "timestamp": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "description": "preference|fact|task|decision|constraint|relationship",
                                },
                                "summary": {"type": "string"},
                                "entities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "salience": {"type": "number"},
                                "confidence": {"type": "number"},
                                "ttl_days": {"type": "integer"},
                            },
                            "required": ["type", "summary"],
                        },
                    },
                    "profile_updates": {
                        "type": "object",
                        "properties": {
                            "preferences": {"type": "array", "items": {"type": "string"}},
                            "stable_facts": {"type": "array", "items": {"type": "string"}},
                            "active_projects": {"type": "array", "items": {"type": "string"}},
                            "relationships": {"type": "array", "items": {"type": "string"}},
                            "constraints": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["events", "profile_updates"],
            },
        },
    }
]


class MemoryPersistence:
    """Low-level persistence for memory files and JSON payloads."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.events_file = self.memory_dir / "events.jsonl"
        self.profile_file = self.memory_dir / "profile.json"
        self.metrics_file = self.memory_dir / "metrics.json"
        self.index_dir = ensure_dir(self.memory_dir / "index")

    @staticmethod
    def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, (dict, list)):
                return data
        except Exception:
            return None
        return None

    @staticmethod
    def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
        return out

    @staticmethod
    def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        written = 0
        with open(path, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
        return written

    @staticmethod
    def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def append_text(path: Path, text: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)

    @staticmethod
    def read_text(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def write_text(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")


class MemoryRetriever:
    """Embedding/index/retrieval component extracted from MemoryStore."""

    def __init__(
        self,
        *,
        index_dir: Path,
        embedding_provider: str,
        vector_backend: str,
        persistence: MemoryPersistence,
        read_events: Any,
        to_str_list: Any,
        safe_float: Any,
        to_datetime: Any,
        utc_now_iso: Any,
        record_metric: Any,
    ):
        self.index_dir = index_dir
        self.embedding_provider = embedding_provider or "hash"
        self.vector_backend = vector_backend or "json"
        self.persistence = persistence
        self.read_events = read_events
        self.to_str_list = to_str_list
        self.safe_float = safe_float
        self.to_datetime = to_datetime
        self.utc_now_iso = utc_now_iso
        self.record_metric = record_metric
        self._embedder: MemoryEmbedder | None = None
        self._index_backend = create_vector_backend(self.vector_backend, index_dir=self.index_dir)

    @staticmethod
    def provider_slug(provider: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", provider.strip().lower())
        return slug or "hash"

    def get_embedder(self, embedding_provider: str | None = None) -> MemoryEmbedder:
        requested = (embedding_provider or self.embedding_provider or "hash").strip()
        if self._embedder is None or self._embedder.requested_provider != requested:
            self._embedder = MemoryEmbedder(requested)
        return self._embedder

    def index_file(self, provider: str) -> Path:
        slug = self.provider_slug(provider)
        if self._index_backend.name == "json":
            return self.index_dir / f"vectors_{slug}.json"
        if self._index_backend.name == "sqlite":
            return self.index_dir / "vectors.sqlite3"
        return self.index_dir / f"vectors_{slug}.faiss"

    @property
    def active_backend(self) -> str:
        return self._index_backend.name

    def event_text(self, event: dict[str, Any]) -> str:
        summary = str(event.get("summary", ""))
        entities = " ".join(self.to_str_list(event.get("entities")))
        event_type = str(event.get("type", "fact"))
        return f"{event_type}. {summary}. {entities}".strip()

    def load_vector_index(self, provider: str) -> dict[str, Any]:
        items = self._index_backend.load_items(provider)
        return {
            "provider": provider,
            "backend": self._index_backend.name,
            "updated_at": self.utc_now_iso(),
            "items": items,
            "dim": len(next(iter(items.values()))) if items else 0,
        }

    def save_vector_index(self, provider: str, index_data: dict[str, Any]) -> None:
        items: dict[str, list[float]] = {
            key: [float(x) for x in value]
            for key, value in index_data.get("items", {}).items()
            if isinstance(key, str) and isinstance(value, list)
        }
        dim = int(index_data.get("dim", 0) or 0)
        if dim <= 0 and items:
            dim = len(next(iter(items.values())))
        self._index_backend.save_items(provider, items, dim)

    def ensure_event_embeddings(
        self,
        events: list[dict[str, Any]],
        *,
        embedding_provider: str | None = None,
    ) -> tuple[dict[str, list[float]], str]:
        embedder = self.get_embedder(embedding_provider)
        provider = embedder.provider_name
        index_data = self.load_vector_index(provider)
        items: dict[str, list[float]] = {
            key: value
            for key, value in index_data.get("items", {}).items()
            if isinstance(key, str) and isinstance(value, list)
        }

        missing_ids: list[str] = []
        missing_texts: list[str] = []
        for event in events:
            event_id = event.get("id")
            if not isinstance(event_id, str) or not event_id:
                continue
            if event_id in items:
                continue
            missing_ids.append(event_id)
            missing_texts.append(self.event_text(event))

        if missing_ids:
            vectors = embedder.embed_texts(missing_texts)
            for event_id, vector in zip(missing_ids, vectors, strict=False):
                items[event_id] = [float(x) for x in vector]
            index_data["items"] = items
            index_data["dim"] = len(next(iter(items.values()))) if items else 0
            self.save_vector_index(provider, index_data)
            self.record_metric("index_updates", len(missing_ids))

        return items, provider

    def rebuild_event_embeddings(
        self,
        events: list[dict[str, Any]],
        *,
        embedding_provider: str | None = None,
    ) -> tuple[dict[str, list[float]], str]:
        embedder = self.get_embedder(embedding_provider)
        provider = embedder.provider_name
        valid_events = [event for event in events if isinstance(event.get("id"), str) and event.get("id")]
        if not valid_events:
            self.save_vector_index(provider, {"items": {}, "dim": 0})
            return {}, provider

        ids = [str(event["id"]) for event in valid_events]
        texts = [self.event_text(event) for event in valid_events]
        vectors = embedder.embed_texts(texts)
        items = {
            event_id: [float(x) for x in vector]
            for event_id, vector in zip(ids, vectors, strict=False)
        }
        self.save_vector_index(
            provider,
            {
                "items": items,
                "dim": len(next(iter(items.values()))) if items else 0,
            },
        )
        self.record_metric("index_updates", len(items))
        return items, provider

    @staticmethod
    def lexical_similarity(query: str, text: str, tokenize: Any) -> float:
        q = tokenize(query)
        t = tokenize(text)
        if not q or not t:
            return 0.0
        common = len(q & t)
        denom = len(q | t)
        return common / denom if denom else 0.0

    def recency_score(self, timestamp: str, half_life_days: float) -> float:
        dt = self.to_datetime(timestamp)
        if not dt:
            return 0.0
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max((now - dt).total_seconds() / 86400.0, 0.0)
        half_life = max(half_life_days, 1.0)
        return math.exp(-age_days / half_life)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        recency_half_life_days: float = 30.0,
        embedding_provider: str | None = None,
        tokenize: Any,
    ) -> list[dict[str, Any]]:
        events = self.read_events()
        if not events:
            self.record_metric("retrieval_queries", 1)
            return []

        vectors_by_id, active_provider = self.ensure_event_embeddings(
            events,
            embedding_provider=embedding_provider,
        )
        query_vec: list[float] | None = None
        if query.strip():
            query_vec = self.get_embedder(active_provider).embed_texts([query])[0]

        scored: list[dict[str, Any]] = []
        for event in events:
            summary = str(event.get("summary", ""))
            entities = " ".join(self.to_str_list(event.get("entities")))
            text = f"{summary} {entities}".strip()
            lex = self.lexical_similarity(query, text, tokenize) if query.strip() else 0.0
            event_vec = vectors_by_id.get(str(event.get("id", "")))
            sem = cosine_similarity(query_vec, event_vec) if (query_vec and event_vec) else 0.0
            rec = self.recency_score(str(event.get("timestamp", "")), recency_half_life_days)
            sal = min(max(self.safe_float(event.get("salience"), 0.6), 0.0), 1.0)
            conf = min(max(self.safe_float(event.get("confidence"), 0.7), 0.0), 1.0)
            score = 0.5 * sem + 0.15 * lex + 0.15 * rec + 0.1 * sal + 0.1 * conf
            if query.strip() and sem <= 0 and lex <= 0 and score < 0.2:
                continue
            event_copy = dict(event)
            event_copy["score"] = score
            event_copy["retrieval_reason"] = {
                "semantic": round(sem, 4),
                "lexical": round(lex, 4),
                "recency": round(rec, 4),
                "salience": round(sal, 4),
                "confidence": round(conf, 4),
                "provider": active_provider,
                "backend": self.active_backend,
            }
            evidence = event.get("evidence") if isinstance(event.get("evidence"), list) else []
            aliases = event.get("aliases") if isinstance(event.get("aliases"), list) else []
            event_copy["provenance"] = {
                "canonical_id": event.get("canonical_id") or event.get("id"),
                "aliases_count": len(aliases),
                "evidence_count": len(evidence),
                "merged_event_count": int(event.get("merged_event_count", 1) or 1),
            }
            scored.append(event_copy)

        scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        result = scored[: max(1, top_k)]
        self.record_metric("retrieval_queries", 1)
        if result:
            self.record_metric("retrieval_hits", 1)
        return result


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
            lowered = text.lower()

            event_type = "fact"
            for candidate, needles in type_hints:
                if any(needle in lowered for needle in needles):
                    event_type = candidate
                    break

            summary = text if len(text) <= 220 else text[:217] + "..."
            source_span = [source_start + offset, source_start + offset]
            event = self.coerce_event(
                {
                    "timestamp": message.get("timestamp") or self.utc_now_iso(),
                    "type": event_type,
                    "summary": summary,
                    "entities": [],
                    "salience": 0.55,
                    "confidence": 0.6,
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
                        "content": "You are a structured memory extractor. Call save_events with events and profile_updates.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_EVENTS_TOOL,
                model=model,
            )
            if response.has_tool_calls:
                args = self.parse_tool_args(response.tool_calls[0].arguments)
                if args:
                    raw_events = args.get("events") if isinstance(args.get("events"), list) else []
                    raw_updates = args.get("profile_updates") if isinstance(args.get("profile_updates"), dict) else {}
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
                            source_span = [source_start, source_start + max(len(old_messages) - 1, 0)]
                        event = self.coerce_event(item, source_span=source_span)
                        if event:
                            events.append(event)
                        if len(events) >= 40:
                            break
                    return events, updates
        except Exception:
            logger.exception("Structured event extraction failed, falling back to heuristic extraction")

        return self.heuristic_extract_events(old_messages, source_start=source_start)


class MemoryStore:
    """Hybrid memory: markdown files + structured events/profile/metrics."""

    PROFILE_KEYS = ("preferences", "stable_facts", "active_projects", "relationships", "constraints")
    EVENT_TYPES = {"preference", "fact", "task", "decision", "constraint", "relationship"}
    PROFILE_STATUS_ACTIVE = "active"
    PROFILE_STATUS_CONFLICTED = "conflicted"
    PROFILE_STATUS_STALE = "stale"

    def __init__(self, workspace: Path, embedding_provider: str = "", vector_backend: str = "json"):
        self.persistence = MemoryPersistence(workspace)
        self.memory_dir = self.persistence.memory_dir
        self.memory_file = self.persistence.memory_file
        self.history_file = self.persistence.history_file
        self.events_file = self.persistence.events_file
        self.profile_file = self.persistence.profile_file
        self.metrics_file = self.persistence.metrics_file
        self.index_dir = self.persistence.index_dir
        self.embedding_provider = embedding_provider or "hash"
        self.vector_backend = vector_backend or "json"
        self.retriever = MemoryRetriever(
            index_dir=self.index_dir,
            embedding_provider=self.embedding_provider,
            vector_backend=self.vector_backend,
            persistence=self.persistence,
            read_events=self.read_events,
            to_str_list=self._to_str_list,
            safe_float=self._safe_float,
            to_datetime=self._to_datetime,
            utc_now_iso=self._utc_now_iso,
            record_metric=self._record_metric,
        )
        self.extractor = MemoryExtractor(
            to_str_list=self._to_str_list,
            coerce_event=self._coerce_event,
            utc_now_iso=self._utc_now_iso,
        )

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _norm_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        return {t for t in re.findall(r"[a-zA-Z0-9_\-]+", value.lower()) if len(t) > 1}

    @staticmethod
    def _to_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    @staticmethod
    def _to_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _load_metrics(self) -> dict[str, Any]:
        data = self.persistence.read_json(self.metrics_file)
        if isinstance(data, dict):
            return data
        if self.metrics_file.exists():
            logger.warning("Failed to parse memory metrics, resetting")
        return {
            "consolidations": 0,
            "events_extracted": 0,
            "event_dedup_merges": 0,
            "retrieval_queries": 0,
            "retrieval_hits": 0,
            "index_updates": 0,
            "conflicts_detected": 0,
            "messages_processed": 0,
            "user_messages_processed": 0,
            "user_corrections": 0,
            "profile_updates_applied": 0,
            "memory_context_calls": 0,
            "memory_context_tokens_total": 0,
            "memory_context_tokens_max": 0,
            "last_updated": self._utc_now_iso(),
        }

    @staticmethod
    def _provider_slug(provider: str) -> str:
        return MemoryRetriever.provider_slug(provider)

    def _get_embedder(self, embedding_provider: str | None = None) -> MemoryEmbedder:
        return self.retriever.get_embedder(embedding_provider)

    def _index_file(self, provider: str) -> Path:
        return self.retriever.index_file(provider)

    def _event_text(self, event: dict[str, Any]) -> str:
        return self.retriever.event_text(event)

    def _load_vector_index(self, provider: str) -> dict[str, Any]:
        return self.retriever.load_vector_index(provider)

    def _save_vector_index(self, provider: str, index_data: dict[str, Any]) -> None:
        self.retriever.save_vector_index(provider, index_data)

    def _ensure_event_embeddings(
        self,
        events: list[dict[str, Any]],
        *,
        embedding_provider: str | None = None,
    ) -> tuple[dict[str, list[float]], str]:
        return self.retriever.ensure_event_embeddings(events, embedding_provider=embedding_provider)

    def _record_metric(self, key: str, delta: int = 1) -> None:
        self._record_metrics({key: delta})

    def _record_metrics(self, deltas: dict[str, int]) -> None:
        metrics = self._load_metrics()
        for key, delta in deltas.items():
            metrics[key] = int(metrics.get(key, 0)) + int(delta)
        metrics["last_updated"] = self._utc_now_iso()
        self.persistence.write_json(self.metrics_file, metrics)

    def get_metrics(self) -> dict[str, Any]:
        return self._load_metrics()

    def get_observability_report(self) -> dict[str, Any]:
        metrics = self.get_metrics()
        retrieval_queries = max(int(metrics.get("retrieval_queries", 0)), 0)
        retrieval_hits = max(int(metrics.get("retrieval_hits", 0)), 0)
        messages_processed = max(int(metrics.get("messages_processed", 0)), 0)
        user_messages_processed = max(int(metrics.get("user_messages_processed", 0)), 0)
        user_corrections = max(int(metrics.get("user_corrections", 0)), 0)
        conflicts_detected = max(int(metrics.get("conflicts_detected", 0)), 0)
        memory_context_calls = max(int(metrics.get("memory_context_calls", 0)), 0)
        memory_context_tokens_total = max(int(metrics.get("memory_context_tokens_total", 0)), 0)
        memory_context_tokens_max = max(int(metrics.get("memory_context_tokens_max", 0)), 0)

        retrieval_hit_rate = (retrieval_hits / retrieval_queries) if retrieval_queries else 0.0
        contradiction_rate_per_100 = (conflicts_detected * 100.0 / messages_processed) if messages_processed else 0.0
        user_correction_rate_per_100 = (user_corrections * 100.0 / user_messages_processed) if user_messages_processed else 0.0
        avg_memory_context_tokens = (memory_context_tokens_total / memory_context_calls) if memory_context_calls else 0.0

        return {
            "metrics": metrics,
            "kpis": {
                "retrieval_hit_rate": round(retrieval_hit_rate, 4),
                "contradiction_rate_per_100_messages": round(contradiction_rate_per_100, 4),
                "user_correction_rate_per_100_user_messages": round(user_correction_rate_per_100, 4),
                "avg_memory_context_tokens": round(avg_memory_context_tokens, 2),
                "max_memory_context_tokens": memory_context_tokens_max,
            },
        }

    def evaluate_retrieval_cases(
        self,
        cases: list[dict[str, Any]],
        *,
        default_top_k: int = 6,
        recency_half_life_days: float = 30.0,
        embedding_provider: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate retrieval quality using labeled cases.

        Case format (each dict):
        - query: str (required)
        - expected_ids: list[str] (optional)
        - expected_any: list[str] substrings expected in retrieved summaries (optional)
        - top_k: int (optional)
        """
        valid_cases = [c for c in cases if isinstance(c, dict) and isinstance(c.get("query"), str) and c.get("query", "").strip()]
        if not valid_cases:
            return {
                "cases": 0,
                "evaluated": [],
                "summary": {
                    "recall_at_k": 0.0,
                    "precision_at_k": 0.0,
                },
            }

        total_expected = 0
        total_found = 0
        total_relevant_retrieved = 0
        total_retrieved_slots = 0
        evaluated: list[dict[str, Any]] = []

        for case in valid_cases:
            query = str(case.get("query", "")).strip()
            top_k = int(case.get("top_k", default_top_k) or default_top_k)
            top_k = max(1, min(top_k, 30))

            expected_ids = [str(x) for x in case.get("expected_ids", []) if isinstance(x, str) and x.strip()]
            expected_any = [str(x).lower() for x in case.get("expected_any", []) if isinstance(x, str) and x.strip()]

            retrieved = self.retrieve(
                query,
                top_k=top_k,
                recency_half_life_days=recency_half_life_days,
                embedding_provider=embedding_provider,
            )

            hits = 0
            relevant_retrieved = 0
            matched_expected_tokens: set[str] = set()

            for item in retrieved:
                summary = str(item.get("summary", "")).lower()
                event_id = str(item.get("id", ""))
                is_relevant = False

                for expected_id in expected_ids:
                    if expected_id == event_id:
                        matched_expected_tokens.add(f"id:{expected_id}")
                        is_relevant = True

                for expected_text in expected_any:
                    if expected_text in summary:
                        matched_expected_tokens.add(f"txt:{expected_text}")
                        is_relevant = True

                if is_relevant:
                    relevant_retrieved += 1

            expected_count = len(expected_ids) + len(expected_any)
            if expected_count > 0:
                hits = len(matched_expected_tokens)
                total_expected += expected_count
                total_found += hits

            total_relevant_retrieved += relevant_retrieved
            total_retrieved_slots += top_k

            case_recall = (hits / expected_count) if expected_count else 0.0
            case_precision = (relevant_retrieved / top_k) if top_k > 0 else 0.0
            evaluated.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "expected": expected_count,
                    "hits": hits,
                    "retrieved": len(retrieved),
                    "case_recall_at_k": round(case_recall, 4),
                    "case_precision_at_k": round(case_precision, 4),
                }
            )

        overall_recall = (total_found / total_expected) if total_expected else 0.0
        overall_precision = (total_relevant_retrieved / total_retrieved_slots) if total_retrieved_slots else 0.0

        return {
            "cases": len(valid_cases),
            "evaluated": evaluated,
            "summary": {
                "recall_at_k": round(overall_recall, 4),
                "precision_at_k": round(overall_precision, 4),
            },
        }

    def save_evaluation_report(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
        *,
        output_file: str | None = None,
    ) -> Path:
        """Persist evaluation + observability report to disk and return the file path."""
        reports_dir = ensure_dir(self.memory_dir / "reports")
        if output_file:
            path = Path(output_file).expanduser().resolve()
            ensure_dir(path.parent)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = reports_dir / f"memory_eval_{ts}.json"

        payload = {
            "generated_at": self._utc_now_iso(),
            "evaluation": evaluation,
            "observability": observability,
        }
        self.persistence.write_json(path, payload)
        return path

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        out = self.persistence.read_jsonl(self.events_file)
        if limit is not None and limit > 0:
            return out[-limit:]
        return out

    @staticmethod
    def _merge_source_span(base: list[int] | Any, incoming: list[int] | Any) -> list[int]:
        base_span = base if isinstance(base, list) and len(base) == 2 and all(isinstance(x, int) for x in base) else [0, 0]
        incoming_span = (
            incoming if isinstance(incoming, list) and len(incoming) == 2 and all(isinstance(x, int) for x in incoming) else base_span
        )
        return [min(base_span[0], incoming_span[0]), max(base_span[1], incoming_span[1])]

    def _ensure_event_provenance(self, event: dict[str, Any]) -> dict[str, Any]:
        event_copy = dict(event)
        event_id = str(event_copy.get("id", "")).strip()
        if not event_id:
            return event_copy

        event_copy.setdefault("canonical_id", event_id)
        aliases = event_copy.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        summary = str(event_copy.get("summary", "")).strip()
        if summary and summary not in aliases:
            aliases.append(summary)
        event_copy["aliases"] = aliases

        evidence = event_copy.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        if not evidence:
            evidence.append(
                {
                    "event_id": event_id,
                    "timestamp": str(event_copy.get("timestamp", "")),
                    "summary": summary,
                    "source_span": event_copy.get("source_span"),
                    "confidence": self._safe_float(event_copy.get("confidence"), 0.7),
                    "salience": self._safe_float(event_copy.get("salience"), 0.6),
                }
            )
        event_copy["evidence"] = evidence
        event_copy["merged_event_count"] = max(int(event_copy.get("merged_event_count", 1)), 1)
        return event_copy

    def _event_similarity(self, left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
        left_text = self._event_text(left)
        right_text = self._event_text(right)
        lexical = self._lexical_similarity(left_text, right_text)

        semantic = 0.0
        try:
            vectors = self._get_embedder(self.embedding_provider).embed_texts([left_text, right_text])
            if len(vectors) == 2:
                semantic = cosine_similarity(vectors[0], vectors[1])
        except Exception:
            semantic = 0.0
        return lexical, semantic

    def _find_semantic_duplicate(
        self,
        candidate: dict[str, Any],
        existing_events: list[dict[str, Any]],
    ) -> tuple[int | None, float]:
        best_idx: int | None = None
        best_score = 0.0
        candidate_type = str(candidate.get("type", ""))

        for idx, existing in enumerate(existing_events):
            if str(existing.get("type", "")) != candidate_type:
                continue
            lexical, semantic = self._event_similarity(candidate, existing)
            candidate_entities = {self._norm_text(x) for x in self._to_str_list(candidate.get("entities"))}
            existing_entities = {self._norm_text(x) for x in self._to_str_list(existing.get("entities"))}
            entity_overlap = 0.0
            if candidate_entities and existing_entities:
                entity_overlap = len(candidate_entities & existing_entities) / max(len(candidate_entities | existing_entities), 1)

            score = 0.4 * semantic + 0.45 * lexical + 0.15 * entity_overlap
            is_duplicate = (
                lexical >= 0.84
                or semantic >= 0.94
                or (lexical >= 0.6 and semantic >= 0.86)
                or (entity_overlap >= 0.33 and (lexical >= 0.42 or semantic >= 0.52))
            )
            if not is_duplicate:
                continue
            if score > best_score:
                best_score = score
                best_idx = idx

        return best_idx, best_score

    def _merge_events(
        self,
        base: dict[str, Any],
        incoming: dict[str, Any],
        *,
        similarity: float,
    ) -> dict[str, Any]:
        canonical = self._ensure_event_provenance(base)
        candidate = self._ensure_event_provenance(incoming)

        entities = list(dict.fromkeys(self._to_str_list(canonical.get("entities")) + self._to_str_list(candidate.get("entities"))))
        aliases = list(dict.fromkeys(self._to_str_list(canonical.get("aliases")) + self._to_str_list(candidate.get("aliases"))))
        evidence = canonical.get("evidence") if isinstance(canonical.get("evidence"), list) else []
        evidence.extend(candidate.get("evidence") if isinstance(candidate.get("evidence"), list) else [])
        if len(evidence) > 20:
            evidence = evidence[-20:]

        merged_count = max(int(canonical.get("merged_event_count", 1)), 1) + 1
        c_conf = self._safe_float(canonical.get("confidence"), 0.7)
        i_conf = self._safe_float(candidate.get("confidence"), 0.7)
        c_sal = self._safe_float(canonical.get("salience"), 0.6)
        i_sal = self._safe_float(candidate.get("salience"), 0.6)

        merged = dict(canonical)
        merged["summary"] = str(canonical.get("summary") or candidate.get("summary") or "")
        merged["entities"] = entities
        merged["aliases"] = aliases
        merged["evidence"] = evidence
        merged["source_span"] = self._merge_source_span(canonical.get("source_span"), candidate.get("source_span"))
        merged["confidence"] = min(max((c_conf + i_conf) / 2.0 + 0.03, 0.0), 1.0)
        merged["salience"] = min(max(max(c_sal, i_sal), 0.0), 1.0)
        merged["merged_event_count"] = merged_count
        merged["last_merged_at"] = self._utc_now_iso()
        merged["last_dedup_score"] = round(similarity, 4)
        merged["canonical_id"] = str(canonical.get("canonical_id") or canonical.get("id", ""))

        canonical_ts = self._to_datetime(str(canonical.get("timestamp", "")))
        candidate_ts = self._to_datetime(str(candidate.get("timestamp", "")))
        if canonical_ts and candidate_ts and candidate_ts > canonical_ts:
            merged["timestamp"] = str(candidate.get("timestamp", merged.get("timestamp", "")))
        return merged

    def append_events(self, events: list[dict[str, Any]]) -> int:
        if not events:
            return 0
        existing_events = [self._ensure_event_provenance(event) for event in self.read_events()]
        existing_ids = {e.get("id") for e in existing_events if e.get("id")}
        written = 0
        merged = 0
        appended_events: list[dict[str, Any]] = []

        for raw in events:
            event_id = raw.get("id")
            if not event_id:
                continue
            candidate = self._ensure_event_provenance(raw)

            if event_id in existing_ids:
                for idx, existing in enumerate(existing_events):
                    if existing.get("id") == event_id:
                        existing_events[idx] = self._merge_events(existing, candidate, similarity=1.0)
                        merged += 1
                        break
                continue

            dup_idx, dup_score = self._find_semantic_duplicate(candidate, existing_events)
            if dup_idx is not None:
                existing_events[dup_idx] = self._merge_events(existing_events[dup_idx], candidate, similarity=dup_score)
                merged += 1
                continue

            existing_ids.add(event_id)
            existing_events.append(candidate)
            appended_events.append(candidate)
            written += 1

        if written <= 0 and merged <= 0:
            return 0

        self.persistence.write_jsonl(self.events_file, existing_events)
        if merged > 0:
            self.retriever.rebuild_event_embeddings(existing_events, embedding_provider=self.embedding_provider)
            self._record_metric("event_dedup_merges", merged)
        elif written > 0:
            self._ensure_event_embeddings(appended_events, embedding_provider=self.embedding_provider)
        return written

    def read_profile(self) -> dict[str, Any]:
        data = self.persistence.read_json(self.profile_file)
        if isinstance(data, dict):
            for key in self.PROFILE_KEYS:
                data.setdefault(key, [])
                if not isinstance(data[key], list):
                    data[key] = []
            data.setdefault("conflicts", [])
            data.setdefault("last_verified_at", None)
            data.setdefault("meta", {})
            for key in self.PROFILE_KEYS:
                section_meta = data["meta"].get(key)
                if not isinstance(section_meta, dict):
                    section_meta = {}
                    data["meta"][key] = section_meta
                for item in data[key]:
                    if not isinstance(item, str) or not item.strip():
                        continue
                    norm = self._norm_text(item)
                    entry = section_meta.get(norm)
                    if not isinstance(entry, dict):
                        section_meta[norm] = {
                            "text": item,
                            "confidence": 0.65,
                            "evidence_count": 1,
                            "status": self.PROFILE_STATUS_ACTIVE,
                            "last_seen_at": data.get("updated_at") or self._utc_now_iso(),
                        }
            return data
        if self.profile_file.exists():
            logger.warning("Failed to parse memory profile, resetting")
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {key: {} for key in self.PROFILE_KEYS},
            "updated_at": self._utc_now_iso(),
        }

    def _meta_section(self, profile: dict[str, Any], key: str) -> dict[str, Any]:
        profile.setdefault("meta", {})
        section = profile["meta"].get(key)
        if not isinstance(section, dict):
            section = {}
            profile["meta"][key] = section
        return section

    def _meta_entry(self, profile: dict[str, Any], key: str, text: str) -> dict[str, Any]:
        norm = self._norm_text(text)
        section = self._meta_section(profile, key)
        entry = section.get(norm)
        if not isinstance(entry, dict):
            entry = {
                "text": text,
                "confidence": 0.65,
                "evidence_count": 1,
                "status": self.PROFILE_STATUS_ACTIVE,
                "last_seen_at": self._utc_now_iso(),
            }
            section[norm] = entry
        return entry

    def _touch_meta_entry(
        self,
        entry: dict[str, Any],
        *,
        confidence_delta: float,
        min_confidence: float = 0.05,
        max_confidence: float = 0.99,
        status: str | None = None,
    ) -> None:
        current_conf = self._safe_float(entry.get("confidence"), 0.65)
        entry["confidence"] = min(max(current_conf + confidence_delta, min_confidence), max_confidence)
        evidence = int(entry.get("evidence_count", 0)) + 1
        entry["evidence_count"] = max(evidence, 1)
        entry["last_seen_at"] = self._utc_now_iso()
        if status:
            entry["status"] = status

    def _validate_profile_field(self, field: str) -> str:
        key = str(field or "").strip()
        if key not in self.PROFILE_KEYS:
            raise ValueError(f"Invalid profile field '{field}'. Expected one of: {', '.join(self.PROFILE_KEYS)}")
        return key

    def set_item_pin(self, field: str, text: str, *, pinned: bool) -> bool:
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            return False

        profile = self.read_profile()
        values = self._to_str_list(profile.get(key))
        normalized = self._norm_text(value)
        existing_map = {self._norm_text(v): v for v in values}
        if normalized not in existing_map:
            values.append(value)
            profile[key] = values

        canonical = existing_map.get(normalized, value)
        entry = self._meta_entry(profile, key, canonical)
        entry["pinned"] = bool(pinned)
        entry["last_seen_at"] = self._utc_now_iso()
        if entry.get("status") == self.PROFILE_STATUS_STALE and pinned:
            entry["status"] = self.PROFILE_STATUS_ACTIVE
        self.write_profile(profile)
        return True

    def mark_item_outdated(self, field: str, text: str) -> bool:
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            return False

        profile = self.read_profile()
        values = self._to_str_list(profile.get(key))
        normalized = self._norm_text(value)
        existing = None
        for item in values:
            if self._norm_text(item) == normalized:
                existing = item
                break
        if existing is None:
            return False

        entry = self._meta_entry(profile, key, existing)
        entry["status"] = self.PROFILE_STATUS_STALE
        entry["last_seen_at"] = self._utc_now_iso()
        self.write_profile(profile)
        return True

    def list_conflicts(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return []

        out: list[dict[str, Any]] = []
        for idx, item in enumerate(conflicts):
            if not isinstance(item, dict):
                continue
            status = item.get("status", "open")
            if not include_closed and status != "open":
                continue
            row = dict(item)
            row["index"] = idx
            out.append(row)
        return out

    def resolve_conflict(self, index: int, action: str) -> bool:
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list) or index < 0 or index >= len(conflicts):
            return False

        conflict = conflicts[index]
        if not isinstance(conflict, dict) or conflict.get("status") != "open":
            return False

        field = str(conflict.get("field", ""))
        try:
            key = self._validate_profile_field(field)
        except ValueError:
            return False

        old_value = str(conflict.get("old", "")).strip()
        new_value = str(conflict.get("new", "")).strip()
        values = self._to_str_list(profile.get(key))

        def _remove_value(values_in: list[str], target: str) -> list[str]:
            target_norm = self._norm_text(target)
            return [v for v in values_in if self._norm_text(v) != target_norm]

        selected = str(action or "").strip().lower()
        if selected == "keep_old":
            values = _remove_value(values, new_value)
            old_entry = self._meta_entry(profile, key, old_value)
            self._touch_meta_entry(old_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE)
            new_entry = self._meta_entry(profile, key, new_value)
            new_entry["status"] = self.PROFILE_STATUS_STALE
        elif selected == "keep_new":
            values = _remove_value(values, old_value)
            new_entry = self._meta_entry(profile, key, new_value)
            self._touch_meta_entry(new_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE)
            old_entry = self._meta_entry(profile, key, old_value)
            old_entry["status"] = self.PROFILE_STATUS_STALE
        elif selected == "dismiss":
            old_entry = self._meta_entry(profile, key, old_value)
            new_entry = self._meta_entry(profile, key, new_value)
            old_entry["status"] = self.PROFILE_STATUS_ACTIVE
            new_entry["status"] = self.PROFILE_STATUS_ACTIVE
        else:
            return False

        profile[key] = values
        conflict["status"] = "resolved"
        conflict["resolution"] = selected
        conflict["resolved_at"] = self._utc_now_iso()
        self.write_profile(profile)
        return True

    def write_profile(self, profile: dict[str, Any]) -> None:
        profile["updated_at"] = self._utc_now_iso()
        self.persistence.write_json(self.profile_file, profile)

    def _build_event_id(self, event_type: str, summary: str, timestamp: str) -> str:
        raw = f"{self._norm_text(event_type)}|{self._norm_text(summary)}|{timestamp[:16]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _coerce_event(
        self,
        raw: dict[str, Any],
        *,
        source_span: list[int],
        channel: str = "",
        chat_id: str = "",
    ) -> dict[str, Any] | None:
        summary = raw.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        event_type = raw.get("type") if isinstance(raw.get("type"), str) else "fact"
        event_type = event_type if event_type in self.EVENT_TYPES else "fact"
        timestamp = raw.get("timestamp") if isinstance(raw.get("timestamp"), str) else self._utc_now_iso()
        salience = min(max(self._safe_float(raw.get("salience"), 0.6), 0.0), 1.0)
        confidence = min(max(self._safe_float(raw.get("confidence"), 0.7), 0.0), 1.0)
        entities = self._to_str_list(raw.get("entities"))
        ttl_days = raw.get("ttl_days")
        if not isinstance(ttl_days, int) or ttl_days <= 0:
            ttl_days = None

        event_id = raw.get("id") if isinstance(raw.get("id"), str) else ""
        if not event_id:
            event_id = self._build_event_id(event_type, summary, timestamp)

        return {
            "id": event_id,
            "timestamp": timestamp,
            "channel": channel,
            "chat_id": chat_id,
            "type": event_type,
            "summary": summary.strip(),
            "entities": entities,
            "salience": salience,
            "confidence": confidence,
            "source_span": source_span,
            "ttl_days": ttl_days,
        }

    def _lexical_similarity(self, query: str, text: str) -> float:
        return self.retriever.lexical_similarity(query, text, self._tokenize)

    def _recency_score(self, timestamp: str, half_life_days: float) -> float:
        return self.retriever.recency_score(timestamp, half_life_days)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        recency_half_life_days: float = 30.0,
        embedding_provider: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.retriever.retrieve(
            query,
            top_k=top_k,
            recency_half_life_days=recency_half_life_days,
            embedding_provider=embedding_provider,
            tokenize=self._tokenize,
        )

    def _profile_section_lines(self, profile: dict[str, Any], max_items_per_section: int = 6) -> list[str]:
        lines: list[str] = []
        title_map = {
            "preferences": "Preferences",
            "stable_facts": "Stable Facts",
            "active_projects": "Active Projects",
            "relationships": "Relationships",
            "constraints": "Constraints",
        }
        for key in self.PROFILE_KEYS:
            values = self._to_str_list(profile.get(key))
            if not values:
                continue
            section_meta = self._meta_section(profile, key)
            scored_values: list[tuple[str, float, int]] = []
            for value in values:
                meta = section_meta.get(self._norm_text(value), {}) if isinstance(section_meta, dict) else {}
                status = meta.get("status") if isinstance(meta, dict) else None
                pinned = bool(meta.get("pinned")) if isinstance(meta, dict) else False
                if status == self.PROFILE_STATUS_STALE and not pinned:
                    continue
                conf = self._safe_float(meta.get("confidence") if isinstance(meta, dict) else None, 0.65)
                pin_rank = 1 if pinned else 0
                scored_values.append((value, conf, pin_rank))
            scored_values.sort(key=lambda item: (item[2], item[1]), reverse=True)
            if not scored_values:
                continue
            lines.append(f"### {title_map[key]}")
            for item, confidence, pin_rank in scored_values[:max_items_per_section]:
                pin_suffix = " 📌" if pin_rank else ""
                lines.append(f"- {item} (conf={confidence:.2f}){pin_suffix}")
            lines.append("")
        return lines

    @staticmethod
    def _is_resolved_task_or_decision(summary: str) -> bool:
        text = summary.lower()
        resolved_markers = ("done", "completed", "resolved", "closed", "finished", "cancelled", "canceled")
        return any(marker in text for marker in resolved_markers)

    def _recent_unresolved(self, events: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
        unresolved: list[dict[str, Any]] = []
        for event in reversed(events):
            event_type = str(event.get("type", ""))
            if event_type not in {"task", "decision"}:
                continue
            summary = str(event.get("summary", "")).strip()
            if not summary or self._is_resolved_task_or_decision(summary):
                continue
            unresolved.append(event)
            if len(unresolved) >= max_items:
                break
        unresolved.reverse()
        return unresolved

    def get_memory_context(
        self,
        *,
        mode: str = "legacy",
        query: str | None = None,
        retrieval_k: int = 6,
        token_budget: int = 900,
        recency_half_life_days: float = 30.0,
        embedding_provider: str | None = None,
    ) -> str:
        long_term = self.read_long_term()
        if mode != "hybrid":
            return f"## Long-term Memory\n{long_term}" if long_term else ""

        profile = self.read_profile()
        retrieved = self.retrieve(
            query or "",
            top_k=retrieval_k,
            recency_half_life_days=recency_half_life_days,
            embedding_provider=embedding_provider,
        )

        lines: list[str] = ["## Long-term Memory"]
        if long_term:
            lines.append(long_term.strip())

        profile_lines = self._profile_section_lines(profile)
        if profile_lines:
            lines.append("## Profile Memory")
            lines.extend(profile_lines)

        if retrieved:
            lines.append("## Relevant Episodic Memories")
            for item in retrieved:
                timestamp = str(item.get("timestamp", ""))[:16]
                event_type = item.get("type", "fact")
                summary = item.get("summary", "")
                reason = item.get("retrieval_reason", {})
                lines.append(
                    f"- [{timestamp}] ({event_type}) {summary} "
                    f"[sem={reason.get('semantic', 0):.2f}, rec={reason.get('recency', 0):.2f}, src={reason.get('provider', 'hash')}]"
                )

        unresolved = self._recent_unresolved(self.read_events(limit=60), max_items=6)
        if unresolved:
            lines.append("## Recent Unresolved Tasks/Decisions")
            for item in unresolved:
                ts = str(item.get("timestamp", ""))[:16]
                lines.append(f"- [{ts}] ({item.get('type', 'task')}) {item.get('summary', '')}")

        text = "\n".join(lines).strip()
        max_chars = max(token_budget, 200) * 4
        if len(text) > max_chars:
            text = text[:max_chars].rsplit("\n", 1)[0] + "\n- ... (memory context truncated to token budget)"

        est_tokens = max(1, len(text) // 4) if text else 0
        metrics = self._load_metrics()
        max_tokens_seen = max(int(metrics.get("memory_context_tokens_max", 0)), est_tokens)
        self._record_metrics(
            {
                "memory_context_calls": 1,
                "memory_context_tokens_total": est_tokens,
            }
        )
        if max_tokens_seen > int(metrics.get("memory_context_tokens_max", 0)):
            refreshed = self._load_metrics()
            refreshed["memory_context_tokens_max"] = max_tokens_seen
            refreshed["last_updated"] = self._utc_now_iso()
            self.persistence.write_json(self.metrics_file, refreshed)
        return text

    def _default_profile_updates(self) -> dict[str, list[str]]:
        return self.extractor.default_profile_updates()

    def _count_user_corrections(self, messages: list[dict[str, Any]]) -> int:
        return self.extractor.count_user_corrections(messages)

    def _parse_tool_args(self, args: Any) -> dict[str, Any] | None:
        return self.extractor.parse_tool_args(args)

    def _heuristic_extract_events(
        self,
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        return self.extractor.heuristic_extract_events(old_messages, source_start=source_start)

    async def _extract_structured_memory(
        self,
        provider: LLMProvider,
        model: str,
        current_profile: dict[str, Any],
        lines: list[str],
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        return await self.extractor.extract_structured_memory(
            provider,
            model,
            current_profile,
            lines,
            old_messages,
            source_start=source_start,
        )

    def _conflict_pair(self, old_value: str, new_value: str) -> bool:
        old_n = self._norm_text(old_value)
        new_n = self._norm_text(new_value)
        if not old_n or not new_n or old_n == new_n:
            return False
        old_has_not = " not " in f" {old_n} " or "n't" in old_n
        new_has_not = " not " in f" {new_n} " or "n't" in new_n
        if old_has_not == new_has_not:
            return False
        old_tokens = self._tokenize(old_n.replace("not", ""))
        new_tokens = self._tokenize(new_n.replace("not", ""))
        if not old_tokens or not new_tokens:
            return False
        overlap = len(old_tokens & new_tokens) / max(len(old_tokens | new_tokens), 1)
        return overlap >= 0.55

    def _apply_profile_updates(
        self,
        profile: dict[str, Any],
        updates: dict[str, list[str]],
        *,
        enable_contradiction_check: bool,
    ) -> tuple[int, int, int]:
        added = 0
        conflicts = 0
        touched = 0
        profile.setdefault("conflicts", [])

        for key in self.PROFILE_KEYS:
            values = self._to_str_list(profile.get(key))
            seen = {self._norm_text(v) for v in values}
            for candidate in self._to_str_list(updates.get(key)):
                normalized = self._norm_text(candidate)
                if not normalized:
                    continue

                if normalized in seen:
                    entry = self._meta_entry(profile, key, candidate)
                    self._touch_meta_entry(entry, confidence_delta=0.03, status=self.PROFILE_STATUS_ACTIVE)
                    touched += 1
                    continue

                has_conflict = False
                if enable_contradiction_check:
                    for existing in values:
                        if self._conflict_pair(existing, candidate):
                            has_conflict = True
                            old_entry = self._meta_entry(profile, key, existing)
                            self._touch_meta_entry(
                                old_entry,
                                confidence_delta=-0.12,
                                status=self.PROFILE_STATUS_CONFLICTED,
                            )
                            new_entry = self._meta_entry(profile, key, candidate)
                            self._touch_meta_entry(
                                new_entry,
                                confidence_delta=-0.2,
                                min_confidence=0.35,
                                status=self.PROFILE_STATUS_CONFLICTED,
                            )
                            profile["conflicts"].append(
                                {
                                    "timestamp": self._utc_now_iso(),
                                    "field": key,
                                    "old": existing,
                                    "new": candidate,
                                    "status": "open",
                                    "old_confidence": old_entry.get("confidence"),
                                    "new_confidence": new_entry.get("confidence"),
                                }
                            )
                            conflicts += 1
                            touched += 2
                            break

                values.append(candidate)
                seen.add(normalized)
                entry = self._meta_entry(profile, key, candidate)
                if not has_conflict:
                    self._touch_meta_entry(entry, confidence_delta=0.1, status=self.PROFILE_STATUS_ACTIVE)
                    touched += 1
                added += 1

            profile[key] = values

        if conflicts > 0:
            self._record_metric("conflicts_detected", conflicts)
        if added > 0:
            self._record_metric("profile_updates_applied", added)
        return added, conflicts, touched

    def read_long_term(self) -> str:
        return self.persistence.read_text(self.memory_file)

    def write_long_term(self, content: str) -> None:
        self.persistence.write_text(self.memory_file, content)

    def append_history(self, entry: str) -> None:
        self.persistence.append_text(self.history_file, entry.rstrip() + "\n\n")

    def rebuild_memory_snapshot(self, *, max_events: int = 30, write: bool = True) -> str:
        profile = self.read_profile()
        events = self.read_events(limit=max_events)

        parts = ["# Memory", ""]
        section_lines = self._profile_section_lines(profile, max_items_per_section=8)
        if section_lines:
            parts.extend(section_lines)

        unresolved = self._recent_unresolved(events, max_items=6)
        if unresolved:
            parts.append("## Open Tasks & Decisions")
            for event in unresolved:
                ts = str(event.get("timestamp", ""))[:16]
                parts.append(f"- [{ts}] ({event.get('type', 'task')}) {event.get('summary', '')}")
            parts.append("")

        if events:
            parts.append("## Recent Episodic Highlights")
            for event in events[-max_events:]:
                ts = str(event.get("timestamp", ""))[:16]
                parts.append(f"- [{ts}] ({event.get('type', 'fact')}) {event.get('summary', '')}")
        snapshot = "\n".join(parts).strip() + "\n"
        if write:
            self.write_long_term(snapshot)
        return snapshot

    def verify_memory(self, *, stale_days: int = 90, update_profile: bool = False) -> dict[str, Any]:
        profile = self.read_profile()
        events = self.read_events()
        now = datetime.now(timezone.utc)
        stale = 0
        total_ttl = 0
        for event in events:
            ttl_days = event.get("ttl_days")
            timestamp = self._to_datetime(str(event.get("timestamp", "")))
            if not timestamp:
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age_days = (now - timestamp).total_seconds() / 86400.0
            if isinstance(ttl_days, int) and ttl_days > 0:
                total_ttl += 1
                if age_days > ttl_days:
                    stale += 1
            elif age_days > stale_days:
                stale += 1

        stale_profile_items = 0
        profile_touched = False
        for key in self.PROFILE_KEYS:
            section_meta = self._meta_section(profile, key)
            for _, entry in section_meta.items():
                if not isinstance(entry, dict):
                    continue
                last_seen = self._to_datetime(str(entry.get("last_seen_at", "")))
                if not last_seen:
                    continue
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                age_days = max((now - last_seen).total_seconds() / 86400.0, 0.0)
                if age_days > stale_days:
                    stale_profile_items += 1
                    if update_profile and entry.get("status") != self.PROFILE_STATUS_STALE:
                        entry["status"] = self.PROFILE_STATUS_STALE
                        profile_touched = True

        if update_profile:
            profile["last_verified_at"] = self._utc_now_iso()
            profile_touched = True
            if profile_touched:
                self.write_profile(profile)

        open_conflicts = [c for c in profile.get("conflicts", []) if isinstance(c, dict) and c.get("status") == "open"]
        report = {
            "events": len(events),
            "profile_items": sum(len(self._to_str_list(profile.get(k))) for k in self.PROFILE_KEYS),
            "open_conflicts": len(open_conflicts),
            "stale_events": stale,
            "stale_profile_items": stale_profile_items,
            "ttl_tracked_events": total_ttl,
            "last_verified_at": profile.get("last_verified_at"),
        }
        return report

    def _select_messages_for_consolidation(
        self,
        session: Session,
        *,
        archive_all: bool,
        memory_window: int,
    ) -> tuple[list[dict[str, Any]], int, int] | None:
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            source_start = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
            return old_messages, keep_count, source_start

        keep_count = memory_window // 2
        if len(session.messages) <= keep_count:
            return None
        if len(session.messages) - session.last_consolidated <= 0:
            return None
        old_messages = session.messages[session.last_consolidated:-keep_count]
        source_start = session.last_consolidated
        if not old_messages:
            return None
        logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)
        return old_messages, keep_count, source_start

    @staticmethod
    def _format_conversation_lines(old_messages: list[dict[str, Any]]) -> list[str]:
        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")
        return lines

    @staticmethod
    def _build_consolidation_prompt(current_memory: str, lines: list[str]) -> str:
        return f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

    def _record_consolidation_input_metrics(self, old_messages: list[dict[str, Any]]) -> None:
        user_messages = [m for m in old_messages if str(m.get("role", "")).lower() == "user"]
        user_corrections = self._count_user_corrections(old_messages)
        self._record_metrics(
            {
                "messages_processed": len(old_messages),
                "user_messages_processed": len(user_messages),
                "user_corrections": user_corrections,
            }
        )

    def _apply_save_memory_tool_result(self, *, args: dict[str, Any], current_memory: str) -> None:
        if entry := args.get("history_entry"):
            if not isinstance(entry, str):
                entry = json.dumps(entry, ensure_ascii=False)
            self.append_history(entry)
        if update := args.get("memory_update"):
            if not isinstance(update, str):
                update = json.dumps(update, ensure_ascii=False)
            if update != current_memory:
                self.write_long_term(update)

    async def _apply_hybrid_consolidation(
        self,
        *,
        provider: LLMProvider,
        model: str,
        lines: list[str],
        old_messages: list[dict[str, Any]],
        source_start: int,
        retrieval_k: int,
        token_budget: int,
        recency_half_life_days: float,
        enable_contradiction_check: bool,
        embedding_provider: str | None,
    ) -> None:
        profile = self.read_profile()
        events, profile_updates = await self._extract_structured_memory(
            provider,
            model,
            profile,
            lines,
            old_messages,
            source_start=source_start,
        )
        events_written = self.append_events(events)
        profile_added, _, profile_touched = self._apply_profile_updates(
            profile,
            profile_updates,
            enable_contradiction_check=enable_contradiction_check,
        )
        if events_written > 0 or profile_added > 0 or profile_touched > 0:
            profile["last_verified_at"] = self._utc_now_iso()
            self.write_profile(profile)
            self._record_metric("events_extracted", events_written)

        self.rebuild_memory_snapshot(write=True)
        _ = self.get_memory_context(
            mode="hybrid",
            query="",
            retrieval_k=retrieval_k,
            token_budget=token_budget,
            recency_half_life_days=recency_half_life_days,
            embedding_provider=embedding_provider,
        )

    def _finalize_consolidation(self, session: Session, *, archive_all: bool, keep_count: int) -> None:
        session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
        self._record_metric("consolidations", 1)
        logger.debug("Memory KPI snapshot: {}", self.get_observability_report().get("kpis", {}))
        logger.info(
            "Memory consolidation done: {} messages, last_consolidated={}",
            len(session.messages),
            session.last_consolidated,
        )

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        memory_mode: str = "legacy",
        retrieval_k: int = 6,
        token_budget: int = 900,
        recency_half_life_days: float = 30.0,
        enable_contradiction_check: bool = True,
        embedding_provider: str | None = None,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        """
        selection = self._select_messages_for_consolidation(
            session,
            archive_all=archive_all,
            memory_window=memory_window,
        )
        if selection is None:
            return True
        old_messages, keep_count, source_start = selection

        lines = self._format_conversation_lines(old_messages)

        current_memory = self.read_long_term()
        prompt = self._build_consolidation_prompt(current_memory, lines)

        try:
            self._record_consolidation_input_metrics(old_messages)

            response = await provider.chat(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation."},
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = self._parse_tool_args(response.tool_calls[0].arguments)
            if not args:
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            self._apply_save_memory_tool_result(args=args, current_memory=current_memory)

            if memory_mode == "hybrid":
                await self._apply_hybrid_consolidation(
                    provider=provider,
                    model=model,
                    lines=lines,
                    old_messages=old_messages,
                    source_start=source_start,
                    retrieval_k=retrieval_k,
                    token_budget=token_budget,
                    recency_half_life_days=recency_half_life_days,
                    enable_contradiction_check=enable_contradiction_check,
                    embedding_provider=embedding_provider,
                )

            self._finalize_consolidation(
                session,
                archive_all=archive_all,
                keep_count=keep_count,
            )
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
