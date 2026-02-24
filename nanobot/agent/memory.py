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

from nanobot.agent.memory_embeddings import MemoryEmbedder, cosine_similarity
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


class MemoryStore:
    """Hybrid memory: markdown files + structured events/profile/metrics."""

    PROFILE_KEYS = ("preferences", "stable_facts", "active_projects", "relationships", "constraints")
    EVENT_TYPES = {"preference", "fact", "task", "decision", "constraint", "relationship"}
    PROFILE_STATUS_ACTIVE = "active"
    PROFILE_STATUS_CONFLICTED = "conflicted"
    PROFILE_STATUS_STALE = "stale"

    def __init__(self, workspace: Path, embedding_provider: str = ""):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.events_file = self.memory_dir / "events.jsonl"
        self.profile_file = self.memory_dir / "profile.json"
        self.metrics_file = self.memory_dir / "metrics.json"
        self.index_dir = ensure_dir(self.memory_dir / "index")
        self.embedding_provider = embedding_provider or "hash"
        self._embedder: MemoryEmbedder | None = None

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
        if self.metrics_file.exists():
            try:
                data = json.loads(self.metrics_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                logger.warning("Failed to parse memory metrics, resetting")
        return {
            "consolidations": 0,
            "events_extracted": 0,
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
        slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", provider.strip().lower())
        return slug or "hash"

    def _get_embedder(self, embedding_provider: str | None = None) -> MemoryEmbedder:
        requested = (embedding_provider or self.embedding_provider or "hash").strip()
        if self._embedder is None or self._embedder.requested_provider != requested:
            self._embedder = MemoryEmbedder(requested)
        return self._embedder

    def _index_file(self, provider: str) -> Path:
        return self.index_dir / f"vectors_{self._provider_slug(provider)}.json"

    def _event_text(self, event: dict[str, Any]) -> str:
        summary = str(event.get("summary", ""))
        entities = " ".join(self._to_str_list(event.get("entities")))
        event_type = str(event.get("type", "fact"))
        return f"{event_type}. {summary}. {entities}".strip()

    def _load_vector_index(self, provider: str) -> dict[str, Any]:
        path = self._index_file(provider)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("items"), dict):
                    return data
            except Exception:
                logger.warning("Failed to parse vector index '{}', rebuilding", path)
        return {
            "provider": provider,
            "updated_at": self._utc_now_iso(),
            "items": {},
        }

    def _save_vector_index(self, provider: str, index_data: dict[str, Any]) -> None:
        path = self._index_file(provider)
        index_data["provider"] = provider
        index_data["updated_at"] = self._utc_now_iso()
        path.write_text(json.dumps(index_data, ensure_ascii=False), encoding="utf-8")

    def _ensure_event_embeddings(
        self,
        events: list[dict[str, Any]],
        *,
        embedding_provider: str | None = None,
    ) -> tuple[dict[str, list[float]], str]:
        embedder = self._get_embedder(embedding_provider)
        provider = embedder.provider_name
        index_data = self._load_vector_index(provider)
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
            missing_texts.append(self._event_text(event))

        if missing_ids:
            vectors = embedder.embed_texts(missing_texts)
            for event_id, vector in zip(missing_ids, vectors, strict=False):
                items[event_id] = [float(x) for x in vector]
            index_data["items"] = items
            index_data["dim"] = len(next(iter(items.values()))) if items else 0
            self._save_vector_index(provider, index_data)
            self._record_metric("index_updates", len(missing_ids))

        return items, provider

    def _record_metric(self, key: str, delta: int = 1) -> None:
        self._record_metrics({key: delta})

    def _record_metrics(self, deltas: dict[str, int]) -> None:
        metrics = self._load_metrics()
        for key, delta in deltas.items():
            metrics[key] = int(metrics.get(key, 0)) + int(delta)
        metrics["last_updated"] = self._utc_now_iso()
        self.metrics_file.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

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

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.events_file.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(self.events_file, encoding="utf-8") as f:
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
        if limit is not None and limit > 0:
            return out[-limit:]
        return out

    def append_events(self, events: list[dict[str, Any]]) -> int:
        if not events:
            return 0
        existing_ids = {e.get("id") for e in self.read_events() if e.get("id")}
        written = 0
        written_events: list[dict[str, Any]] = []
        with open(self.events_file, "a", encoding="utf-8") as f:
            for event in events:
                event_id = event.get("id")
                if not event_id or event_id in existing_ids:
                    continue
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
                existing_ids.add(event_id)
                written += 1
                written_events.append(event)
        if written_events:
            self._ensure_event_embeddings(written_events, embedding_provider=self.embedding_provider)
        return written

    def read_profile(self) -> dict[str, Any]:
        if self.profile_file.exists():
            try:
                data = json.loads(self.profile_file.read_text(encoding="utf-8"))
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
            except Exception:
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

    def write_profile(self, profile: dict[str, Any]) -> None:
        profile["updated_at"] = self._utc_now_iso()
        self.profile_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

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
        q = self._tokenize(query)
        t = self._tokenize(text)
        if not q or not t:
            return 0.0
        common = len(q & t)
        denom = len(q | t)
        return common / denom if denom else 0.0

    def _recency_score(self, timestamp: str, half_life_days: float) -> float:
        dt = self._to_datetime(timestamp)
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
    ) -> list[dict[str, Any]]:
        events = self.read_events()
        if not events:
            self._record_metric("retrieval_queries", 1)
            return []

        vectors_by_id, active_provider = self._ensure_event_embeddings(
            events,
            embedding_provider=embedding_provider,
        )
        query_vec: list[float] | None = None
        if query.strip():
            query_vec = self._get_embedder(active_provider).embed_texts([query])[0]

        scored: list[dict[str, Any]] = []
        for event in events:
            summary = str(event.get("summary", ""))
            entities = " ".join(self._to_str_list(event.get("entities")))
            text = f"{summary} {entities}".strip()
            lex = self._lexical_similarity(query, text) if query.strip() else 0.0
            event_vec = vectors_by_id.get(str(event.get("id", "")))
            sem = cosine_similarity(query_vec, event_vec) if (query_vec and event_vec) else 0.0
            rec = self._recency_score(str(event.get("timestamp", "")), recency_half_life_days)
            sal = min(max(self._safe_float(event.get("salience"), 0.6), 0.0), 1.0)
            conf = min(max(self._safe_float(event.get("confidence"), 0.7), 0.0), 1.0)
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
            }
            scored.append(event_copy)

        scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        result = scored[: max(1, top_k)]
        self._record_metric("retrieval_queries", 1)
        if result:
            self._record_metric("retrieval_hits", 1)
        return result

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
            scored_values: list[tuple[str, float]] = []
            for value in values:
                meta = section_meta.get(self._norm_text(value), {}) if isinstance(section_meta, dict) else {}
                status = meta.get("status") if isinstance(meta, dict) else None
                if status == self.PROFILE_STATUS_STALE:
                    continue
                conf = self._safe_float(meta.get("confidence") if isinstance(meta, dict) else None, 0.65)
                scored_values.append((value, conf))
            scored_values.sort(key=lambda item: item[1], reverse=True)
            if not scored_values:
                continue
            lines.append(f"### {title_map[key]}")
            for item, confidence in scored_values[:max_items_per_section]:
                lines.append(f"- {item} (conf={confidence:.2f})")
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
            self.metrics_file.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2), encoding="utf-8")
        return text

    def _default_profile_updates(self) -> dict[str, list[str]]:
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }

    def _count_user_corrections(self, messages: list[dict[str, Any]]) -> int:
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

    def _parse_tool_args(self, args: Any) -> dict[str, Any] | None:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        return args if isinstance(args, dict) else None

    def _heuristic_extract_events(
        self,
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        updates = self._default_profile_updates()
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
            event = self._coerce_event(
                {
                    "timestamp": message.get("timestamp") or self._utc_now_iso(),
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
                args = self._parse_tool_args(response.tool_calls[0].arguments)
                if args:
                    raw_events = args.get("events") if isinstance(args.get("events"), list) else []
                    raw_updates = args.get("profile_updates") if isinstance(args.get("profile_updates"), dict) else {}
                    updates = self._default_profile_updates()
                    for key in updates:
                        updates[key] = self._to_str_list(raw_updates.get(key))

                    events: list[dict[str, Any]] = []
                    for offset, item in enumerate(raw_events):
                        if not isinstance(item, dict):
                            continue
                        source_span = item.get("source_span")
                        if (
                            not isinstance(source_span, list)
                            or len(source_span) != 2
                            or not all(isinstance(x, int) for x in source_span)
                        ):
                            source_span = [source_start, source_start + max(len(old_messages) - 1, 0)]
                        event = self._coerce_event(item, source_span=source_span)
                        if event:
                            events.append(event)
                        if len(events) >= 40:
                            break
                    return events, updates
        except Exception:
            logger.exception("Structured event extraction failed, falling back to heuristic extraction")

        return self._heuristic_extract_events(old_messages, source_start=source_start)

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
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

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
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            source_start = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated:-keep_count]
            source_start = session.last_consolidated
            if not old_messages:
                return True
            logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            user_messages = [m for m in old_messages if str(m.get("role", "")).lower() == "user"]
            user_corrections = self._count_user_corrections(old_messages)
            self._record_metrics(
                {
                    "messages_processed": len(old_messages),
                    "user_messages_processed": len(user_messages),
                    "user_corrections": user_corrections,
                }
            )

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

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            if memory_mode == "hybrid":
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

                # Keep MEMORY.md synchronized with profile/events while preserving token budget.
                self.rebuild_memory_snapshot(write=True)
                # Trigger retrieval once to update hit-rate observability for hybrid mode.
                _ = self.get_memory_context(
                    mode="hybrid",
                    query="",
                    retrieval_k=retrieval_k,
                    token_budget=token_budget,
                    recency_half_life_days=recency_half_life_days,
                    embedding_provider=embedding_provider,
                )

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            self._record_metric("consolidations", 1)
            logger.debug("Memory KPI snapshot: {}", self.get_observability_report().get("kpis", {}))
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
