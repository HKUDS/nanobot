"""Memory system for persistent and short-term agent memory."""

from __future__ import annotations

import json
import math
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import ensure_dir, timestamp, today_date


class MemoryStore:
    """
    Memory system for the agent.

    Supports:
    - Daily notes (memory/YYYY-MM-DD.md)
    - Legacy long-term notes (memory/MEMORY.md)
    - RAM-first long-term snapshot (memory/LTM_SNAPSHOT.json)
    - Session short-term working memory (in-memory only)
    """

    DEFAULT_FLUSH_EVERY_UPDATES = 8
    DEFAULT_FLUSH_INTERVAL_SECONDS = 120
    DEFAULT_SHORT_TERM_TURNS = 12
    DEFAULT_PENDING_LIMIT = 20
    DEFAULT_MAX_LTM_ITEMS = 300
    DEFAULT_MAX_LESSONS = 200
    DEFAULT_MAX_LESSONS_IN_PROMPT = 5
    DEFAULT_MIN_LESSON_CONFIDENCE = 1

    def __init__(
        self,
        workspace: Path,
        flush_every_updates: int = DEFAULT_FLUSH_EVERY_UPDATES,
        flush_interval_seconds: int = DEFAULT_FLUSH_INTERVAL_SECONDS,
        short_term_turns: int = DEFAULT_SHORT_TERM_TURNS,
        pending_limit: int = DEFAULT_PENDING_LIMIT,
        self_improvement_enabled: bool = True,
        max_lessons_in_prompt: int = DEFAULT_MAX_LESSONS_IN_PROMPT,
        min_lesson_confidence: int = DEFAULT_MIN_LESSON_CONFIDENCE,
        max_lessons: int = DEFAULT_MAX_LESSONS,
    ):
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.snapshot_file = self.memory_dir / "LTM_SNAPSHOT.json"
        self.audit_file = self.memory_dir / "LTM_AUDIT.jsonl"
        self.lessons_file = self.memory_dir / "LESSONS.jsonl"
        self.lessons_audit_file = self.memory_dir / "LESSONS_AUDIT.jsonl"

        self.flush_every_updates = max(1, flush_every_updates)
        self.flush_interval_seconds = max(1, flush_interval_seconds)
        self.short_term_turns = max(1, short_term_turns)
        self.pending_limit = max(1, pending_limit)
        self.self_improvement_enabled = self_improvement_enabled
        self.max_lessons_in_prompt = max(1, max_lessons_in_prompt)
        self.min_lesson_confidence = min_lesson_confidence
        self.max_lessons = max(1, max_lessons)

        self._loaded = False
        self._snapshot: dict[str, Any] = {"version": 1, "updated_at": timestamp(), "items": []}
        self._short_term: dict[str, deque[dict[str, str]]] = {}
        self._pending: dict[str, deque[str]] = {}
        self._lessons: list[dict[str, Any]] = []
        self._dirty_updates = 0
        self._last_flush_monotonic = time.monotonic()
        self._audit_buffer: list[dict[str, Any]] = []
        self._lessons_audit_buffer: list[dict[str, Any]] = []
        self._snapshot_dirty = False
        self._lessons_dirty = False

    def get_today_file(self) -> Path:
        """Get path to today's memory file."""
        return self.memory_dir / f"{today_date()}.md"

    def read_today(self) -> str:
        """Read today's memory notes."""
        today_file = self.get_today_file()
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""

    def append_today(self, content: str) -> None:
        """Append content to today's memory notes."""
        today_file = self.get_today_file()

        if today_file.exists():
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n" + content
        else:
            header = f"# {today_date()}\n\n"
            content = header + content

        today_file.write_text(content, encoding="utf-8")

    def read_long_term(self) -> str:
        """Read legacy long-term memory (MEMORY.md)."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """Write to legacy long-term memory (MEMORY.md)."""
        self.memory_file.write_text(content, encoding="utf-8")

    def get_recent_memories(self, days: int = 7) -> str:
        """Get memories from the last N days."""
        from datetime import timedelta

        memories = []
        today = datetime.now().date()

        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            file_path = self.memory_dir / f"{date_str}.md"

            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                memories.append(content)

        return "\n\n---\n\n".join(memories)

    def list_memory_files(self) -> list[Path]:
        """List all memory files sorted by date (newest first)."""
        if not self.memory_dir.exists():
            return []

        files = list(self.memory_dir.glob("????-??-??.md"))
        return sorted(files, reverse=True)

    def remember(
        self,
        text: str,
        session_key: str | None = None,
        source: str = "explicit_user",
        immediate: bool = False,
    ) -> bool:
        """
        Add or update a long-term memory item.

        Returns:
            True if a memory item was added/updated.
        """
        self._load_once()
        cleaned = self._clean_text(text, max_len=280)
        if not cleaned:
            return False

        norm = self._normalize_text(cleaned)
        now = timestamp()
        items = self._snapshot["items"]

        existing = None
        for item in items:
            if self._normalize_text(item.get("text", "")) == norm:
                existing = item
                break

        if existing:
            previous = existing.get("text", "")
            existing["text"] = cleaned
            existing["updated_at"] = now
            if session_key:
                existing["session_key"] = session_key
            existing["hits"] = int(existing.get("hits", 0)) + 1
            self._audit_buffer.append(
                {
                    "type": "memory_update",
                    "at": now,
                    "id": existing.get("id", ""),
                    "source": source,
                    "before": previous,
                    "after": cleaned,
                }
            )
        else:
            item_id = f"ltm_{int(time.time() * 1000)}_{len(items) + 1}"
            items.append(
                {
                    "id": item_id,
                    "text": cleaned,
                    "source": source,
                    "session_key": session_key or "",
                    "created_at": now,
                    "updated_at": now,
                    "hits": 1,
                }
            )
            self._audit_buffer.append(
                {
                    "type": "memory_add",
                    "at": now,
                    "id": item_id,
                    "source": source,
                    "text": cleaned,
                }
            )

        self._snapshot["updated_at"] = now
        self._dirty_updates += 1
        self._snapshot_dirty = True
        self.compact(max_items=self.DEFAULT_MAX_LTM_ITEMS, auto_flush=False)

        if immediate:
            self.flush(force=True)
        else:
            self.flush_if_needed()
        return True

    def record_turn(
        self,
        session_key: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Update short-term memory and learn explicit long-term rules from the turn."""
        self._load_once()

        turns = self._short_term.setdefault(session_key, deque(maxlen=self.short_term_turns))
        turns.append(
            {
                "user": self._clean_text(user_message, max_len=320),
                "assistant": self._clean_text(assistant_message, max_len=320),
            }
        )

        pending_item = self._extract_pending_item(user_message)
        if pending_item:
            queue = self._pending.setdefault(session_key, deque(maxlen=self.pending_limit))
            queue.append(pending_item)

        if self._is_pending_resolved(user_message):
            queue = self._pending.get(session_key)
            if queue:
                queue.popleft()

        explicit_memories = self._extract_explicit_memories(user_message)
        for fact in explicit_memories:
            self.remember(fact, session_key=session_key, source="explicit_user", immediate=True)

        self.flush_if_needed()

    def learn_lesson(
        self,
        trigger: str,
        bad_action: str,
        better_action: str,
        session_key: str | None = None,
        source: str = "unknown",
        scope: str = "session",
        confidence_delta: int = 1,
        immediate: bool = False,
    ) -> bool:
        """
        Add or update a self-improvement lesson.

        Returns:
            True if a lesson was added/updated.
        """
        self._load_once()
        if not self.self_improvement_enabled:
            return False

        trigger = self._clean_text(trigger, max_len=120)
        bad_action = self._clean_text(bad_action, max_len=260)
        better_action = self._clean_text(better_action, max_len=260)
        if not trigger or not better_action:
            return False

        now = timestamp()
        scope = "session" if scope == "session" else "global"
        lesson_key = self._lesson_key(trigger, better_action, scope, session_key)

        existing = None
        for lesson in self._lessons:
            if lesson.get("key") == lesson_key:
                existing = lesson
                break

        delta = max(1, confidence_delta)
        if existing:
            existing["updated_at"] = now
            existing["bad_action"] = bad_action or existing.get("bad_action", "")
            existing["better_action"] = better_action
            existing["hits"] = int(existing.get("hits", 0)) + 1
            existing["confidence"] = min(10, int(existing.get("confidence", 1)) + delta)
            self._lessons_audit_buffer.append(
                {
                    "type": "lesson_update",
                    "at": now,
                    "id": existing.get("id", ""),
                    "source": source,
                    "confidence": existing["confidence"],
                }
            )
        else:
            lesson_id = f"lesson_{int(time.time() * 1000)}_{len(self._lessons) + 1}"
            self._lessons.append(
                {
                    "id": lesson_id,
                    "key": lesson_key,
                    "trigger": trigger,
                    "bad_action": bad_action,
                    "better_action": better_action,
                    "scope": scope,
                    "session_key": session_key if scope == "session" else "",
                    "source": source,
                    "confidence": max(self.min_lesson_confidence, delta),
                    "hits": 1,
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                    "last_applied_at": "",
                }
            )
            self._lessons_audit_buffer.append(
                {
                    "type": "lesson_add",
                    "at": now,
                    "id": lesson_id,
                    "source": source,
                    "trigger": trigger,
                }
            )

        self._lessons_dirty = True
        self._dirty_updates += 1
        self.compact_lessons(max_lessons=self.max_lessons, auto_flush=False)

        if immediate:
            self.flush(force=True)
        else:
            self.flush_if_needed()
        return True

    def record_tool_feedback(self, session_key: str, tool_name: str, result: str) -> bool:
        """Learn lesson from a tool execution result."""
        self._load_once()
        if not self.self_improvement_enabled:
            return False

        if self._is_tool_error(result):
            better_action = self._suggest_tool_better_action(tool_name, result)
            return self.learn_lesson(
                trigger=f"tool:{tool_name}:error",
                bad_action=result,
                better_action=better_action,
                session_key=session_key,
                source="tool_feedback",
                scope="session",
                confidence_delta=1,
                immediate=False,
            )

        # If a tool succeeds after previous failures, slightly reinforce existing
        # tool lessons for this session.
        now = timestamp()
        updated = False
        for lesson in self._lessons:
            if (
                lesson.get("enabled", True)
                and lesson.get("scope") == "session"
                and lesson.get("session_key") == session_key
                and lesson.get("trigger") == f"tool:{tool_name}:error"
            ):
                lesson["confidence"] = min(10, int(lesson.get("confidence", 1)) + 1)
                lesson["updated_at"] = now
                lesson["hits"] = int(lesson.get("hits", 0)) + 1
                lesson["last_applied_at"] = now
                updated = True
                self._lessons_audit_buffer.append(
                    {
                        "type": "lesson_reinforced",
                        "at": now,
                        "id": lesson.get("id", ""),
                        "source": "tool_success",
                    }
                )
                break

        if updated:
            self._lessons_dirty = True
            self._dirty_updates += 1
            self.flush_if_needed()
        return updated

    def record_user_feedback(
        self, session_key: str, user_message: str, previous_assistant: str | None = None
    ) -> bool:
        """Learn lesson from explicit user correction/feedback."""
        self._load_once()
        if not self.self_improvement_enabled:
            return False

        feedback = self._extract_feedback_signal(user_message)
        if not feedback:
            return False

        trigger, better_action = feedback
        bad_action = previous_assistant or "(No previous assistant content available.)"
        return self.learn_lesson(
            trigger=trigger,
            bad_action=bad_action,
            better_action=better_action,
            session_key=session_key,
            source="user_feedback",
            scope="session",
            confidence_delta=2,
            immediate=True,
        )

    def flush_if_needed(self, force: bool = False) -> bool:
        """Flush snapshot/audit to disk when thresholds are reached."""
        self._load_once()
        has_pending = (
            self._dirty_updates > 0
            or self._snapshot_dirty
            or self._lessons_dirty
            or bool(self._audit_buffer)
            or bool(self._lessons_audit_buffer)
        )

        if not has_pending:
            return False

        if force:
            self._flush_to_disk()
            return True

        elapsed = time.monotonic() - self._last_flush_monotonic
        should_flush = (
            self._dirty_updates >= self.flush_every_updates
            or elapsed >= self.flush_interval_seconds
        )
        if not should_flush:
            return False

        self._flush_to_disk()
        return True

    def flush(self, force: bool = False) -> bool:
        """Flush memory state to disk."""
        return self.flush_if_needed(force=force)

    def compact(self, max_items: int = DEFAULT_MAX_LTM_ITEMS, auto_flush: bool = True) -> int:
        """
        Compact long-term snapshot by deduplicating and capping size.

        Returns:
            Number of removed items.
        """
        self._load_once()
        max_items = max(1, max_items)
        items = self._snapshot.get("items", [])
        if not items:
            return 0

        dedup: dict[str, dict[str, Any]] = {}
        for item in sorted(items, key=lambda x: x.get("updated_at", ""), reverse=True):
            norm = self._normalize_text(item.get("text", ""))
            if norm and norm not in dedup:
                dedup[norm] = item

        compacted = list(dedup.values())[:max_items]
        removed = len(items) - len(compacted)
        if removed <= 0:
            return 0

        self._snapshot["items"] = compacted
        self._snapshot["updated_at"] = timestamp()
        self._dirty_updates += 1
        self._snapshot_dirty = True
        self._audit_buffer.append(
            {"type": "memory_compact", "at": timestamp(), "removed": removed, "kept": len(compacted)}
        )

        if auto_flush:
            self.flush_if_needed()
        return removed

    def compact_lessons(self, max_lessons: int | None = None, auto_flush: bool = True) -> int:
        """
        Compact lessons by deduplicating and capping size.

        Returns:
            Number of removed lessons.
        """
        self._load_once()
        if not self.self_improvement_enabled:
            return 0

        max_keep = max(1, max_lessons or self.max_lessons)
        original_count = len(self._lessons)
        if original_count == 0:
            return 0

        dedup: dict[str, dict[str, Any]] = {}
        sorted_lessons = sorted(
            self._lessons,
            key=lambda x: (
                int(x.get("confidence", 0)),
                int(x.get("hits", 0)),
                x.get("updated_at", ""),
            ),
            reverse=True,
        )
        for lesson in sorted_lessons:
            if not lesson.get("enabled", True):
                continue
            if int(lesson.get("confidence", 0)) < self.min_lesson_confidence:
                continue
            key = str(lesson.get("key", ""))
            if key and key not in dedup:
                dedup[key] = lesson

        compacted = list(dedup.values())[:max_keep]
        removed = original_count - len(compacted)
        if removed <= 0:
            return 0

        self._lessons = compacted
        self._lessons_dirty = True
        self._dirty_updates += 1
        self._lessons_audit_buffer.append(
            {"type": "lesson_compact", "at": timestamp(), "removed": removed, "kept": len(compacted)}
        )

        if auto_flush:
            self.flush_if_needed()
        return removed

    def reset_lessons(self) -> int:
        """Reset all lessons and return removed count."""
        self._load_once()
        removed = len(self._lessons)
        if removed == 0:
            return 0

        self._lessons = []
        self._lessons_dirty = True
        self._dirty_updates += 1
        self._lessons_audit_buffer.append(
            {"type": "lesson_reset", "at": timestamp(), "removed": removed}
        )
        self.flush(force=True)
        return removed

    def get_lessons_for_context(
        self,
        session_key: str | None = None,
        current_message: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Select top lessons for prompt context."""
        self._load_once()
        if not self.self_improvement_enabled:
            return []

        max_items = max(1, limit or self.max_lessons_in_prompt)
        lessons = []
        for lesson in self._lessons:
            if not lesson.get("enabled", True):
                continue
            confidence = int(lesson.get("confidence", 0))
            if confidence < self.min_lesson_confidence:
                continue
            scope = lesson.get("scope", "session")
            lesson_session = lesson.get("session_key", "")
            if scope == "session" and session_key and lesson_session != session_key:
                continue
            if scope == "session" and not session_key:
                continue
            lessons.append(lesson)

        if not lessons:
            return []

        query_tokens = self._tokenize(current_message or "")

        def _score(item: dict[str, Any]) -> tuple[float, int, int, str]:
            text = " ".join(
                [
                    str(item.get("trigger", "")),
                    str(item.get("bad_action", "")),
                    str(item.get("better_action", "")),
                ]
            )
            lesson_tokens = self._tokenize(text)
            overlap = len(query_tokens & lesson_tokens) if query_tokens else 0
            overlap_score = float(overlap) if overlap > 0 else 0.0
            # Mild recency bonus based on ISO timestamp year-month-day precision.
            recency = item.get("updated_at", "")
            recency_bonus = 0.0
            if recency:
                try:
                    dt = datetime.fromisoformat(str(recency))
                    age_hours = max(0.0, (datetime.now() - dt).total_seconds() / 3600)
                    recency_bonus = 1.0 / (1.0 + math.log1p(age_hours))
                except Exception:
                    recency_bonus = 0.0
            return (
                overlap_score + recency_bonus,
                int(item.get("confidence", 0)),
                int(item.get("hits", 0)),
                str(recency),
            )

        lessons.sort(key=_score, reverse=True)
        return lessons[:max_items]

    def get_status(self) -> dict[str, Any]:
        """Get in-memory status and snapshot statistics."""
        self._load_once()
        return {
            "snapshot_path": str(self.snapshot_file),
            "audit_path": str(self.audit_file),
            "ltm_items": len(self._snapshot.get("items", [])),
            "short_term_sessions": len(self._short_term),
            "pending_sessions": len(self._pending),
            "dirty_updates": self._dirty_updates,
            "flush_every_updates": self.flush_every_updates,
            "flush_interval_seconds": self.flush_interval_seconds,
            "last_snapshot_at": self._snapshot.get("updated_at", ""),
            "snapshot_exists": self.snapshot_file.exists(),
            "lessons_file": str(self.lessons_file),
            "lessons_audit_file": str(self.lessons_audit_file),
            "self_improvement_enabled": self.self_improvement_enabled,
            "lessons_count": len(self._lessons),
            "max_lessons_in_prompt": self.max_lessons_in_prompt,
            "min_lesson_confidence": self.min_lesson_confidence,
            "max_lessons": self.max_lessons,
        }

    def get_memory_context(
        self, session_key: str | None = None, current_message: str | None = None
    ) -> str:
        """
        Get memory context for the agent.

        Args:
            session_key: Optional session key for short-term/pending memory.
            current_message: Optional current user message for lesson relevance.

        Returns:
            Formatted memory context including long-term and short-term memories.
        """
        self._load_once()
        parts: list[str] = []

        lessons = self.get_lessons_for_context(
            session_key=session_key,
            current_message=current_message,
            limit=self.max_lessons_in_prompt,
        )
        if lessons:
            lesson_lines = [
                f"- When {lesson['trigger']}: {lesson['better_action']} "
                f"(confidence={lesson.get('confidence', 1)})"
                for lesson in lessons
            ]
            parts.append("## Lessons\n" + "\n".join(lesson_lines))

        snapshot_items = self._select_snapshot_items(session_key=session_key, limit=8)
        if snapshot_items:
            lines = [f"- {item['text']}" for item in snapshot_items]
            parts.append("## Long-term Memory (Snapshot)\n" + "\n".join(lines))

        long_term = self.read_long_term()
        if long_term:
            if snapshot_items:
                legacy = self._clean_text(long_term, max_len=900)
                parts.append("## Legacy Long-term Notes\n" + legacy)
            else:
                parts.append("## Long-term Memory\n" + long_term)

        today = self.read_today()
        if today:
            parts.append("## Today's Notes\n" + today)

        if session_key:
            turns = self._short_term.get(session_key)
            if turns:
                short_lines = []
                for turn in list(turns)[-6:]:
                    user = turn.get("user", "")
                    assistant = turn.get("assistant", "")
                    short_lines.append(f"- User: {user}\n  Assistant: {assistant}")
                parts.append("## Short-term Working Memory\n" + "\n".join(short_lines))

            pending = self._pending.get(session_key)
            if pending:
                pending_lines = [f"- {item}" for item in list(pending)]
                parts.append("## Pending Items\n" + "\n".join(pending_lines))

        return "\n\n".join(parts) if parts else ""

    def _load_once(self) -> None:
        """Load snapshot from disk once (RAM-first)."""
        if self._loaded:
            return

        if self.snapshot_file.exists():
            try:
                data = json.loads(self.snapshot_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    items = data.get("items", [])
                    if not isinstance(items, list):
                        items = []
                    cleaned_items = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        text = self._clean_text(str(item.get("text", "")), max_len=280)
                        if not text:
                            continue
                        cleaned_items.append(
                            {
                                "id": str(item.get("id", f"ltm_{len(cleaned_items) + 1}")),
                                "text": text,
                                "source": str(item.get("source", "unknown")),
                                "session_key": str(item.get("session_key", "")),
                                "created_at": str(item.get("created_at", timestamp())),
                                "updated_at": str(item.get("updated_at", timestamp())),
                                "hits": int(item.get("hits", 1)),
                            }
                        )
                    self._snapshot = {
                        "version": int(data.get("version", 1)),
                        "updated_at": str(data.get("updated_at", timestamp())),
                        "items": cleaned_items,
                    }
            except Exception:
                self._snapshot = {"version": 1, "updated_at": timestamp(), "items": []}

        self._lessons = self._load_lessons()
        self._loaded = True

    def _flush_to_disk(self) -> None:
        """Persist snapshot and audit buffer to disk."""
        now = timestamp()

        if self._snapshot_dirty:
            data = {
                "version": int(self._snapshot.get("version", 1)),
                "updated_at": now,
                "items": self._snapshot.get("items", []),
            }
            tmp = self.snapshot_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.snapshot_file)
            self._snapshot["updated_at"] = now

        if self._lessons_dirty:
            tmp = self.lessons_file.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                for lesson in self._lessons:
                    f.write(json.dumps(lesson, ensure_ascii=False) + "\n")
            tmp.replace(self.lessons_file)

        if self._audit_buffer:
            with open(self.audit_file, "a", encoding="utf-8") as f:
                for event in self._audit_buffer:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._audit_buffer = []

        if self._lessons_audit_buffer:
            with open(self.lessons_audit_file, "a", encoding="utf-8") as f:
                for event in self._lessons_audit_buffer:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._lessons_audit_buffer = []

        self._dirty_updates = 0
        self._last_flush_monotonic = time.monotonic()
        self._snapshot_dirty = False
        self._lessons_dirty = False

    def _select_snapshot_items(
        self, session_key: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Select long-term items for prompt context."""
        items = self._snapshot.get("items", [])
        if session_key:
            scoped = [
                item
                for item in items
                if not item.get("session_key") or item.get("session_key") == session_key
            ]
        else:
            scoped = list(items)

        scoped.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return scoped[: max(1, limit)]

    def _extract_explicit_memories(self, message: str) -> list[str]:
        """Extract explicit long-term memory intents from user messages."""
        text = message.strip()
        if not text:
            return []

        candidates: list[str] = []
        lower = text.lower()

        cn_match = re.search(r"(?:请)?记住[:：\s]*(.+)$", text)
        if cn_match:
            candidates.append(cn_match.group(1))

        en_match = re.search(r"(?:please\s+)?remember(?:\s+that)?[:\s]+(.+)$", lower)
        if en_match:
            candidates.append(text[en_match.start(1) :])

        if not candidates and any(token in text for token in ("以后都", "以后请", "长期", "默认")):
            candidates.append(text)
        if not candidates and any(token in lower for token in ("from now on", "always", "default")):
            candidates.append(text)

        cleaned = [self._clean_text(c, max_len=280) for c in candidates]
        return [c for c in cleaned if c]

    def _extract_pending_item(self, message: str) -> str | None:
        """Extract pending item hints from user messages."""
        text = message.strip()
        if not text:
            return None

        lower = text.lower()
        markers = ("todo", "to-do", "待办", "请提醒", "remember to", "别忘了")
        if any(marker in lower for marker in markers) or any(marker in text for marker in markers):
            return self._clean_text(text, max_len=180)
        return None

    def _is_pending_resolved(self, message: str) -> bool:
        """Check if user indicates pending items are resolved/canceled."""
        lower = message.lower()
        markers = ("done", "resolved", "cancel", "不用了", "已完成", "完成了", "取消")
        return any(marker in lower for marker in markers) or any(marker in message for marker in markers)

    def _extract_feedback_signal(self, user_message: str) -> tuple[str, str] | None:
        """Extract user correction into (trigger, better_action)."""
        text = user_message.strip()
        if not text:
            return None

        lower = text.lower()
        correction_markers = (
            "不对",
            "不是这个意思",
            "别这样",
            "不要这样",
            "太啰嗦",
            "太长",
            "wrong",
            "incorrect",
            "not what i meant",
            "too verbose",
            "too long",
        )
        if not any(marker in lower for marker in correction_markers) and not any(
            marker in text for marker in correction_markers
        ):
            return None

        if any(token in text for token in ("中文", "英文", "英语")) or any(
            token in lower for token in ("chinese", "english", "language")
        ):
            trigger = "response:language"
        elif any(token in text for token in ("简短", "简洁", "太长", "太啰嗦")) or any(
            token in lower for token in ("concise", "shorter", "too verbose", "too long")
        ):
            trigger = "response:length"
        elif any(token in text for token in ("错误", "不对", "事实")) or any(
            token in lower for token in ("wrong", "incorrect", "factual")
        ):
            trigger = "response:accuracy"
        else:
            trigger = "response:alignment"

        return trigger, self._clean_text(text, max_len=240)

    def _load_lessons(self) -> list[dict[str, Any]]:
        """Load lessons from LESSONS.jsonl."""
        if not self.lessons_file.exists():
            return []

        lessons: list[dict[str, Any]] = []
        try:
            with open(self.lessons_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if not isinstance(data, dict):
                        continue
                    trigger = self._clean_text(str(data.get("trigger", "")), max_len=120)
                    better_action = self._clean_text(str(data.get("better_action", "")), max_len=260)
                    if not trigger or not better_action:
                        continue
                    scope = "session" if data.get("scope") == "session" else "global"
                    session_key = str(data.get("session_key", "")) if scope == "session" else ""
                    key = self._lesson_key(trigger, better_action, scope, session_key)
                    lessons.append(
                        {
                            "id": str(data.get("id", f"lesson_{len(lessons) + 1}")),
                            "key": key,
                            "trigger": trigger,
                            "bad_action": self._clean_text(
                                str(data.get("bad_action", "")), max_len=260
                            ),
                            "better_action": better_action,
                            "scope": scope,
                            "session_key": session_key,
                            "source": str(data.get("source", "unknown")),
                            "confidence": int(data.get("confidence", 1)),
                            "hits": int(data.get("hits", 1)),
                            "enabled": bool(data.get("enabled", True)),
                            "created_at": str(data.get("created_at", timestamp())),
                            "updated_at": str(data.get("updated_at", timestamp())),
                            "last_applied_at": str(data.get("last_applied_at", "")),
                        }
                    )
        except Exception:
            return []
        return lessons

    def _lesson_key(
        self, trigger: str, better_action: str, scope: str, session_key: str | None
    ) -> str:
        """Build a stable dedup key for lessons."""
        normalized_scope = "session" if scope == "session" else "global"
        normalized_session = session_key or "" if normalized_scope == "session" else ""
        return "|".join(
            [
                self._normalize_text(trigger),
                self._normalize_text(better_action),
                normalized_scope,
                normalized_session,
            ]
        )

    def _suggest_tool_better_action(self, tool_name: str, result: str) -> str:
        """Suggest a lightweight fix action for common tool failures."""
        lower = result.lower()
        if "invalid parameters" in lower:
            return f"Validate `{tool_name}` arguments against its schema before calling."
        if "not found" in lower:
            return f"Check path/resource existence before calling `{tool_name}`."
        if "permission" in lower or "outside allowed directory" in lower:
            return f"Check permissions/workspace boundaries before `{tool_name}`."
        if "timeout" in lower:
            return f"Use smaller scope or lighter parameters when calling `{tool_name}`."
        return f"Inspect `{tool_name}` result and adjust arguments before retrying once."

    @staticmethod
    def _is_tool_error(result: str) -> bool:
        """Check whether tool result string indicates an error."""
        return result.strip().lower().startswith("error:")

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Tokenize text into lowercase alnum/CJK terms."""
        tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower())
        return {token for token in tokens if len(token) >= 2}

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text for deduplication."""
        return re.sub(r"\s+", " ", text.strip().lower())

    @staticmethod
    def _clean_text(text: str, max_len: int) -> str:
        """Normalize whitespace and trim to max length."""
        cleaned = re.sub(r"\s+", " ", text.strip())
        if len(cleaned) > max_len:
            return cleaned[: max_len - 3] + "..."
        return cleaned
