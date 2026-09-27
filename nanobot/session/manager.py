"""Session management for conversation history."""

from __future__ import annotations

import re
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Generator, TypedDict, cast
from uuid import uuid4

from nanobot.providers.base import ProviderConversationState
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    public_history_message,
)
from nanobot.session.history_visibility import HIDDEN_HISTORY_META, is_hidden_history_message
from nanobot.session.location import SessionLocation
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY
from nanobot.session.summary import SUMMARY_CONTINUATION_TEXT, is_summary_checkpoint
from nanobot.session.types import PARENT_SESSION_KEY, SESSION_TYPE_KEY, SessionTypes
from nanobot.utils.helpers import (
    content_with_media_breadcrumbs,
    estimate_message_tokens,
    find_legal_message_start,
    recent_message_start_index,
    strip_think,
)
from nanobot.utils.subagent_channel_display import scrub_subagent_announce_body

if TYPE_CHECKING:
    from nanobot.session.state import SessionState

SESSION_CACHE_MAX_SIZE = 128
_MESSAGE_TIME_PREFIX_RE = re.compile(r"^\[Message Time: [^\]]+\]\n?")
_LOCAL_IMAGE_BREADCRUMB_RE = re.compile(r"^\[image: (?:/|~)[^\]]+\]\s*$")
_TOOL_CALL_ECHO_RE = re.compile(r'^\s*(?:generate_image|message)\([^)]*\)\s*$')
_SESSION_PREVIEW_MAX_CHARS = 120
_SESSION_LIST_PREVIEW_MAX_RECORDS = 200
_SESSION_LIST_PREVIEW_MAX_CHARS = 1_000_000
_FORK_VOLATILE_METADATA_KEYS = {
    PARENT_SESSION_KEY,
    SESSION_TYPE_KEY,
    "goal_state",
    "pending_user_turn",
    "pending_user_followups",
    "runtime_checkpoint",
    "session_handle",
    "webui_recovery",
    "thread_goal",
    "title",
    "title_user_edited",
}


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


def message_preview_text(message: dict[str, Any]) -> str:
    """Session list preview text; subagent inject blobs are shortened for display."""
    message = public_history_message(message)
    content = cast(object, message.get("content"))
    if message.get("injected_event") == "subagent_result" and isinstance(content, str):
        content = scrub_subagent_announce_body(content)
    return _text_preview(content)


def metadata_title(metadata: object) -> str:
    if not isinstance(metadata, dict):
        return ""
    metadata_data = cast(dict[object, object], metadata)
    title = metadata_data.get("title")
    if not isinstance(title, str):
        return ""
    if metadata_data.get("title_user_edited") is True:
        return title
    return strip_think(title)


@dataclass(frozen=True)
class SessionPolicy:
    """Runtime rules that do not belong in durable session data."""

    persist: bool = True
    log_content: bool = True
    disabled_tools: frozenset[str] = frozenset()


@dataclass
class Session:
    """Message history, runtime state, and metadata for one agent session."""

    key: str  # namespace:identity
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Keep the legacy storage name while persisted sessions and SDK callers migrate.
    last_consolidated: int = 0
    provider_state: ProviderConversationState | None = field(default=None, repr=False)
    policy: SessionPolicy = field(default_factory=SessionPolicy, repr=False, compare=False)

    # Owner-private committed snapshot. Never mutate or expose its records as draft data.
    _baseline: Session | None = field(default=None, repr=False, compare=False)
    persisted: bool = field(default=False, repr=False, compare=False)
    revision: int = field(default=0, repr=False, compare=False)
    generation: str = field(default_factory=lambda: uuid4().hex, repr=False, compare=False)

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

    @property
    def last_archived(self) -> int:
        """End of the latest committed Memory checkpoint."""
        return self.last_consolidated

    @last_archived.setter
    def last_archived(self, value: int) -> None:
        self.last_consolidated = value

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

    def commit_summary_checkpoint(
        self,
        summary: str,
        *,
        insert_at: int | None = None,
        last_active: datetime | None = None,
    ) -> None:
        """Replace replay before a hidden boundary while preserving the transcript."""
        boundary = len(self.messages) if insert_at is None else insert_at
        self.messages.insert(boundary, {
            "role": "user",
            "content": SUMMARY_CONTINUATION_TEXT,
            HIDDEN_HISTORY_META: True,
            "timestamp": datetime.now().isoformat(),
        })
        self.metadata["_last_summary"] = {
            "text": summary,
            "last_active": (last_active or self.updated_at).isoformat(),
        }
        self.last_archived = boundary

    def get_history(
        self,
        max_messages: int = 0,
        *,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        include_runtime_context: bool = True,
    ) -> list[dict[str, Any]]:
        """Return recent replayable messages for LLM input.

        A committed summary checkpoint replaces its old prefix with the stored
        summary and resumes replay after its hidden boundary marker. The marker
        is not a user request and must not resume an old task on the next turn.
        A positive ``max_messages`` applies an additional caller-owned count limit.
        """
        replayable = self.messages[self.last_archived:]
        if max_messages <= 0:
            start_idx = 0
        else:
            start_idx = recent_message_start_index(
                replayable,
                max_messages,
                extend_to_user=extend_to_user,
            )
        sliced = replayable[start_idx:]

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
            if message.get("_command") or is_summary_checkpoint(message):
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
        self.last_archived = 0
        self.provider_state = None
        self.updated_at = datetime.now()
        self.metadata.pop("_last_summary", None)

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
    path: str


