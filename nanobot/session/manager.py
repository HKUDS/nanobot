"""Session management for conversation history."""

import base64
import json
import re
import sqlite3
from collections import OrderedDict
from collections.abc import Generator
from contextlib import contextmanager, suppress
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable, Protocol, TypedDict, cast
from weakref import WeakValueDictionary

from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir
from nanobot.providers.base import ProviderConversationState
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    public_history_message,
)
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.model_selection import model_preset_from_metadata
from nanobot.utils.helpers import (
    content_with_media_breadcrumbs,
    ensure_dir,
    estimate_message_tokens,
    find_legal_message_start,
    recent_message_start_index,
    safe_filename,
    strip_think,
)
from nanobot.utils.subagent_channel_display import scrub_subagent_announce_body

FILE_MAX_MESSAGES = 2000
SESSION_CACHE_MAX_SIZE = 128
MIN_REPLAY_MAX_MESSAGES = 120
REPLAY_TOKENS_PER_MESSAGE = 100
_MESSAGE_TIME_PREFIX_RE = re.compile(r"^\[Message Time: [^\]]+\]\n?")
_LOCAL_IMAGE_BREADCRUMB_RE = re.compile(r"^\[image: (?:/|~)[^\]]+\]\s*$")
_TOOL_CALL_ECHO_RE = re.compile(r'^\s*(?:generate_image|message)\([^)]*\)\s*$')
_SESSION_PREVIEW_MAX_CHARS = 120
_SESSION_LIST_PREVIEW_MAX_RECORDS = 200
_SESSION_LIST_PREVIEW_MAX_CHARS = 1_000_000
_SESSION_DATA_ERRORS = (ValueError, TypeError, AttributeError, KeyError)
_PROVIDER_STATE_RECORD_TYPE = "provider_state"
_SQLITE_DB_NAME = "sessions.db"
_SQLITE_SCHEMA_VERSION = 1
_SQLITE_BUSY_TIMEOUT_SECONDS = 5.0
_SQLITE_STARTUP_BUSY_TIMEOUT_SECONDS = 60.0
# TODO(0.3.2): Remove JSONL migration; v0.3.1 is the upgrade window.
_SQLITE_JSONL_MIGRATION_KEY = "jsonl_import_v1"
_SQLITE_JSONL_MANIFEST_VERSION = 1
_FORK_VOLATILE_METADATA_KEYS = {
    "goal_state",
    "pending_user_turn",
    "runtime_checkpoint",
    "thread_goal",
    "title",
    "title_user_edited",
}


def _json_object(value: object) -> dict[str, Any]:
    """Narrow a decoded JSON object while preserving its original values."""
    if not isinstance(value, dict):
        raise ValueError("session records must be JSON objects")
    return cast(dict[str, Any], value)


