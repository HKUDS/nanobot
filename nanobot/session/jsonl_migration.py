"""One-time JSONL import, introduced in 0.3.6 and removed in 0.5.0.

0.4.x is the final migration release line. Older installations must pass through
that line before upgrading to 0.5.0. The importer never changes its source files.
"""

from __future__ import annotations

import json
import stat
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from nanobot.providers.base import ProviderConversationState
from nanobot.session.location import SessionLocation
from nanobot.session.manager import Session

if TYPE_CHECKING:
    from nanobot.session.sqlite_store import SqliteSessionStore

INTRODUCED_VERSION = "0.3.6"
LAST_SUPPORTED_RELEASE_LINE = "0.4.x"
SUNSET_VERSION = "0.5.0"


def _record(line: str) -> dict[str, Any]:
    value: object = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("JSONL records must be objects")
    return cast(dict[str, Any], value)


def read_jsonl(path: Path) -> Session:
    """Read a complete legacy session, failing without modifying malformed input."""
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"JSONL migration requires a regular file: {path}")
    header: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = []
    provider: ProviderConversationState | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = _record(line)
        if item.get("_type") == "metadata":
            if header is not None:
                raise ValueError(f"multiple session headers: {path}")
            header = item
        elif item.get("_type") == "provider_state":
            provider = ProviderConversationState.from_private_record(item.get("state"))
            if provider is None:
                raise ValueError(f"invalid private provider state: {path}")
        else:
            if not isinstance(item.get("role"), str):
                raise ValueError(f"invalid session message: {path}")
            messages.append(item)
    if header is None:
        raise ValueError(f"missing session header: {path}")
    key = header.get("key") or SessionLocation.session_key_from_path(path)
    if not isinstance(key, str) or not key:
        raise ValueError(f"cannot determine session key: {path}")
    metadata: object = header.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError(f"invalid session metadata: {path}")
    fallback = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    session = Session(
        key=key, messages=messages, metadata=cast(dict[str, Any], metadata),
        created_at=datetime.fromisoformat(header.get("created_at") or fallback),
        updated_at=datetime.fromisoformat(header.get("updated_at") or fallback),
        last_consolidated=header.get("last_archived", header.get("last_consolidated", 0)),
        provider_state=provider,
    )
    checkpoint_path = path.with_suffix(".checkpoint.json")
    if checkpoint_path.exists():
        if checkpoint_path.is_symlink():
            raise ValueError(f"checkpoint must not be a symlink: {checkpoint_path}")
        checkpoint = _record(checkpoint_path.read_text(encoding="utf-8"))
        if (
            checkpoint_path.stat().st_mtime_ns >= path.stat().st_mtime_ns
            and checkpoint.get("version") == 1
            and checkpoint.get("session_key") == key
            and checkpoint.get("base_updated_at") == session.updated_at.isoformat()
            and checkpoint.get("base_message_count") == len(messages)
        ):
            if not isinstance(checkpoint.get("checkpoint"), dict):
                raise ValueError(f"invalid checkpoint: {checkpoint_path}")
            session.metadata["runtime_checkpoint"] = checkpoint["checkpoint"]
            raw_provider = checkpoint.get("provider_state")
            session.provider_state = ProviderConversationState.from_private_record(raw_provider)
            if raw_provider is not None and session.provider_state is None:
                raise ValueError(f"invalid checkpoint provider state: {checkpoint_path}")
    return session


def migrate_jsonl(store: SqliteSessionStore, workspace: Path) -> int:
    """Import atomically, then let the caller commit the durable completion marker.

    Duplicate sources must agree. A malformed or conflicting source aborts the
    whole import so a retry cannot silently omit a conversation.
    """
    imported: dict[str, tuple[Session, Path]] = {}
    for directory in (store.path.parent, workspace / "sessions"):
        if directory.is_symlink():
            raise ValueError(f"migration source must not be a symlink: {directory}")
        for path in sorted(directory.glob("*.jsonl")):
            try:
                session = read_jsonl(path)
                prior = imported.get(session.key)
                if prior is not None:
                    old, old_path = prior
                    if (old.messages, old.metadata, old.last_archived, old.provider_state) != (
                        session.messages, session.metadata, session.last_archived, session.provider_state,
                    ):
                        raise ValueError(f"conflicting JSONL sources: {old_path} and {path}")
                    continue
                if store.load(session.key) is not None:
                    raise ValueError(f"session already exists in SQLite: {session.key}")
                store.save(session)
                imported[session.key] = (session, path)
            except Exception as exc:
                raise RuntimeError(
                    f"JSONL migration failed for {path}; source files are unchanged. "
                    "Resolve the invalid or conflicting file and restart."
                ) from exc
    if imported:
        logger.info("Imported {} JSONL sessions into {}", len(imported), store.path)
    return len(imported)