def fork_session(source: Session, target_key: str, before_user_index: int) -> Session | None:
    """Build a portable fork ending before the requested visible user message."""
    if before_user_index < 0:
        return None
    copied: list[dict[str, Any]] = []
    user_index = 0
    found_target = False
    for message in source.messages:
        if message.get("role") == "user" and not is_hidden_history_message(message):
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

    last_consolidated = min(source.last_archived, len(copied))
    if source.last_archived > len(copied):
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
    return target


class SessionManager:
    """Locate session storage and expose synchronous administrative operations."""

    def __init__(
        self,
        workspace: Path,
        *,
        sessions_root: Path | None = None,
    ):
        from nanobot.session.sqlite_store import SqliteSessionStore

        self.workspace = workspace
        self.location = SessionLocation(workspace, sessions_root=sessions_root)
        self.sessions_dir = self.location.sessions_dir
        self._store = SqliteSessionStore(self.sessions_dir)
        self._store.initialize(workspace)
        self._delete_observer: Callable[[str], None] | None = None
        self.types = SessionTypes()
        self._state: SessionState | None = None

    @property
    def state(self) -> SessionState:
        """The asynchronous owner of session state transitions."""
        if self._state is None:
            from nanobot.session.state import SessionState

            self._state = SessionState(self._store, on_delete=self._notify_delete)
        return self._state

    def _notify_delete(self, key: str) -> None:
        if self._delete_observer is not None:
            self._delete_observer(key)

    def get_cached(self, key: str) -> Session | None:
        return self.state.peek(key)

    def set_delete_observer(self, observer: Callable[[str], None]) -> None:
        """Observe explicit session deletion for process-local state cleanup."""
        self._delete_observer = observer

    @staticmethod
    def safe_key(key: str) -> str:
        """Public helper used by HTTP handlers to map an arbitrary key to a stable filename stem."""
        return SessionLocation.safe_key(key)

    @staticmethod
    def _storage_key(key: str) -> str:
        """Collision-resistant encoding for internal session storage filenames."""
        return SessionLocation.storage_key(key)

    @staticmethod
    def _decode_storage_key(stem: str) -> str | None:
        """Reverse _storage_key(): decode a base64url (no-padding) stem back to the original key."""
        return SessionLocation.decode_storage_key(stem)

    @staticmethod
    def decode_storage_key(stem: str) -> str | None:
        """Public decoder for components that inspect canonical session filenames."""
        return SessionManager._decode_storage_key(stem)

    @classmethod
    def _session_key_from_path(cls, path: Path) -> str | None:
        """Decode a session key only from a canonical collision-resistant filename."""
        return SessionLocation.session_key_from_path(path)

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Group synchronous administrative operations in one SQLite transaction."""
        with self._store.transaction():
            yield

    def get_or_create(self, key: str) -> Session:
        """Load a detached snapshot for synchronous administrative callers."""
        return self._store.load(key) or Session(key=key)

    def get_existing(self, key: str) -> Session | None:
        """Read an existing session without recreating a deleted conversation."""
        return self.get_cached(key) or self._store.load(key)

    def child_session_keys(self, parent_key: str) -> list[str]:
        """Find persisted children through their declared parent."""
        return [row["key"] for row in self._store.list_metadata()
                if row["metadata"].get(PARENT_SESSION_KEY) == parent_key]

    def save(self, session: Session) -> None:
        """Commit an administrative snapshot, rejecting obsolete history."""
        if session.policy.persist:
            self._store.save(session)

    def rename_model_preset(self, old_name: str, new_name: str) -> int:
        if old_name == new_name:
            return 0
        changed = 0
        with self.transaction():
            for row in self._store.list_metadata():
                if row["metadata"].get(SESSION_MODEL_PRESET_METADATA_KEY) == old_name:
                    self._store.update_metadata(row["key"], {SESSION_MODEL_PRESET_METADATA_KEY: new_name})
                    changed += 1
        return changed

    def invalidate(self, key: str) -> None:
        if self._state is not None:
            self._state.forget_transient(key)

    def delete_session(self, key: str) -> bool:
        """Delete a session and its persisted descendants in one transaction."""
        with self.transaction():
            pending = [key]
            collected: set[str] = set()
            while pending:
                current = pending.pop()
                if current in collected:
                    continue
                collected.add(current)
                pending.extend(self.child_session_keys(current))
            deleted = False
            for current in collected:
                deleted = self._store.delete(current) or deleted
                self.invalidate(current)
                self._notify_delete(current)
            return deleted

    def export_sessions_to_workspace(self) -> int:
        """Export portable JSONL copies; SQLite remains authoritative."""
        from nanobot.session.export import export_sessions

        return export_sessions(self._store, self.workspace / "sessions")

    def fork_session_before_user_index(
        self, source_key: str, target_key: str, before_user_index: int,
    ) -> Session | None:
        with self.transaction():
            source = self._store.load(source_key)
            if source is None:
                return None
            target = fork_session(source, target_key, before_user_index)
            if target is not None:
                self._store.save(target)
            return target

    def read_session_file(self, key: str) -> dict[str, Any] | None:
        """Read a session without populating the cache."""
        return cast(dict[str, Any] | None, self._store.read(key))

    def read_session_snapshot(self, key: str) -> Session | None:
        """Load a detached session snapshot without populating the runtime cache."""
        return self._store.load(key)

    def read_session_metadata(self, key: str) -> dict[str, Any] | None:
        """Read session metadata without loading the transcript."""
        return cast(dict[str, Any] | None, self._store.read_metadata(key))

    def update_session_metadata(
        self,
        key: str,
        updates: dict[str, Any],
    ) -> bool:
        """Atomically update metadata without replacing session history."""
        return self._store.update_metadata(key, updates)

    def list_session_metadata(self) -> list[dict[str, Any]]:
        return self._store.list_metadata()

    def list_sessions(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._store.list_sessions())
