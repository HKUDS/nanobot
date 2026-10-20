"""WebUI projection of durable session facts and strict legacy transcript import."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any, cast

from nanobot.bus.events import INBOUND_META_LOCAL_MEDIA
from nanobot.config.paths import get_webui_dir
from nanobot.session.display_history import HistoryFact, HistoryImport, HistoryKind, HistoryReader
from nanobot.session.manager import SessionInfo, SessionManager
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_chat_id, webui_session_key

HISTORY_IMPORT_MARKER = "webui_history_import_v1"
_SEGMENT_NAME = re.compile(r"^\d{6}\.jsonl$")
_EVENTS = {
    "user": HistoryKind.INPUT,
    "message": HistoryKind.ANSWER,
    "stream_end": HistoryKind.ANSWER_SEGMENT,
    "reasoning_end": HistoryKind.REASONING_SEGMENT,
    "file_edit": HistoryKind.FILE_ACTIVITY,
    "turn_end": HistoryKind.COMPLETION,
    "fork_marker": HistoryKind.FORK_BOUNDARY,
    "context_compaction": HistoryKind.COMPACTION,
    "delta": HistoryKind.ANSWER_FRAGMENT,
    "reasoning_delta": HistoryKind.REASONING_FRAGMENT,
}
_MESSAGE_KINDS = {
    "reasoning": HistoryKind.REASONING,
    "progress": HistoryKind.PROGRESS,
    "tool_hint": HistoryKind.TOOL_ACTIVITY,
}
_CONTENT_FIELDS = frozenset({
    "text", "media_paths", "media", "media_urls", "reply_to", "agent_ui", "cli_apps", "mcp_presets", "session_mentions",
    "session_message", INBOUND_META_LOCAL_MEDIA, "tool_events", "edits", "source", "response_sources", "resuming",
    "merge_next", "latency_ms", "usage", "round_usages", "context_window_tokens", "goal_state",
    "outcome", "failure_kind", "failure_error_kind", "failure_attempts", "failure_message",
    "transcript_incomplete", "stream_id", "compaction_id", "phase", "reason",
})


def fact_from_record(record: Mapping[str, Any]) -> HistoryFact:
    """Parse the channel boundary once; core storage never sees event/chat_id keys."""
    event = record.get("event")
    if event is None and record.get("role") in {"user", "assistant"}:
        event = "user" if record["role"] == "user" else "message"
        record = {**record, "text": record.get("text", record.get("content", ""))}
    if event not in _EVENTS:
        raise ValueError(f"unsupported legacy history event: {event!r}")
    kind = _EVENTS[event]
    if event == "message":
        message_kind = record.get("kind")
        if message_kind is not None and message_kind not in _MESSAGE_KINDS:
            raise ValueError(f"unsupported history message kind: {message_kind!r}")
        if isinstance(message_kind, str):
            kind = _MESSAGE_KINDS[message_kind]
    created = record.get("created_at_ms", 0)
    if isinstance(created, bool) or not isinstance(created, int | float) or not 0 <= created < 10**16:
        raise ValueError("invalid history timestamp")
    sequence = record.get("turn_seq")
    if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0):
        raise ValueError("invalid history sequence")
    turn_id, phase = record.get("turn_id"), record.get("turn_phase")
    if turn_id is not None and (not isinstance(turn_id, str) or len(turn_id) > 128):
        raise ValueError("invalid history turn identity")
    if phase is not None and not isinstance(phase, str):
        raise ValueError("invalid history phase")
    fact = HistoryFact(kind, {key: value for key, value in record.items() if key in _CONTENT_FIELDS},
                       turn_id, phase, sequence, int(created))
    return fact


def record_from_fact(fact: HistoryFact, key: str) -> dict[str, Any]:
    if fact.kind in _MESSAGE_KINDS.values():
        event = "message"
        message_kind = next(name for name, kind in _MESSAGE_KINDS.items() if kind is fact.kind)
    else:
        event = next(name for name, kind in _EVENTS.items() if kind is fact.kind)
        message_kind = None
    record = {"event": event, "chat_id": webui_chat_id(key), **fact.content,
              "created_at_ms": fact.created_at_ms}
    if message_kind:
        record["kind"] = message_kind
    if fact.turn_id is not None:
        record["turn_id"] = fact.turn_id
    if fact.phase is not None:
        record["turn_phase"] = fact.phase
    if fact.sequence is not None:
        record["turn_seq"] = fact.sequence
    return record


def turn_records(
    history: HistoryReader, ordinal: int, *, max_records: int | None = None, max_bytes: int | None = None,
) -> list[dict[str, Any]]:
    return [{**record_from_fact(fact, history.key),
             "_webui_replay_identity": f"turn:{ordinal}:record:{position}"}
            for position, fact in history.read_entries(ordinal, max_records=max_records, max_bytes=max_bytes)]


def _read_legacy_file(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"legacy history must be a regular, non-symlink file: {path}")
    before = path.stat()
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value: object = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("record is not an object")
                record = cast(dict[str, Any], value)
                fact_from_record(record).encode()
            except (ValueError, TypeError) as exc:
                raise ValueError(f"cannot import history {path}:{line_number}: {exc}") from exc
            records.append(record)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError(f"legacy history changed during import: {path}")
    return records


def collect_legacy_history(
    sessions: Sequence[SessionInfo], *, directory: Path | None = None,
    namespace: Path | None = None,
) -> list[HistoryImport]:
    """Resolve recorded identities; a lossy filename alone cannot identify an orphan."""
    from nanobot.webui.transcript import compact_legacy_records

    directory = directory if directory is not None else get_webui_dir()
    if directory.is_symlink():
        raise ValueError(f"legacy history directory must not be a symlink: {directory}")
    if not directory.exists():
        return []
    groups: dict[str, list[Path]] = {}
    for path in sorted(directory.iterdir()):
        if path.name.endswith(".segments"):
            if path.is_symlink() or not path.is_dir():
                raise ValueError(f"invalid legacy history segments directory: {path}")
            groups.setdefault(path.name[:-len(".segments")], []).extend(
                item for item in sorted(path.iterdir()) if _SEGMENT_NAME.fullmatch(item.name)
            )
        elif path.suffix == ".jsonl":
            groups.setdefault(path.stem, [])
    for stem, paths in groups.items():
        active = directory / f"{stem}.jsonl"
        if active.exists() or active.is_symlink():
            paths.append(active)
    keys_by_stem: dict[str, set[str]] = {}
    for session in sessions:
        keys_by_stem.setdefault(SessionManager.safe_key(session["key"]), set()).add(session["key"])
    foreign_owners: dict[str, list[Path]] = {}
    if namespace is not None and groups:
        for database in namespace.parent.glob("*/sessions.sqlite3"):
            if database.parent == namespace:
                continue
            if database.is_symlink() or database.parent.is_symlink():
                raise ValueError(f"invalid session namespace for history migration: {database}")
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                owned = {str(row[0]) for row in db.execute("SELECT key FROM sessions")}
                prefix = f"{HISTORY_IMPORT_MARKER}:"
                owned.update(str(row[0])[len(prefix):] for row in db.execute(
                    "SELECT key FROM storage_meta WHERE key LIKE ? AND value='complete'",
                    (prefix + "%",),
                ))
                for key in owned:
                    foreign_owners.setdefault(key, []).append(database)
    imports: list[HistoryImport] = []
    for stem, paths in groups.items():
        records = [record for path in paths for record in _read_legacy_file(path)]
        if not records:
            continue
        recorded_keys: set[str] = set()
        for record in records:
            chat_id = record.get("chat_id")
            if chat_id is not None:
                if not is_valid_webui_chat_id(chat_id):
                    raise ValueError(f"invalid recorded chat identity in legacy history: {stem}")
                recorded_keys.add(webui_session_key(chat_id))
        candidates = recorded_keys or keys_by_stem.get(stem, set())
        if len(candidates) != 1:
            raise ValueError(f"ambiguous legacy history identity: {stem}; expected one recorded chat or canonical session")
        key = next(iter(candidates))
        if SessionManager.safe_key(key) != stem:
            raise ValueError(f"legacy history filename conflicts with its recorded identity: {stem}")
        if key in foreign_owners:
            if key not in keys_by_stem.get(stem, set()) and len(foreign_owners[key]) == 1:
                # This instance-wide backup belongs to another workspace. Its
                # owner will import it when that namespace starts.
                continue
            raise ValueError(
                f"cannot select a SQLite owner for legacy history {key}: also present in "
                f"{foreign_owners[key]}; resolve the duplicate explicitly before restarting"
            )
        facts = [fact_from_record(record) for record in compact_legacy_records(records)]
        times = [fact.created_at_ms for fact in facts if fact.created_at_ms]
        file_times = [int(path.stat().st_mtime * 1000) for path in paths]
        imports.append(HistoryImport(key, facts, min(times or file_times), max(times or file_times)))
    return imports


async def initialize_history(sessions: SessionManager) -> None:
    """Finish the once-only import before recovery or transport admission."""
    await sessions.state.migrate_history(
        HISTORY_IMPORT_MARKER,
        lambda rows: collect_legacy_history(rows, namespace=sessions.sessions_dir),
    )