def replay_max_messages_for_context(context_window_tokens: int | None) -> int:
    if not context_window_tokens or context_window_tokens <= 0:
        return FILE_MAX_MESSAGES
    return min(
        FILE_MAX_MESSAGES,
        max(MIN_REPLAY_MAX_MESSAGES, context_window_tokens // REPLAY_TOKENS_PER_MESSAGE),
    )


def _sanitize_assistant_replay_text(content: str) -> str:
    """Remove internal replay artifacts that the model may have copied before.

    These strings are useful as runtime/session metadata, but when they appear
    in assistant examples they become demonstrations for the model to repeat.
    """
    content = _MESSAGE_TIME_PREFIX_RE.sub("", content, count=1)
    lines = [
        line
        for line in content.splitlines()
        if not _LOCAL_IMAGE_BREADCRUMB_RE.match(line)
        and not _TOOL_CALL_ECHO_RE.match(line)
    ]
    return "\n".join(lines).strip()


def _text_preview(content: object) -> str:
    """Return compact display text for session lists."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in cast(list[object], content):
            if isinstance(block, dict):
                block_data = cast(dict[object, object], block)
                if block_data.get("type") != "text":
                    continue
                value = block_data.get("text")
                if isinstance(value, str):
                    parts.append(value)
        text = " ".join(parts)
    else:
        return ""
    text = _sanitize_assistant_replay_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _SESSION_PREVIEW_MAX_CHARS:
        text = text[: _SESSION_PREVIEW_MAX_CHARS - 1].rstrip() + "…"
    return text


def _message_preview_text(message: dict[str, Any]) -> str:
    """Session list preview text; subagent inject blobs are shortened for display."""
    message = public_history_message(message)
    content = cast(object, message.get("content"))
    if message.get("injected_event") == "subagent_result" and isinstance(content, str):
        content = scrub_subagent_announce_body(content)
    return _text_preview(content)


def _metadata_title(metadata: object) -> str:
    if not isinstance(metadata, dict):
        return ""
    metadata_data = cast(dict[object, object], metadata)
    title = metadata_data.get("title")
    if not isinstance(title, str):
        return ""
    if metadata_data.get("title_user_edited") is True:
        return title
    return strip_think(title)


@dataclass
class RetentionResult:
    dropped: list[dict[str, Any]]
    already_consolidated_count: int


@dataclass
class Session:
    """A conversation session."""

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files
    provider_state: ProviderConversationState | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.metadata), dict):
            self.metadata = {}
        if not isinstance(cast(object, self.provider_state), ProviderConversationState):
            self.provider_state = None
        # An out-of-range offset (corrupt metadata) would hide all history; reset it.
        last_consolidated = cast(object, self.last_consolidated)
        if (
            isinstance(last_consolidated, bool)
            or not isinstance(last_consolidated, int)
            or not 0 <= last_consolidated <= len(self.messages)
        ):
            self.last_consolidated = 0

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(
        self,
        max_messages: int = FILE_MAX_MESSAGES,
        *,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        include_runtime_context: bool = True,
    ) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input.

        History is sliced by message count first (``max_messages``), then by
        token budget from the tail (``max_tokens``) when provided.
        """
        unconsolidated = self.messages[self.last_consolidated:]
        max_messages = max_messages if max_messages > 0 else FILE_MAX_MESSAGES
        start_idx = recent_message_start_index(
            unconsolidated,
            max_messages,
            extend_to_user=extend_to_user,
        )
        sliced = unconsolidated[start_idx:]

        # Avoid starting mid-turn when possible, except for proactive
        # assistant deliveries that the user may be replying to.
        for i, message in enumerate(sliced):
            if message.get("role") == "user":
                start = i
                if i > 0 and sliced[i - 1].get("_channel_delivery"):
                    start = i - 1
                sliced = sliced[start:]
                break

        # Drop orphan tool results at the front.
        start = find_legal_message_start(sliced)
        if start:
            sliced = sliced[start:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            if message.get("_command"):
                continue
            has_persisted_runtime_context = isinstance(
                message.get(RUNTIME_CONTEXT_HISTORY_META),
                dict,
            )
            if not include_runtime_context:
                message = public_history_message(message)
            content = message.get("content", "")
            role = message.get("role")
            if role == "assistant" and isinstance(content, str):
                content = _sanitize_assistant_replay_text(content)
            # Synthesize an ``[image: path]`` breadcrumb from the persisted
            # ``media`` kwarg so LLM replay still sees *something* where the
            # image used to be. Without this, an image-only user turn
            # replays as an empty user message — the assistant's reply then
            # looks like it's responding to nothing.
            content = content_with_media_breadcrumbs(
                role,
                content,
                message.get("media"),
            )
            cli_apps = cast(object, message.get("cli_apps"))
            if (
                include_runtime_context
                and not has_persisted_runtime_context
                and role == "user"
                and isinstance(cli_apps, list)
                and cli_apps
                and isinstance(content, str)
            ):
                cli_lines: list[str] = []
                for item in cast(list[object], cli_apps[:8]):
                    if not isinstance(item, dict):
                        continue
                    item_data = cast(dict[object, object], item)
                    name = str(item_data.get("name") or "").strip().lower()
                    if not name:
                        continue
                    entry_point = (
                        str(item_data.get("entry_point") or "unknown").strip() or "unknown"
                    )
                    cli_lines.append(
                        f"[CLI App Attachment: @{name}; tool=run_cli_app; entry_point={entry_point}; "
                        f"skill=skills/cli-app-{name}/SKILL.md]"
                    )
                if cli_lines:
                    breadcrumbs = "\n".join(cli_lines)
                    content = f"{content}\n{breadcrumbs}" if content else breadcrumbs
            if role == "assistant" and isinstance(content, str) and not content.strip():
                if not any(key in message for key in ("tool_calls", "reasoning_content", "thinking_blocks")):
                    continue
            entry: dict[str, Any] = {"role": message["role"], "content": content}
            for key in ("tool_calls", "tool_call_id", "name", "reasoning_content", "thinking_blocks"):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)

        if max_tokens > 0 and out:
            kept: list[dict[str, Any]] = []
            used = 0
            for message in reversed(out):
                tokens = estimate_message_tokens(message)
                if kept and used + tokens > max_tokens:
                    break
                kept.append(message)
                used += tokens
            kept.reverse()

            # Keep history aligned to the first visible user turn.
            first_user = next((i for i, m in enumerate(kept) if m.get("role") == "user"), None)
            if first_user is not None:
                kept = kept[first_user:]
            else:
                # Tight token budgets can otherwise leave assistant-only tails.
                # If a user turn exists in the unsliced output, recover the
                # nearest one even if it slightly exceeds the token budget.
                recovered_user = next(
                    (i for i in range(len(out) - 1, -1, -1) if out[i].get("role") == "user"),
                    None,
                )
                if recovered_user is not None:
                    kept = out[recovered_user:]

            # And keep a legal tool-call boundary at the front.
            start = find_legal_message_start(kept)
            if start:
                kept = kept[start:]
            out = kept
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.provider_state = None
        self.updated_at = datetime.now()
        self.metadata.pop("_last_summary", None)

    def retain_recent_legal_suffix(
        self,
        max_messages: int,
        *,
        extend_to_user: bool = False,
    ) -> RetentionResult:
        """Keep a legal recent suffix, optionally extending it back to a user turn.

        Returns a RetentionResult with dropped messages and how many of those
        were in the already-consolidated prefix. This method mutates
        self.messages and self.last_consolidated in place.
        """
        if max_messages <= 0:
            dropped = list(self.messages)
            lc = self.last_consolidated
            self.clear()
            return RetentionResult(
                dropped=dropped,
                already_consolidated_count=min(lc, len(dropped)),
            )
        if len(self.messages) <= max_messages:
            return RetentionResult(
                dropped=[],
                already_consolidated_count=0,
            )

        original = list(self.messages)
        before_lc = self.last_consolidated

        start_idx = max(0, len(self.messages) - max_messages)
        if extend_to_user:
            start_idx = next(
                (i for i in range(start_idx, -1, -1) if self.messages[i].get("role") == "user"),
                start_idx,
            )

        retained = self.messages[start_idx:]

        # Prefer starting at a user turn when one exists within the retained window.
        first_user = next((i for i, m in enumerate(retained) if m.get("role") == "user"), None)
        if first_user is not None:
            retained = retained[first_user:]
        elif not extend_to_user:
            # If the hard-capped tail is assistant/tool-only, anchor to the
            # latest user in the full session and take a capped forward window.
            latest_user = next(
                (i for i in range(len(self.messages) - 1, -1, -1)
                 if self.messages[i].get("role") == "user"),
                None,
            )
            if latest_user is not None:
                retained = self.messages[latest_user: latest_user + max_messages]

        # Mirror get_history(): avoid persisting orphan tool results at the front.
        start = find_legal_message_start(retained)
        if start:
            retained = retained[start:]

        # Hard-cap guarantee unless the caller requested user-turn extension.
        if not extend_to_user and len(retained) > max_messages:
            retained = retained[-max_messages:]
            start = find_legal_message_start(retained)
            if start:
                retained = retained[start:]

        # Compute actually-dropped messages using identity comparison so that
        # even when retained is a non-contiguous slice of original (the else
        # branch above), we never duplicate or lose messages.
        retained_ids = set(id(m) for m in retained)
        dropped = [m for m in original if id(m) not in retained_ids]

        # Count how many dropped messages were in the already-consolidated
        # prefix of the original list.  This cannot be a simple min() because
        # dropped may include messages from *after* the consolidated prefix
        # (e.g. in the else branch).
        already_consolidated = sum(
            1 for i, m in enumerate(original)
            if i < before_lc and id(m) not in retained_ids
        )

        # New last_consolidated = count of retained messages that were inside
        # the old consolidated prefix.
        new_lc = sum(
            1 for i, m in enumerate(original)
            if i < before_lc and id(m) in retained_ids
        )

        self.messages = retained
        self.last_consolidated = new_lc
        if dropped:
            self.provider_state = None
        self.updated_at = datetime.now()
        return RetentionResult(
            dropped=dropped,
            already_consolidated_count=already_consolidated,
        )

    def enforce_file_cap(
        self,
        on_archive: Callable[[list[dict[str, Any]]], None] | None = None,
        limit: int = FILE_MAX_MESSAGES,
    ) -> None:
        """Bound session message growth by archiving and trimming old prefixes."""
        if limit <= 0 or len(self.messages) <= limit:
            return

        result = self.retain_recent_legal_suffix(limit)
        if not result.dropped:
            return

        archive_chunk = result.dropped[result.already_consolidated_count:]
        if archive_chunk and on_archive:
            on_archive(archive_chunk)
        logger.info(
            "Session file cap hit for {}: dropped {}, raw-archived {}, kept {}",
            self.key,
            len(result.dropped),
            len(archive_chunk),
            len(self.messages),
        )


class SessionPayload(TypedDict):
    key: str
    created_at: str | None
    updated_at: str | None
    metadata: dict[str, Any]
    messages: list[dict[str, Any]]


class SessionMetadataPayload(TypedDict):
    key: str
    created_at: str | None
    updated_at: str | None
    metadata: dict[str, Any]


class SessionInfo(TypedDict):
    key: str
    created_at: str
    updated_at: str
    title: str
    preview: str
    model_preset: str | None
    path: str


@dataclass(frozen=True)
class _JsonlFileSignature:
    sha256: str


@dataclass(frozen=True)
class _PreparedSession:
    key: str
    created_at: str
    updated_at: str
    metadata_json: str
    private_metadata_json: str
    last_consolidated: int
    message_rows: tuple[tuple[str, int, str], ...]


class SessionStore(Protocol):
    def load(self, key: str) -> Session | None: ...

    def save(self, session: Session, *, fsync: bool = False) -> None: ...

    def delete(self, key: str) -> bool: ...

    def read(self, key: str) -> SessionPayload | None: ...

    def read_metadata(self, key: str) -> SessionMetadataPayload | None: ...

    def list_sessions(self) -> list[SessionInfo]: ...


class JsonlSessionFiles:
    """Read and clean up JSONL files during SQLite migration."""

    def __init__(self, workspace: Path):
        self.sessions_dir = ensure_dir(workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()

    @staticmethod
    def safe_key(key: str) -> str:
        return safe_filename(key.replace(":", "_"))

    @staticmethod
    def storage_key(key: str) -> str:
        return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")

    @staticmethod
    def decode_storage_key(stem: str) -> str | None:
        try:
            padding = 4 - len(stem) % 4
            if padding != 4:
                stem += "=" * padding
            return base64.urlsafe_b64decode(stem).decode("utf-8")
        except _SESSION_DATA_ERRORS:
            return None

    @classmethod
    def session_key_from_path(cls, path: Path) -> str | None:
        key = cls.decode_storage_key(path.stem)
        if key is None or cls.storage_key(key) != path.stem:
            return None
        return key

    def get_session_path(self, key: str) -> Path:
        return self.sessions_dir / f"{self.storage_key(key)}.jsonl"

    def get_legacy_lossy_path(self, key: str) -> Path:
        return self.sessions_dir / f"{self.safe_key(key)}.jsonl"

    def get_legacy_session_path(self, key: str) -> Path:
        return self.legacy_sessions_dir / f"{self.safe_key(key)}.jsonl"

    def session_files(self) -> list[tuple[str, Path]]:
        files: list[tuple[str, Path]] = []
        for path in sorted(self.sessions_dir.glob("*.jsonl")):
            key = self.session_key_from_path(path)
            if key is not None:
                files.append((key, path))
        return files

    @staticmethod
    def _metadata_record_key(path: Path) -> str | None:
        try:
            with open(path, encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue
                    raw_data: object = json.loads(line)
                    if not isinstance(raw_data, dict):
                        continue
                    data = cast(dict[object, object], raw_data)
                    if data.get("_type") != "metadata":
                        continue
                    key = data.get("key")
                    return key if isinstance(key, str) else None
        except (OSError, *_SESSION_DATA_ERRORS):
            return None
        return None

    def load_for_migration(self, key: str) -> Session | None:
        path = self.get_session_path(key)
        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: datetime | None = None
            updated_at: datetime | None = None
            last_consolidated = 0
            provider_state: ProviderConversationState | None = None

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    raw_data: object = json.loads(line)
                    data = _json_object(raw_data)

                    record_type = data.get("_type")
                    if record_type == "metadata":
                        if data.get("key") != key:
                            raise ValueError(
                                "session metadata key does not match its canonical filename"
                            )
                        metadata_value = cast(object, data.get("metadata", {}))
                        metadata = (
                            cast(dict[str, Any], metadata_value)
                            if isinstance(metadata_value, dict)
                            else {}
                        )
                        created_at_value = cast(object, data.get("created_at"))
                        updated_at_value = cast(object, data.get("updated_at"))
                        created_at = (
                            datetime.fromisoformat(created_at_value)
                            if isinstance(created_at_value, str) and created_at_value
                            else None
                        )
                        updated_at = (
                            datetime.fromisoformat(updated_at_value)
                            if isinstance(updated_at_value, str) and updated_at_value
                            else None
                        )
                        offset = cast(object, data.get("last_consolidated", 0))
                        last_consolidated = (
                            offset
                            if isinstance(offset, int) and not isinstance(offset, bool)
                            else 0
                        )
                    elif record_type == _PROVIDER_STATE_RECORD_TYPE:
                        provider_state = ProviderConversationState.from_private_record(
                            data.get("state")
                        )
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
                provider_state=provider_state,
            )
        except _SESSION_DATA_ERRORS as e:
            logger.warning("Failed to load session {}: {}", key, e)
            repaired = self._repair(key)
            if repaired is not None:
                logger.info(
                    "Recovered session {} from corrupt file ({} messages)",
                    key,
                    len(repaired.messages),
                )
            return repaired

    def _repair(self, key: str) -> Session | None:
        path = self.get_session_path(key)
        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: datetime | None = None
            updated_at: datetime | None = None
            last_consolidated = 0
            provider_state: ProviderConversationState | None = None
            skipped = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw_data: object = json.loads(line)
                    except json.JSONDecodeError:
                        skipped += 1
                        continue
                    if not isinstance(raw_data, dict):
                        skipped += 1
                        continue
                    data = cast(dict[str, Any], raw_data)

                    record_type = data.get("_type")
                    if record_type == "metadata":
                        if data.get("key") != key:
                            logger.warning(
                                "Session metadata key does not match canonical key {}",
                                key,
                            )
                            return None
                        metadata_value = cast(object, data.get("metadata", {}))
                        metadata = (
                            cast(dict[str, Any], metadata_value)
                            if isinstance(metadata_value, dict)
                            else {}
                        )
                        created_at_value = cast(object, data.get("created_at"))
                        if isinstance(created_at_value, str) and created_at_value:
                            with suppress(ValueError):
                                created_at = datetime.fromisoformat(created_at_value)
                        updated_at_value = cast(object, data.get("updated_at"))
                        if isinstance(updated_at_value, str) and updated_at_value:
                            with suppress(ValueError):
                                updated_at = datetime.fromisoformat(updated_at_value)
                        offset = cast(object, data.get("last_consolidated", 0))
                        last_consolidated = (
                            offset
                            if isinstance(offset, int) and not isinstance(offset, bool)
                            else 0
                        )
                    elif record_type == _PROVIDER_STATE_RECORD_TYPE:
                        candidate = ProviderConversationState.from_private_record(
                            data.get("state")
                        )
                        if candidate is None:
                            skipped += 1
                        else:
                            provider_state = candidate
                    else:
                        messages.append(data)

            if skipped:
                logger.warning("Skipped {} corrupt lines in session {}", skipped, key)

            if not messages and not metadata and provider_state is None:
                return None

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
                provider_state=provider_state,
            )
        except _SESSION_DATA_ERRORS as e:
            logger.warning("Repair failed for session {}: {}", key, e)
            return None

    def delete_backups(self, key: str) -> bool:
        canonical_path = self.get_session_path(key)
        lossy_path = self.get_legacy_lossy_path(key)
        paths = [canonical_path]
        if lossy_path != canonical_path and lossy_path.exists():
            canonical_owner = self.session_key_from_path(lossy_path)
            if canonical_owner is None or canonical_owner == key:
                paths.append(lossy_path)
            else:
                metadata_owner = self._metadata_record_key(lossy_path)
                if metadata_owner != canonical_owner:
                    raise RuntimeError(
                        f"Refusing to delete ambiguous legacy session file {lossy_path}"
                    )
        paths.append(self.get_legacy_session_path(key))
        deleted = False
        for path in paths:
            if not path.exists():
                continue
            try:
                path.unlink()
                deleted = True
            except OSError as e:
                logger.warning("Failed to delete session file {}: {}", path, e)
                raise
        return deleted


class SQLiteSessionStore:
    """SQLite implementation of session persistence."""

    def __init__(self, workspace: Path):
        self.db_path = ensure_dir(workspace) / _SQLITE_DB_NAME
        self._initialize()

    @contextmanager
    def _connection(
        self,
        *,
        durable: bool = False,
        timeout: float = _SQLITE_BUSY_TIMEOUT_SECONDS,
    ) -> Generator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=timeout)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
            connection.execute(
                "PRAGMA synchronous = FULL" if durable else "PRAGMA synchronous = NORMAL"
            )
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection(
            durable=True,
            timeout=_SQLITE_STARTUP_BUSY_TIMEOUT_SECONDS,
        ) as connection:
            deadline = monotonic() + _SQLITE_STARTUP_BUSY_TIMEOUT_SECONDS
            while True:
                try:
                    journal_mode: object = connection.execute(
                        "PRAGMA journal_mode = WAL"
                    ).fetchone()
                    if journal_mode != ("wal",):
                        raise RuntimeError(f"Failed to enable SQLite WAL mode: {journal_mode!r}")
                    break
                except sqlite3.OperationalError as exc:
                    error_code = exc.sqlite_errorcode & 0xFF
                    if (
                        error_code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                        or monotonic() >= deadline
                    ):
                        raise
                    sleep(0.05)
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                raw_version: object = connection.execute("PRAGMA user_version").fetchone()
                if not isinstance(raw_version, tuple):
                    raise RuntimeError("Failed to read SQLite session schema version")
                version_row = cast(tuple[object, ...], raw_version)
                if len(version_row) != 1 or not isinstance(version_row[0], int):
                    raise RuntimeError("Failed to read SQLite session schema version")
                version = version_row[0]
                if version not in (0, _SQLITE_SCHEMA_VERSION):
                    raise RuntimeError(
                        f"Unsupported SQLite session schema version {version}; "
                        f"expected {_SQLITE_SCHEMA_VERSION}"
                    )
                if version == 0:
                    connection.execute(
                        """
                        CREATE TABLE sessions (
                            key TEXT PRIMARY KEY,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            metadata TEXT NOT NULL,
                            private_metadata TEXT NOT NULL DEFAULT '{}',
                            last_consolidated INTEGER NOT NULL DEFAULT 0
                                CHECK (last_consolidated >= 0)
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE TABLE messages (
                            session_key TEXT NOT NULL,
                            position INTEGER NOT NULL CHECK (position >= 0),
                            payload TEXT NOT NULL,
                            PRIMARY KEY (session_key, position),
                            FOREIGN KEY (session_key) REFERENCES sessions(key) ON DELETE CASCADE
                        )
                        """
                    )
                    connection.execute(
                        "CREATE INDEX sessions_updated_at ON sessions(updated_at DESC)"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS store_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                if version != _SQLITE_SCHEMA_VERSION:
                    connection.execute(f"PRAGMA user_version = {_SQLITE_SCHEMA_VERSION}")

    @staticmethod
    def _file_signature(path: Path) -> _JsonlFileSignature:
        try:
            digest = sha256()
            with open(path, "rb") as file:
                while chunk := file.read(1024 * 1024):
                    digest.update(chunk)
        except OSError as exc:
            raise RuntimeError(f"Failed to inspect JSONL session backup {path}") from exc
        return _JsonlFileSignature(sha256=digest.hexdigest())

    @classmethod
    def _current_jsonl_signatures(
        cls,
        source: JsonlSessionFiles,
    ) -> dict[str, _JsonlFileSignature]:
        return {
            key: cls._file_signature(path)
            for key, path in source.session_files()
        }

    @staticmethod
    def _read_migration_marker(connection: sqlite3.Connection) -> str | None:
        row: object = connection.execute(
            "SELECT value FROM store_metadata WHERE key = ?",
            (_SQLITE_JSONL_MIGRATION_KEY,),
        ).fetchone()
        if row is None:
            return None
        if not isinstance(row, tuple):
            raise RuntimeError("Invalid JSONL migration marker")
        values = cast(tuple[object, ...], row)
        if len(values) != 1 or not isinstance(values[0], str):
            raise RuntimeError("Invalid JSONL migration marker")
        return values[0]

    @classmethod
    def _encode_migration_manifest(
        cls,
        signatures: dict[str, _JsonlFileSignature],
    ) -> str:
        return cls._encode_json(
            {
                "version": _SQLITE_JSONL_MANIFEST_VERSION,
                "files": {
                    key: {"sha256": signature.sha256}
                    for key, signature in sorted(signatures.items())
                },
            }
        )

    @staticmethod
    def _decode_migration_manifest(
        value: str,
    ) -> dict[str, _JsonlFileSignature]:
        try:
            data = _json_object(json.loads(value))
            version = cast(object, data.get("version"))
            files = cast(object, data.get("files"))
            if (
                not isinstance(version, int)
                or isinstance(version, bool)
                or version != _SQLITE_JSONL_MANIFEST_VERSION
                or not isinstance(files, dict)
            ):
                raise ValueError("unsupported JSONL migration manifest")

            signatures: dict[str, _JsonlFileSignature] = {}
            for raw_key, raw_signature in cast(dict[object, object], files).items():
                if not isinstance(raw_key, str) or not isinstance(raw_signature, dict):
                    raise ValueError("invalid JSONL migration manifest entry")
                signature_data = cast(dict[object, object], raw_signature)
                digest = signature_data.get("sha256")
                if (
                    not isinstance(digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                ):
                    raise ValueError("invalid JSONL migration file signature")
                signatures[raw_key] = _JsonlFileSignature(sha256=digest)
            return signatures
        except _SESSION_DATA_ERRORS as exc:
            raise RuntimeError("Invalid JSONL migration marker") from exc

    @staticmethod
    def _assert_backups_unchanged(
        connection: sqlite3.Connection,
        current: dict[str, _JsonlFileSignature],
        expected: dict[str, _JsonlFileSignature],
    ) -> None:
        changed = {
            key
            for key, signature in current.items()
            if expected.get(key) != signature
        }
        live_keys = {
            row[0]
            for row in connection.execute("SELECT key FROM sessions")
            if isinstance(row[0], str)
        }
        changed.update((expected.keys() - current.keys()).intersection(live_keys))
        if changed:
            raise RuntimeError(
                "JSONL session backups changed after SQLite migration for "
                f"{len(changed)} session(s). Refusing to start to avoid losing "
                "rollback writes; preserve sessions.db and the JSONL files before recovery."
            )

    @classmethod
    def _assert_prepared_sources_unchanged(
        cls,
        source: JsonlSessionFiles,
        expected: dict[str, _JsonlFileSignature],
    ) -> None:
        if cls._current_jsonl_signatures(source) != expected:
            raise RuntimeError(
                "JSONL session files changed while migration was being prepared; "
                "retry startup after session writers have stopped."
            )

    def _prepare_jsonl_sessions(
        self,
        source: JsonlSessionFiles,
    ) -> tuple[list[_PreparedSession], dict[str, _JsonlFileSignature]]:
        prepared: list[_PreparedSession] = []
        signatures: dict[str, _JsonlFileSignature] = {}
        for key, path in source.session_files():
            before = self._file_signature(path)
            session = source.load_for_migration(key)
            if session is None:
                raise RuntimeError(f"Failed to migrate JSONL session {path}")
            prepared_session = self._prepare_session(session)
            after = self._file_signature(path)
            if before != after:
                raise RuntimeError(
                    f"JSONL session file changed while it was being read: {path}"
                )
            prepared.append(prepared_session)
            signatures[key] = after
        return prepared, signatures

    def migrate_from_jsonl(self, source: JsonlSessionFiles) -> int:
        with self._connection(
            timeout=_SQLITE_STARTUP_BUSY_TIMEOUT_SECONDS,
        ) as connection:
            marker = self._read_migration_marker(connection)
            if marker is not None:
                manifest = self._decode_migration_manifest(marker)
                current = self._current_jsonl_signatures(source)
                self._assert_backups_unchanged(connection, current, manifest)
                return 0

        prepared, signatures = self._prepare_jsonl_sessions(source)
        self._assert_prepared_sources_unchanged(source, signatures)
        migrated_count = 0
        with self._connection(
            durable=True,
            timeout=_SQLITE_STARTUP_BUSY_TIMEOUT_SECONDS,
        ) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            marker = self._read_migration_marker(connection)
            if marker is not None:
                manifest = self._decode_migration_manifest(marker)
                self._assert_backups_unchanged(connection, signatures, manifest)
                return 0

            existing_keys = {
                row[0]
                for row in connection.execute("SELECT key FROM sessions")
                if isinstance(row[0], str)
            }
            conflicts = sorted(
                existing_keys.intersection(session.key for session in prepared)
            )
            if conflicts:
                raise RuntimeError(
                    "Cannot migrate JSONL sessions because SQLite already contains "
                    f"{len(conflicts)} matching session key(s)"
                )

            for session in prepared:
                self._save_prepared(connection, session)

            connection.execute(
                "INSERT INTO store_metadata (key, value) VALUES (?, ?)",
                (
                    _SQLITE_JSONL_MIGRATION_KEY,
                    self._encode_migration_manifest(signatures),
                ),
            )
            migrated_count = len(prepared)

        if migrated_count:
            logger.info("Migrated {} JSONL session(s) to SQLite", migrated_count)
        return migrated_count

    @staticmethod
    def _encode_json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_json_object(value: object) -> dict[str, Any]:
        if not isinstance(value, str):
            raise ValueError("SQLite session JSON must be text")
        return _json_object(json.loads(value))

    @classmethod
    def _decode_session_row(
        cls,
        row: object,
    ) -> tuple[str, str, str, dict[str, Any], int]:
        if not isinstance(row, tuple):
            raise ValueError("Invalid SQLite session row")
        values = cast(tuple[object, ...], row)
        if len(values) != 5:
            raise ValueError("Invalid SQLite session row")
        key, created_at, updated_at, metadata_json, last_consolidated = values
        if (
            not isinstance(key, str)
            or not isinstance(created_at, str)
            or not isinstance(updated_at, str)
            or not isinstance(last_consolidated, int)
            or isinstance(last_consolidated, bool)
        ):
            raise ValueError("Invalid SQLite session fields")
        return (
            key,
            created_at,
            updated_at,
            cls._decode_json_object(metadata_json),
            last_consolidated,
        )

    @classmethod
    def _decode_loaded_session_row(
        cls,
        row: object,
    ) -> tuple[
        str,
        str,
        str,
        dict[str, Any],
        int,
        ProviderConversationState | None,
    ]:
        if not isinstance(row, tuple):
            raise ValueError("Invalid SQLite session row")
        values = cast(tuple[object, ...], row)
        if len(values) != 6:
            raise ValueError("Invalid SQLite session row")
        key, created_at, updated_at, metadata_json, private_metadata_json, offset = values
        stored_key, created_at_text, updated_at_text, metadata, last_consolidated = (
            cls._decode_session_row(
                (key, created_at, updated_at, metadata_json, offset)
            )
        )
        private_metadata = cls._decode_json_object(private_metadata_json)
        provider_state = ProviderConversationState.from_private_record(
            private_metadata.get(_PROVIDER_STATE_RECORD_TYPE)
        )
        return (
            stored_key,
            created_at_text,
            updated_at_text,
            metadata,
            last_consolidated,
            provider_state,
        )

    @classmethod
    def _read_messages(
        cls,
        connection: sqlite3.Connection,
        key: str,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        rows = connection.execute(
            "SELECT payload FROM messages WHERE session_key = ? ORDER BY position",
            (key,),
        )
        for raw_row in rows:
            row: object = raw_row
            if not isinstance(row, tuple):
                raise ValueError("Invalid SQLite message row")
            values = cast(tuple[object, ...], row)
            if len(values) != 1:
                raise ValueError("Invalid SQLite message row")
            messages.append(cls._decode_json_object(values[0]))
        return messages

    @classmethod
    def _preview(
        cls,
        connection: sqlite3.Connection,
        key: str,
    ) -> str:
        fallback_preview = ""
        scanned_chars = 0
        rows = connection.execute(
            """
            SELECT payload
            FROM messages
            WHERE session_key = ?
            ORDER BY position
            LIMIT ?
            """,
            (key, _SESSION_LIST_PREVIEW_MAX_RECORDS),
        )
        for raw_row in rows:
            row: object = raw_row
            if not isinstance(row, tuple):
                raise ValueError("Invalid SQLite message row")
            values = cast(tuple[object, ...], row)
            if len(values) != 1 or not isinstance(values[0], str):
                raise ValueError("Invalid SQLite message row")
            payload = values[0]
            scanned_chars += len(payload) + 1
            if scanned_chars > _SESSION_LIST_PREVIEW_MAX_CHARS:
                break
            message = cls._decode_json_object(payload)
            if is_hidden_history_message(message):
                continue
            text = _message_preview_text(message)
            if not text:
                continue
            if message.get("role") == "user":
                return text
            if not fallback_preview and message.get("role") == "assistant":
                fallback_preview = text
        return fallback_preview

    def load(self, key: str) -> Session | None:
        with self._connection() as connection, connection:
            connection.execute("BEGIN")
            row: object = connection.execute(
                """
                SELECT
                    key,
                    created_at,
                    updated_at,
                    metadata,
                    private_metadata,
                    last_consolidated
                FROM sessions
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
            if row is None:
                return None
            try:
                (
                    stored_key,
                    created_at,
                    updated_at,
                    metadata,
                    last_consolidated,
                    provider_state,
                ) = self._decode_loaded_session_row(row)
                messages = self._read_messages(connection, stored_key)
                return Session(
                    key=stored_key,
                    messages=messages,
                    created_at=datetime.fromisoformat(created_at),
                    updated_at=datetime.fromisoformat(updated_at),
                    metadata=metadata,
                    last_consolidated=last_consolidated,
                    provider_state=provider_state,
                )
            except _SESSION_DATA_ERRORS as exc:
                logger.warning("Failed to load SQLite session {}: {}", key, exc)
                raise RuntimeError(f"Failed to load SQLite session {key}") from exc

    def save(self, session: Session, *, fsync: bool = False) -> None:
        prepared = self._prepare_session(session)
        with self._connection(durable=fsync) as connection, connection:
            self._save_prepared(connection, prepared)

    @classmethod
    def _prepare_session(cls, session: Session) -> _PreparedSession:
        metadata_json = cls._encode_json(session.metadata)
        private_metadata_json = cls._encode_json(
            {
                _PROVIDER_STATE_RECORD_TYPE: session.provider_state.to_private_record()
            }
            if session.provider_state is not None
            else {}
        )
        message_rows = tuple(
            (
                session.key,
                position,
                cls._encode_json(_json_object(cast(object, message))),
            )
            for position, message in enumerate(session.messages)
        )
        return _PreparedSession(
            key=session.key,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
            metadata_json=metadata_json,
            private_metadata_json=private_metadata_json,
            last_consolidated=session.last_consolidated,
            message_rows=message_rows,
        )

    @staticmethod
    def _save_prepared(
        connection: sqlite3.Connection,
        session: _PreparedSession,
    ) -> None:
        connection.execute(
            """
            INSERT INTO sessions (
                key,
                created_at,
                updated_at,
                metadata,
                private_metadata,
                last_consolidated
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                metadata = excluded.metadata,
                private_metadata = excluded.private_metadata,
                last_consolidated = excluded.last_consolidated
            """,
            (
                session.key,
                session.created_at,
                session.updated_at,
                session.metadata_json,
                session.private_metadata_json,
                session.last_consolidated,
            ),
        )
        connection.execute("DELETE FROM messages WHERE session_key = ?", (session.key,))
        connection.executemany(
            """
            INSERT INTO messages (session_key, position, payload)
            VALUES (?, ?, ?)
            """,
            session.message_rows,
        )

    def delete(self, key: str) -> bool:
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            marker = self._read_migration_marker(connection)
            if marker is not None:
                manifest = self._decode_migration_manifest(marker)
                if key in manifest:
                    updated_manifest = dict(manifest)
                    updated_manifest.pop(key)
                    connection.execute(
                        "UPDATE store_metadata SET value = ? WHERE key = ?",
                        (
                            self._encode_migration_manifest(updated_manifest),
                            _SQLITE_JSONL_MIGRATION_KEY,
                        ),
                    )
            cursor = connection.execute("DELETE FROM sessions WHERE key = ?", (key,))
            return cursor.rowcount > 0

    def read(self, key: str) -> SessionPayload | None:
        session = self.load(key)
        if session is None:
            return None
        return {
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "messages": session.messages,
        }

    def read_metadata(self, key: str) -> SessionMetadataPayload | None:
        with self._connection() as connection:
            row: object = connection.execute(
                """
                SELECT key, created_at, updated_at, metadata, last_consolidated
                FROM sessions
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
            if row is None:
                return None
            try:
                stored_key, created_at, updated_at, metadata, _ = self._decode_session_row(row)
            except _SESSION_DATA_ERRORS as exc:
                logger.warning("Failed to read SQLite session metadata {}: {}", key, exc)
                raise RuntimeError(
                    f"Failed to read SQLite session metadata {key}"
                ) from exc
            return {
                "key": stored_key,
                "created_at": created_at,
                "updated_at": updated_at,
                "metadata": metadata,
            }

    def list_sessions(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        with self._connection() as connection, connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                """
                SELECT key, created_at, updated_at, metadata, last_consolidated
                FROM sessions
                ORDER BY updated_at DESC, key
                """
            )
            for raw_row in rows:
                row: object = raw_row
                try:
                    key, created_at, updated_at, metadata, _ = self._decode_session_row(row)
                    preview = self._preview(connection, key)
                except _SESSION_DATA_ERRORS as exc:
                    logger.warning("Failed to list SQLite session: {}", exc)
                    raise RuntimeError("Failed to list SQLite sessions") from exc
                sessions.append(
                    {
                        "key": key,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "title": _metadata_title(metadata),
                        "preview": preview,
                        "model_preset": model_preset_from_metadata(metadata),
                        "path": str(self.db_path),
                    }
                )
        return sessions


class SessionManager:
    """Manage session identity, caching, retention, and persistence."""

    def __init__(self, workspace: Path, *, store: SessionStore | None = None):
        self.workspace = workspace
        self._jsonl_files = JsonlSessionFiles(workspace)
        if store is None:
            sqlite_store = SQLiteSessionStore(workspace)
            sqlite_store.migrate_from_jsonl(self._jsonl_files)
            self._store: SessionStore = sqlite_store
        else:
            self._store = store
        self._cache: OrderedDict[str, Session] = OrderedDict()
        # Preserve identity for sessions held by active callers without retaining idle ones.
        self._overflow_cache: WeakValueDictionary[str, Session] = WeakValueDictionary()
        self._max_cached_sessions = SESSION_CACHE_MAX_SIZE
        self._file_cap_archiver: Callable[..., None] | None = None

    def _remember(self, session: Session) -> None:
        """Keep recent sessions strongly cached without duplicating live objects."""
        self._overflow_cache.pop(session.key, None)
        self._cache[session.key] = session
        self._cache.move_to_end(session.key)
        while len(self._cache) > self._max_cached_sessions:
            key, evicted = self._cache.popitem(last=False)
            self._overflow_cache[key] = evicted

    def _cached(self, key: str) -> Session | None:
        session = self._cache.get(key)
        if session is not None:
            self._cache.move_to_end(key)
            return session

        session = self._overflow_cache.get(key)
        if session is not None:
            self._remember(session)
        return session

    def get_cached(self, key: str) -> Session | None:
        """Return a cached session without creating or loading one from disk."""
        return self._cached(key)

    def set_file_cap_archiver(self, archiver: Callable[..., None]) -> None:
        """Archive unconsolidated overflow whenever a session is persisted."""
        self._file_cap_archiver = archiver

    @staticmethod
    def safe_key(key: str) -> str:
        """Public helper used by HTTP handlers to map an arbitrary key to a stable filename stem."""
        return JsonlSessionFiles.safe_key(key)

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        session = self._cached(key)
        if session is not None:
            return session

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._remember(session)
        return session

    def _load(self, key: str) -> Session | None:
        return self._store.load(key)

    def save(self, session: Session, *, fsync: bool = False) -> None:
        """Persist a session and retain it in the cache."""
        archiver = self._file_cap_archiver
        if archiver is not None:
            session.enforce_file_cap(
                on_archive=lambda messages: archiver(
                    messages,
                    session_key=session.key,
                )
            )

        self._store.save(session, fsync=fsync)
        self._remember(session)

    def flush_all(self) -> int:
        """Re-save every cached session with fsync for durable shutdown.

        Returns the number of sessions flushed.  Errors on individual
        sessions are logged but do not prevent other sessions from being
        flushed.
        """
        flushed = 0
        cached = dict(self._overflow_cache.items())
        cached.update(self._cache)
        for key, session in cached.items():
            try:
                self.save(session, fsync=True)
                flushed += 1
            except Exception:
                logger.warning("Failed to flush session {}", key, exc_info=True)
        return flushed

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)
        self._overflow_cache.pop(key, None)

    def delete_session(self, key: str) -> bool:
        """Delete a persisted session and invalidate its cache entry."""
        self.invalidate(key)
        backup_deleted = self._jsonl_files.delete_backups(key)
        deleted = self._store.delete(key)
        return backup_deleted or deleted

    def fork_session_before_user_index(
        self,
        source_key: str,
        target_key: str,
        before_user_index: int,
    ) -> Session | None:
        """Create *target_key* from *source_key* before a global user-message index.

        ``before_user_index`` is zero-based over user messages in the full session:
        ``0`` means "before the first user message", ``1`` means "before the
        second user message", and so on. A value equal to the total user-message
        count copies the full session prefix. WebUI assistant-reply forks pass
        the next user index so the selected completed assistant turn is included.
        """
        if before_user_index < 0:
            return None
        source = self._cached(source_key) or self._load(source_key)
        if source is None:
            return None

        copied: list[dict[str, Any]] = []
        user_index = 0
        found_target = False
        for message in source.messages:
            if message.get("role") == "user":
                if user_index == before_user_index:
                    found_target = True
                    break
                user_index += 1
            copied.append(public_history_message(message))
        if user_index == before_user_index:
            found_target = True
        if not found_target:
            return None

        metadata = deepcopy(source.metadata)
        for key in _FORK_VOLATILE_METADATA_KEYS:
            metadata.pop(key, None)

        last_consolidated = min(source.last_consolidated, len(copied))
        if source.last_consolidated > len(copied):
            metadata.pop("_last_summary", None)
            last_consolidated = 0

        now = datetime.now()
        target = Session(
            key=target_key,
            messages=copied,
            created_at=now,
            updated_at=now,
            metadata=metadata,
            last_consolidated=last_consolidated,
        )
        self.save(target, fsync=True)
        return target

    def read_session_file(self, key: str) -> dict[str, Any] | None:
        """Read a session without populating the cache."""
        return cast(dict[str, Any] | None, self._store.read(key))

    def read_session_metadata(self, key: str) -> dict[str, Any] | None:
        """Read session metadata without loading the transcript."""
        return cast(dict[str, Any] | None, self._store.read_metadata(key))

    def list_sessions(self) -> list[SessionInfo]:
        return self._store.list_sessions()
