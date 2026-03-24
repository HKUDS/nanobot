"""Memory snapshot: rebuild MEMORY.md and verify memory integrity.

Extracted from ``MemoryStore`` (Task 6) to isolate snapshot-related
operations from the main store orchestration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from ..helpers import _to_datetime, _to_str_list, _utc_now_iso
from .profile_io import ProfileStore as ProfileManager

if TYPE_CHECKING:
    from .unified_db import UnifiedMemoryDB

# Constants previously on MemoryStore — shared with snapshot logic.
PROFILE_KEYS = (
    "preferences",
    "stable_facts",
    "active_projects",
    "relationships",
    "constraints",
)
PROFILE_STATUS_STALE = "stale"
CONFLICT_STATUS_OPEN = "open"
CONFLICT_STATUS_NEEDS_USER = "needs_user"


class MemorySnapshot:
    """Rebuild MEMORY.md snapshots and verify memory integrity.

    Constructor takes collaborators that are already initialised in
    ``MemoryStore.__init__``.
    """

    _PINNED_START = "<!-- user-pinned -->"
    _PINNED_END = "<!-- end-user-pinned -->"

    def __init__(
        self,
        *,
        profile_mgr: ProfileManager,
        read_events_fn: Callable[..., list[dict[str, Any]]],
        profile_section_lines_fn: Callable[..., list[str]],
        recent_unresolved_fn: Callable[..., list[dict[str, Any]]],
        read_long_term_fn: Callable[[], str] | None = None,
        write_long_term_fn: Callable[[str], None] | None = None,
        verify_beliefs_fn: Callable[[], dict[str, Any]],
        write_profile_fn: Callable[[dict[str, Any]], None],
        profile_keys: tuple[str, ...] = PROFILE_KEYS,
        db: UnifiedMemoryDB | None = None,
    ) -> None:
        self.profile_mgr = profile_mgr
        self._read_events = read_events_fn
        self._profile_section_lines = profile_section_lines_fn
        self._recent_unresolved = recent_unresolved_fn
        self._read_long_term = read_long_term_fn
        self._write_long_term = write_long_term_fn
        self._verify_beliefs = verify_beliefs_fn
        self._write_profile = write_profile_fn
        self._profile_keys = profile_keys
        self._db = db

    @classmethod
    def _extract_pinned_section(cls, text: str) -> str | None:
        """Extract user-pinned content from MEMORY.md, if present."""
        start = text.find(cls._PINNED_START)
        end = text.find(cls._PINNED_END)
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + len(cls._PINNED_END)]

    @classmethod
    def _restore_pinned_section(cls, new_text: str, pinned: str) -> str:
        """Re-insert a pinned section into new MEMORY.md content.

        If the new text already contains a pinned fence, replace it.
        Otherwise insert the pinned block after the first heading.
        """
        existing = cls._extract_pinned_section(new_text)
        if existing:
            return new_text.replace(existing, pinned)
        # Insert after the first heading line (or at the top).
        lines = new_text.split("\n")
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("#"):
                insert_at = i + 1
                break
        lines.insert(insert_at, pinned)
        return "\n".join(lines)

    def rebuild_memory_snapshot(self, *, max_events: int = 30, write: bool = True) -> str:
        """Rebuild MEMORY.md from profile + events."""
        profile = self.profile_mgr.read_profile()
        if self._db is not None:
            events = self._db.read_events(limit=max_events)
        else:
            events = self._read_events(limit=max_events) or []

        # Preserve user-pinned sections across rebuilds (LAN-199 / LAN-206).
        if self._db is not None:
            existing_memory = self._db.read_snapshot("current")
        else:
            existing_memory = self._read_long_term() if self._read_long_term is not None else ""
        pinned = self._extract_pinned_section(existing_memory) if existing_memory else None

        parts: list[str] = ["# Memory", ""]
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

        if pinned:
            snapshot = self._restore_pinned_section(snapshot, pinned)

        if write:
            if self._db is not None:
                self._db.write_snapshot("current", snapshot)
            elif self._write_long_term is not None:
                self._write_long_term(snapshot)
        return snapshot

    def verify_memory(
        self, *, stale_days: int = 90, update_profile: bool = False
    ) -> dict[str, Any]:
        """Produce a verification report on memory health."""
        profile = self.profile_mgr.read_profile()
        if self._db is not None:
            events = self._db.read_events(limit=1000)
        else:
            events = self._read_events() if self._read_events is not None else []
        now = datetime.now(timezone.utc)
        stale = 0
        total_ttl = 0
        for event in events:
            ttl_days = event.get("ttl_days")
            timestamp = _to_datetime(str(event.get("timestamp", "")))
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
        for key in self._profile_keys:
            section_meta = self.profile_mgr._meta_section(profile, key)
            for _, entry in section_meta.items():
                if not isinstance(entry, dict):
                    continue
                last_seen = _to_datetime(str(entry.get("last_seen_at", "")))
                if not last_seen:
                    continue
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                age_days = max((now - last_seen).total_seconds() / 86400.0, 0.0)
                if age_days > stale_days:
                    stale_profile_items += 1
                    if update_profile and entry.get("status") != PROFILE_STATUS_STALE:
                        entry["status"] = PROFILE_STATUS_STALE
                        profile_touched = True

        if update_profile:
            profile["last_verified_at"] = _utc_now_iso()
            profile_touched = True
            if profile_touched:
                self._write_profile(profile)

        open_conflicts = [
            c
            for c in profile.get("conflicts", [])
            if isinstance(c, dict)
            and str(c.get("status", CONFLICT_STATUS_OPEN)).strip().lower()
            in {CONFLICT_STATUS_OPEN, CONFLICT_STATUS_NEEDS_USER}
        ]
        belief_quality = self._verify_beliefs()

        return {
            "events": len(events),
            "profile_items": sum(len(_to_str_list(profile.get(k))) for k in self._profile_keys),
            "open_conflicts": len(open_conflicts),
            "stale_events": stale,
            "stale_profile_items": stale_profile_items,
            "ttl_tracked_events": total_ttl,
            "last_verified_at": profile.get("last_verified_at"),
            "belief_quality": belief_quality["summary"],
        }
