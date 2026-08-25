"""Session management for conversation history."""

import base64
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
from collections import OrderedDict
from contextlib import contextmanager, suppress
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Collection, Generator, Protocol, TypedDict, cast
from weakref import WeakValueDictionary

from filelock import FileLock
from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir, get_runtime_subdir
from nanobot.providers.base import ProviderConversationState
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    public_history_message,
)
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY
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

SESSION_CACHE_MAX_SIZE = 128
MIN_COMPACTED_REPLAY_MESSAGES = 8
_MESSAGE_TIME_PREFIX_RE = re.compile(r"^\[Message Time: [^\]]+\]\n?")
_LOCAL_IMAGE_BREADCRUMB_RE = re.compile(r"^\[image: (?:/|~)[^\]]+\]\s*$")
_TOOL_CALL_ECHO_RE = re.compile(r'^\s*(?:generate_image|message)\([^)]*\)\s*$')
_SESSION_PREVIEW_MAX_CHARS = 120
_SESSION_LIST_PREVIEW_MAX_RECORDS = 200
_SESSION_LIST_PREVIEW_MAX_CHARS = 1_000_000
_SESSION_DATA_ERRORS = (ValueError, TypeError, AttributeError, KeyError)
_RUNTIME_CHECKPOINT_DATA_ERRORS = (OSError, *_SESSION_DATA_ERRORS)
_PROVIDER_STATE_RECORD_TYPE = "provider_state"
_PROVIDER_STATE_RECORD_PREFIX_RE = re.compile(
    r'^\s*\{\s*"_type"\s*:\s*"provider_state"\s*(?:,|\})'
)
_RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
_RUNTIME_CHECKPOINT_VERSION = 1
_RUNTIME_CHECKPOINT_SUFFIX = ".checkpoint.json"
_FORK_VOLATILE_METADATA_KEYS = {
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
_WORKSPACE_STATE_DIR = ".nanobot"
_WORKSPACE_ID_FILE = "workspace-id"
_WORKSPACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SESSION_MIGRATION_LOCK_TIMEOUT_SECONDS = 30
_SESSION_FILES_LOCK_FILENAME = ".session-files.lock"
_COPY_CHUNK_SIZE = 1024 * 1024


def _json_object(value: object) -> dict[str, Any]:
    """Narrow a decoded JSON object while preserving its original values."""
    if not isinstance(value, dict):
        raise ValueError("session records must be JSON objects")
    return cast(dict[str, Any], value)


# TODO(0.3.2): Remove the write_stdin replay migration after 0.3.1.
def _migrate_legacy_exec_arguments(container: dict[str, Any]) -> bool:
    raw_arguments = cast(object, container.get("arguments"))
    encoded = isinstance(raw_arguments, str)
    if encoded:
        try:
            decoded: object = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return False
    else:
        decoded = raw_arguments
    if not isinstance(decoded, dict):
        return False

    arguments = cast(dict[str, Any], decoded)
    changed = False
    if "chars" in arguments:
        if "input" not in arguments:
            arguments["input"] = arguments["chars"]
        arguments.pop("chars")
        changed = True

    wait_key = (
        "wait_timeout_ms"
        if arguments.get("wait_for") or arguments.get("until_exit")
        else "yield_time_ms"
    )
    if "timeout_ms" not in arguments and wait_key in arguments:
        arguments["timeout_ms"] = arguments[wait_key]
    for key in ("yield_time_ms", "wait_timeout_ms", "max_output_chars", "max_output_tokens"):
        if key in arguments:
            arguments.pop(key)
            changed = True

    if changed:
        container["arguments"] = (
            json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
            if encoded
            else arguments
        )
    return changed


def _migrate_legacy_exec_tool_call(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    tool_call = cast(dict[str, Any], value)
    function_value = cast(object, tool_call.get("function"))
    function = (
        cast(dict[str, Any], function_value)
        if isinstance(function_value, dict)
        else tool_call
    )
    name = function.get("name")
    if name not in {"write_stdin", "exec_session"}:
        return False

    changed = name == "write_stdin"
    if changed:
        function["name"] = "exec_session"
    return _migrate_legacy_exec_arguments(function) or changed


def _migrate_legacy_exec_message(message: dict[str, Any]) -> bool:
    changed = False
    if message.get("name") == "write_stdin":
        message["name"] = "exec_session"
        changed = True
    tool_calls = cast(object, message.get("tool_calls"))
    if isinstance(tool_calls, list):
        for tool_call in cast(list[object], tool_calls):
            changed = _migrate_legacy_exec_tool_call(tool_call) or changed
    return changed


def _migrate_legacy_exec_session_records(
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> bool:
    changed = False
    for message in messages:
        changed = _migrate_legacy_exec_message(message) or changed

    checkpoint_value = cast(object, metadata.get(_RUNTIME_CHECKPOINT_KEY))
    if not isinstance(checkpoint_value, dict):
        return changed
    checkpoint = cast(dict[str, Any], checkpoint_value)
    assistant = cast(object, checkpoint.get("assistant_message"))
    if isinstance(assistant, dict):
        changed = _migrate_legacy_exec_message(cast(dict[str, Any], assistant)) or changed
    pending = cast(object, checkpoint.get("pending_tool_calls"))
    if isinstance(pending, list):
        for tool_call in cast(list[object], pending):
            changed = _migrate_legacy_exec_tool_call(tool_call) or changed
    completed = cast(object, checkpoint.get("completed_tool_results"))
    if isinstance(completed, list):
        for result in cast(list[object], completed):
            if isinstance(result, dict):
                result_data = cast(dict[str, Any], result)
                if result_data.get("name") == "write_stdin":
                    result_data["name"] = "exec_session"
                    changed = True
    return changed


def _is_provider_state_record_line(line: str) -> bool:
    """Recognize the canonical private record without decoding its opaque payload."""
    return _PROVIDER_STATE_RECORD_PREFIX_RE.match(line) is not None


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


@dataclass(frozen=True)
class SessionPolicy:
    """Runtime rules that do not belong in durable session data."""

    persist: bool = True
    log_content: bool = True
    disabled_tools: frozenset[str] = frozenset()


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
    policy: SessionPolicy = field(default_factory=SessionPolicy, repr=False, compare=False)

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
        max_messages: int = 0,
        *,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        include_runtime_context: bool = True,
    ) -> list[dict[str, Any]]:
        """Return recent replayable messages for LLM input.

        A positive ``max_messages`` applies an explicit caller-owned count
        limit. The normal model path relies on ``max_tokens`` instead.
        """
        replay_start = self.last_consolidated
        if replay_start:
            # ``last_consolidated`` is archive progress, not a replay boundary.
            # Keep a small raw suffix for continuity, extending back to the user
            # that started an assistant/tool sequence when necessary.
            recent_start = recent_message_start_index(
                self.messages,
                MIN_COMPACTED_REPLAY_MESSAGES,
                extend_to_user=True,
            )
            replay_start = min(replay_start, recent_start)

        replayable = self.messages[replay_start:]
        if max_messages <= 0:
            start_idx = 0
        else:
            unarchived_count = len(self.messages) - self.last_consolidated
            if replay_start < self.last_consolidated and unarchived_count < max_messages:
                # The archived replay suffix can exceed the nominal count when one
                # tool-heavy turn spans the boundary. Preserve that complete turn.
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
            recovered_user = next(
                (i for i in range(start_idx, -1, -1) if self.messages[i].get("role") == "user"),
                None,
            )
            if recovered_user is not None:
                start_idx = recovered_user
                if start_idx > 0 and self.messages[start_idx - 1].get("_channel_delivery"):
                    start_idx -= 1

        retained = self.messages[start_idx:]

        # Prefer starting at a user turn (or its preceding _channel_delivery) when one exists within the retained window.
        first_user = next((i for i, m in enumerate(retained) if m.get("role") == "user"), None)
        if first_user is not None:
            if first_user > 0 and retained[first_user - 1].get("_channel_delivery"):
                retained = retained[first_user - 1:]
            else:
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


@dataclass(frozen=True)
class _SessionFileSnapshot:
    digest: str
    size: int
    mtime_ns: int
    updated_at: float
    device: int
    inode: int


@dataclass(frozen=True)
class SessionRestoreResult:
    restored: int
    unchanged: int
    conflicts: tuple[Path, ...]


class SessionStore(Protocol):
    def load(self, key: str) -> Session | None: ...

    def save(self, session: Session, *, fsync: bool = False) -> None: ...

    def delete(self, key: str) -> bool: ...

    def read(self, key: str) -> SessionPayload | None: ...

    def read_metadata(self, key: str) -> SessionMetadataPayload | None: ...

    def update_metadata(
        self,
        key: str,
        updates: dict[str, Any],
        *,
        fsync: bool = False,
    ) -> bool: ...

    def list_sessions(self) -> list[SessionInfo]: ...


class JsonlSessionStore:
    """JSONL implementation of session persistence."""

    def __init__(self, workspace: Path, *, sessions_root: Path | None = None):
        canonical_workspace = Path(workspace).expanduser().resolve(strict=False)
        ensure_dir(canonical_workspace)
        root = (
            Path(sessions_root).expanduser().resolve(strict=False)
            if sessions_root is not None
            else get_runtime_subdir("sessions").resolve(strict=False)
        )
        if root == canonical_workspace or root.is_relative_to(canonical_workspace):
            raise RuntimeError(
                "session storage must be outside the agent workspace; "
                "move --config outside --workspace or choose a nested workspace directory"
            )
        ensure_dir(root)
        with suppress(OSError):
            os.chmod(root, 0o700)
        self.workspace = canonical_workspace
        self._migration_lock = FileLock(
            str(root / ".workspace-migration.lock"),
            timeout=_SESSION_MIGRATION_LOCK_TIMEOUT_SECONDS,
        )
        with self._migration_lock:
            workspace_id = self._load_or_create_workspace_id(canonical_workspace, root)
            workspace_id = self._claim_workspace_namespace(
                root,
                canonical_workspace,
                workspace_id,
            )
            self.sessions_dir = ensure_dir(root / workspace_id)
            self.legacy_sessions_dir = get_legacy_sessions_dir()
            self._session_files_lock = FileLock(
                str(self.sessions_dir / _SESSION_FILES_LOCK_FILENAME)
            )
            with self._session_files_lock:
                self._migrate_from_workspace(canonical_workspace)

    @contextmanager
    def locked_session_files(self) -> Generator[Path, None, None]:
        """Guard direct access to canonical session files in this directory."""
        with self._session_files_lock:
            yield self.sessions_dir

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        with suppress(PermissionError, NotImplementedError):
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            except OSError as exc:
                if exc.errno != errno.EINVAL:
                    raise
            finally:
                os.close(fd)

    @classmethod
    def _write_text_atomic(cls, path: Path, content: str, *, mode: int = 0o600) -> None:
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with open(tmp, "x", encoding="utf-8") as handle:
                os.chmod(tmp, mode)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            cls._fsync_directory(path.parent)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def _read_workspace_id(cls, marker: Path) -> str:
        if marker.is_symlink():
            raise RuntimeError(f"workspace identity marker must not be a symlink: {marker}")
        value = marker.read_text(encoding="utf-8").strip()
        if not _WORKSPACE_ID_RE.fullmatch(value):
            raise RuntimeError(
                f"workspace identity marker is invalid: {marker}; "
                "restore its original 32-character identifier before starting nanobot"
            )
        return value

    @staticmethod
    def _workspace_id_path(workspace: Path) -> Path:
        state_dir = workspace / _WORKSPACE_STATE_DIR
        if state_dir.is_symlink():
            raise RuntimeError(f"workspace state directory must not be a symlink: {state_dir}")
        ensure_dir(state_dir)
        return state_dir / _WORKSPACE_ID_FILE

    @classmethod
    def _find_workspace_namespace(cls, workspace: Path, root: Path) -> str | None:
        """Recover an identity marker removed by cleanup at the same workspace path."""
        matches: list[str] = []
        for sessions_dir in root.iterdir():
            if (
                not _WORKSPACE_ID_RE.fullmatch(sessions_dir.name)
                or sessions_dir.is_symlink()
                or not sessions_dir.is_dir()
            ):
                continue
            marker = sessions_dir / ".workspace"
            if marker.is_symlink() or not marker.is_file():
                continue
            try:
                recorded = Path(marker.read_text(encoding="utf-8").strip()).expanduser()
                recorded = recorded.resolve(strict=False)
                same_workspace = recorded == workspace or (
                    recorded.exists() and recorded.samefile(workspace)
                )
            except (OSError, UnicodeError, ValueError):
                continue
            if same_workspace:
                matches.append(sessions_dir.name)
        if len(matches) > 1:
            raise RuntimeError(
                f"multiple session namespaces claim workspace {workspace}; "
                "remove the stale namespace marker before starting nanobot"
            )
        return matches[0] if matches else None

    @classmethod
    def _load_or_create_workspace_id(cls, workspace: Path, root: Path) -> str:
        marker = cls._workspace_id_path(workspace)
        if marker.exists() or marker.is_symlink():
            return cls._read_workspace_id(marker)

        recovered = cls._find_workspace_namespace(workspace, root)
        if recovered is not None:
            cls._write_text_atomic(marker, f"{recovered}\n")
            return recovered

        workspace_id = secrets.token_hex(16)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(marker, flags, 0o600)
        except FileExistsError:
            return cls._read_workspace_id(marker)
        try:
            payload = f"{workspace_id}\n".encode("ascii")
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        except BaseException:
            with suppress(OSError):
                marker.unlink()
            raise
        finally:
            os.close(fd)
        cls._fsync_directory(marker.parent)
        return workspace_id

    @classmethod
    def _replace_workspace_id(cls, workspace: Path, workspace_id: str) -> None:
        cls._write_text_atomic(cls._workspace_id_path(workspace), f"{workspace_id}\n")

    @classmethod
    def _write_workspace_marker(cls, sessions_dir: Path, workspace: Path) -> None:
        cls._write_text_atomic(sessions_dir / ".workspace", f"{workspace}\n")

    @classmethod
    def _claim_workspace_namespace(
        cls,
        root: Path,
        workspace: Path,
        workspace_id: str,
    ) -> str:
        """Bind a stable workspace ID, rotating copied live workspaces apart."""
        for _attempt in range(3):
            sessions_dir = root / workspace_id
            marker = sessions_dir / ".workspace"
            if sessions_dir.is_symlink():
                raise RuntimeError(f"session namespace must not be a symlink: {sessions_dir}")
            if not sessions_dir.exists():
                ensure_dir(sessions_dir)
                cls._write_workspace_marker(sessions_dir, workspace)
                return workspace_id
            if marker.is_symlink():
                raise RuntimeError(f"session workspace marker must not be a symlink: {marker}")
            if not marker.exists():
                if any(sessions_dir.iterdir()):
                    raise RuntimeError(
                        f"session namespace has data but no workspace marker: {sessions_dir}"
                    )
                cls._write_workspace_marker(sessions_dir, workspace)
                return workspace_id

            recorded_text = marker.read_text(encoding="utf-8").strip()
            if not recorded_text:
                raise RuntimeError(f"session workspace marker is empty: {marker}")
            recorded = Path(recorded_text).expanduser().resolve(strict=False)
            if recorded == workspace:
                return workspace_id
            try:
                same_workspace = recorded.exists() and recorded.samefile(workspace)
            except OSError:
                same_workspace = False
            if same_workspace:
                cls._write_workspace_marker(sessions_dir, workspace)
                return workspace_id
            if not recorded.exists():
                # The identity marker travelled with a renamed or moved workspace.
                cls._write_workspace_marker(sessions_dir, workspace)
                return workspace_id

            # Both paths exist and are different: this is a copy, not a move.
            workspace_id = secrets.token_hex(16)
            cls._replace_workspace_id(workspace, workspace_id)

        raise RuntimeError(f"could not allocate an isolated session namespace for {workspace}")

    @staticmethod
    def _session_file_snapshot(path: Path) -> _SessionFileSnapshot | None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except OSError:
            return None
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                return None
            digest = hashlib.sha256()
            saw_record = False
            updated_at: float | None = None
            with os.fdopen(fd, "rb", closefd=False) as handle:
                for raw_line in handle:
                    digest.update(raw_line)
                    if not raw_line.strip():
                        continue
                    value: object = json.loads(raw_line.decode("utf-8"))
                    data = _json_object(value)
                    saw_record = True
                    if data.get("_type") == "metadata":
                        raw_updated_at = cast(object, data.get("updated_at"))
                        if isinstance(raw_updated_at, str) and raw_updated_at:
                            updated_at = datetime.fromisoformat(raw_updated_at).timestamp()
            after = os.fstat(fd)
            if (
                not saw_record
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
            ):
                return None
            return _SessionFileSnapshot(
                digest=digest.hexdigest(),
                size=after.st_size,
                mtime_ns=after.st_mtime_ns,
                updated_at=(updated_at if updated_at is not None else after.st_mtime_ns / 1e9),
                device=after.st_dev,
                inode=after.st_ino,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            return None
        finally:
            os.close(fd)

    @classmethod
    def _prepare_copy(
        cls,
        src: Path,
        dst_dir: Path,
        snapshot: _SessionFileSnapshot,
    ) -> Path:
        tmp = dst_dir / f".{src.name}.{secrets.token_hex(8)}.tmp"
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        src_fd = os.open(src, flags)
        try:
            before = os.fstat(src_fd)
            if (
                before.st_dev != snapshot.device
                or before.st_ino != snapshot.inode
                or before.st_size != snapshot.size
                or before.st_mtime_ns != snapshot.mtime_ns
            ):
                raise OSError("session source changed before migration")
            digest = hashlib.sha256()
            size = 0
            with os.fdopen(src_fd, "rb", closefd=False) as source, open(tmp, "xb") as target:
                os.chmod(tmp, 0o600)
                while chunk := source.read(_COPY_CHUNK_SIZE):
                    digest.update(chunk)
                    size += len(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            after = os.fstat(src_fd)
            if (
                digest.hexdigest() != snapshot.digest
                or size != snapshot.size
                or after.st_dev != snapshot.device
                or after.st_ino != snapshot.inode
                or after.st_size != snapshot.size
                or after.st_mtime_ns != snapshot.mtime_ns
            ):
                raise OSError("session source changed during migration")
            return tmp
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        finally:
            os.close(src_fd)

    @classmethod
    def _install_snapshot(
        cls,
        src: Path,
        dst: Path,
        snapshot: _SessionFileSnapshot,
    ) -> None:
        tmp = cls._prepare_copy(src, dst.parent, snapshot)
        try:
            os.replace(tmp, dst)
            cls._fsync_directory(dst.parent)
            installed = cls._session_file_snapshot(dst)
            if installed is None or installed.digest != snapshot.digest:
                raise OSError(f"session migration verification failed: {dst}")
        finally:
            tmp.unlink(missing_ok=True)

    def _archive_conflict(
        self,
        src: Path,
        snapshot: _SessionFileSnapshot,
        label: str,
    ) -> Path:
        conflict_dir = ensure_dir(self.sessions_dir / ".migration-conflicts")
        conflict = conflict_dir / (
            f"{src.stem}.{label}.{snapshot.digest[:12]}.{secrets.token_hex(4)}.jsonl"
        )
        self._install_snapshot(src, conflict, snapshot)
        return conflict

    @classmethod
    def _remove_migrated_source(
        cls,
        src: Path,
        snapshot: _SessionFileSnapshot,
    ) -> bool:
        try:
            current = src.stat(follow_symlinks=False)
            if (
                current.st_dev != snapshot.device
                or current.st_ino != snapshot.inode
                or current.st_size != snapshot.size
                or current.st_mtime_ns != snapshot.mtime_ns
            ):
                return False
            src.unlink()
            cls._fsync_directory(src.parent)
            return True
        except OSError:
            return False

    def _migrate_from_workspace(self, workspace: Path) -> None:
        """Durably copy legacy sessions out of the workspace, then remove the source."""
        old_dir = workspace / "sessions"
        if old_dir.is_symlink() or not old_dir.is_dir():
            if old_dir.is_symlink():
                logger.warning("Skipping symlinked legacy sessions directory: {}", old_dir)
            return
        for src in old_dir.glob("*.jsonl"):
            if src.is_symlink() or not src.is_file():
                logger.warning("Skipping unsafe legacy session file: {}", src)
                continue
            dst = self.sessions_dir / src.name
            source_snapshot = self._session_file_snapshot(src)
            if source_snapshot is None:
                logger.warning("Skipping invalid or changing legacy session file: {}", src)
                continue
            try:
                destination_snapshot = self._session_file_snapshot(dst) if dst.exists() else None
                if dst.exists() and destination_snapshot is None:
                    logger.warning(
                        "Keeping legacy session because destination is invalid: {}",
                        dst,
                    )
                    continue

                if destination_snapshot is None:
                    self._install_snapshot(src, dst, source_snapshot)
                elif destination_snapshot.digest == source_snapshot.digest:
                    pass
                elif source_snapshot.updated_at > destination_snapshot.updated_at:
                    archived = self._archive_conflict(dst, destination_snapshot, "destination")
                    self._install_snapshot(src, dst, source_snapshot)
                    logger.warning("Archived older session migration conflict at {}", archived)
                else:
                    archived = self._archive_conflict(src, source_snapshot, "workspace")
                    logger.warning("Archived older session migration conflict at {}", archived)

                installed = self._session_file_snapshot(dst)
                if installed is None:
                    raise OSError(f"session migration destination is unreadable: {dst}")
                selected_digest = (
                    source_snapshot.digest
                    if destination_snapshot is None
                    or source_snapshot.updated_at > destination_snapshot.updated_at
                    else destination_snapshot.digest
                )
                if installed.digest != selected_digest:
                    raise OSError(f"session migration selected unexpected data: {dst}")
                if not self._remove_migrated_source(src, source_snapshot):
                    logger.warning(
                        "Session migrated but legacy source changed or could not be removed: {}",
                        src,
                    )
            except OSError as exc:
                logger.warning("Failed to migrate session {}: {}", src, exc)

    def restore_to_workspace(self) -> SessionRestoreResult:
        """Copy canonical sessions back for an explicit downgrade or rollback."""
        restored = 0
        unchanged = 0
        conflicts: list[Path] = []
        old_dir = self.workspace / "sessions"
        if old_dir.is_symlink():
            raise RuntimeError(f"refusing to restore into symlinked sessions directory: {old_dir}")
        ensure_dir(old_dir)

        with self._migration_lock, self._session_files_lock:
            for src in self.sessions_dir.glob("*.jsonl"):
                if self.session_key_from_path(src) is None:
                    continue
                source_snapshot = self._session_file_snapshot(src)
                if source_snapshot is None:
                    conflicts.append(src)
                    continue
                dst = old_dir / src.name
                if dst.exists():
                    destination_snapshot = self._session_file_snapshot(dst)
                    if (
                        destination_snapshot is not None
                        and destination_snapshot.digest == source_snapshot.digest
                    ):
                        unchanged += 1
                    else:
                        conflicts.append(dst)
                    continue
                self._install_snapshot(src, dst, source_snapshot)
                restored += 1
        return SessionRestoreResult(
            restored=restored,
            unchanged=unchanged,
            conflicts=tuple(conflicts),
        )

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

    def get_runtime_checkpoint_path(self, key: str) -> Path:
        return self.sessions_dir / f"{self.storage_key(key)}{_RUNTIME_CHECKPOINT_SUFFIX}"

    def get_legacy_lossy_path(self, key: str) -> Path:
        return self.sessions_dir / f"{safe_filename(key.replace(':', '_'))}.jsonl"

    def get_legacy_session_path(self, key: str) -> Path:
        return self.legacy_sessions_dir / f"{self.safe_key(key)}.jsonl"

    def load(self, key: str) -> Session | None:
        with self._session_files_lock:
            return self._load_unlocked(key)

    def _load_unlocked(self, key: str) -> Session | None:
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

            session = Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
                provider_state=provider_state,
            )
            self._overlay_runtime_checkpoint_unlocked(session, path)
            if _migrate_legacy_exec_session_records(session.messages, session.metadata):
                session.provider_state = None
            return session
        except _SESSION_DATA_ERRORS as e:
            logger.warning("Failed to load session {}: {}", key, e)
            repaired = self._repair_unlocked(key)
            if repaired is not None:
                logger.info(
                    "Recovered session {} from corrupt file ({} messages)",
                    key,
                    len(repaired.messages),
                )
            return repaired

    def repair(self, key: str, *, path: Path | None = None) -> Session | None:
        with self._session_files_lock:
            return self._repair_unlocked(key, path=path)

    def _repair_unlocked(self, key: str, *, path: Path | None = None) -> Session | None:
        if path is None:
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

            session = Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
                provider_state=provider_state,
            )
            self._overlay_runtime_checkpoint_unlocked(session, path)
            if _migrate_legacy_exec_session_records(session.messages, session.metadata):
                session.provider_state = None
            return session
        except _SESSION_DATA_ERRORS as e:
            logger.warning("Repair failed for session {}: {}", key, e)
            return None

    @staticmethod
    def session_payload(session: Session) -> SessionPayload:
        return {
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "messages": session.messages,
        }

    def save(self, session: Session, *, fsync: bool = False) -> None:
        with self._session_files_lock:
            self._save_unlocked(session, fsync=fsync)

    def save_runtime_checkpoint(self, session: Session) -> None:
        """Atomically persist only the volatile in-flight turn state.

        A checkpoint is written several times during a tool-heavy turn. Keeping it
        beside the append history avoids copying the full transcript at each safe
        recovery boundary.
        """
        with self._session_files_lock:
            path = self.get_session_path(session.key)
            if not path.exists():
                # A user turn normally creates the session first. Internal callers
                # may checkpoint a fresh session, so establish the durable base once.
                self._save_unlocked(session)
                return

            checkpoint = session.metadata.get(_RUNTIME_CHECKPOINT_KEY)
            if not isinstance(checkpoint, dict):
                self.get_runtime_checkpoint_path(session.key).unlink(missing_ok=True)
                return

            payload: dict[str, Any] = {
                "version": _RUNTIME_CHECKPOINT_VERSION,
                "session_key": session.key,
                "base_updated_at": session.updated_at.isoformat(),
                "base_message_count": len(session.messages),
                "checkpoint": checkpoint,
                "provider_state": (
                    session.provider_state.to_private_record()
                    if session.provider_state is not None
                    else None
                ),
            }
            target = self.get_runtime_checkpoint_path(session.key)
            tmp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
            try:
                with open(tmp, "x", encoding="utf-8") as handle:
                    os.chmod(tmp, 0o600)
                    json.dump(
                        payload,
                        handle,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                os.replace(tmp, target)
            finally:
                tmp.unlink(missing_ok=True)

    def _overlay_runtime_checkpoint_unlocked(self, session: Session, main_path: Path) -> None:
        checkpoint_path = self.get_runtime_checkpoint_path(session.key)
        try:
            checkpoint_stat = checkpoint_path.lstat()
            if not stat.S_ISREG(checkpoint_stat.st_mode):
                logger.warning(
                    "Ignoring non-regular runtime checkpoint for session {}",
                    session.key,
                )
                return
            # A complete session save supersedes an older sidecar. This comparison
            # closes the small crash window between replacing the JSONL and unlinking
            # its previous checkpoint.
            if main_path.stat().st_mtime_ns > checkpoint_stat.st_mtime_ns:
                checkpoint_path.unlink(missing_ok=True)
                return
            raw = _json_object(json.loads(checkpoint_path.read_text(encoding="utf-8")))
            if (
                raw.get("version") != _RUNTIME_CHECKPOINT_VERSION
                or raw.get("session_key") != session.key
                or raw.get("base_updated_at") != session.updated_at.isoformat()
                or raw.get("base_message_count") != len(session.messages)
                or not isinstance(raw.get("checkpoint"), dict)
            ):
                checkpoint_path.unlink(missing_ok=True)
                return
            provider_record = raw.get("provider_state")
            provider_state = (
                None
                if provider_record is None
                else ProviderConversationState.from_private_record(provider_record)
            )
            if provider_record is not None and provider_state is None:
                raise ValueError("invalid checkpoint provider state")
            session.metadata[_RUNTIME_CHECKPOINT_KEY] = cast(
                dict[str, Any], raw["checkpoint"]
            )
            session.provider_state = provider_state
        except FileNotFoundError:
            return
        except _RUNTIME_CHECKPOINT_DATA_ERRORS as exc:
            logger.warning(
                "Ignoring invalid runtime checkpoint for session {}: {}",
                session.key,
                exc,
            )
            # Atomic writes mean a malformed target cannot become valid later.
            # Remove it once so future loads do not repeatedly parse and log it.
            with suppress(OSError):
                if checkpoint_path.is_file() and not checkpoint_path.is_symlink():
                    checkpoint_path.unlink()

    def _save_unlocked(self, session: Session, *, fsync: bool = False) -> None:
        path = self.get_session_path(session.key)
        tmp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")

        try:
            with open(tmp_path, "x", encoding="utf-8") as f:
                metadata_line = {
                    "_type": "metadata",
                    "key": session.key,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "metadata": session.metadata,
                    "last_consolidated": session.last_consolidated,
                }
                f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
                if session.provider_state is not None:
                    provider_state_line = {
                        "_type": _PROVIDER_STATE_RECORD_TYPE,
                        "state": session.provider_state.to_private_record(),
                    }
                    f.write(json.dumps(provider_state_line, ensure_ascii=False) + "\n")
                for msg in session.messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                if fsync:
                    f.flush()
                    os.fsync(f.fileno())

            os.replace(tmp_path, path)

            # The full record now contains the authoritative checkpoint state (or
            # its removal), so an older volatile overlay is no longer needed.
            self.get_runtime_checkpoint_path(session.key).unlink(missing_ok=True)

            if fsync:
                with suppress(PermissionError):
                    fd = os.open(str(path.parent), os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    except OSError as exc:
                        if exc.errno != errno.EINVAL:
                            raise
                    finally:
                        os.close(fd)
        finally:
            tmp_path.unlink(missing_ok=True)

    def update_metadata(
        self,
        key: str,
        updates: dict[str, Any],
        *,
        fsync: bool = False,
    ) -> bool:
        """Atomically replace only a session file's metadata record."""
        with self._session_files_lock:
            path = self.get_session_path(key)
            if not path.exists():
                return False
            tmp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
            try:
                with open(path, encoding="utf-8") as source:
                    first_line = source.readline()
                    data = _json_object(json.loads(first_line))
                    if data.get("_type") != "metadata":
                        return False
                    raw_metadata = cast(object, data.get("metadata", {}))
                    metadata = (
                        dict(cast(dict[str, Any], raw_metadata))
                        if isinstance(raw_metadata, dict)
                        else {}
                    )
                    metadata.update(deepcopy(updates))
                    data["metadata"] = metadata
                    with open(tmp_path, "x", encoding="utf-8") as target:
                        target.write(json.dumps(data, ensure_ascii=False) + "\n")
                        shutil.copyfileobj(source, target)
                        if fsync:
                            target.flush()
                            os.fsync(target.fileno())
                os.replace(tmp_path, path)
                if fsync:
                    self._fsync_directory(path.parent)
                return True
            except _SESSION_DATA_ERRORS as exc:
                logger.warning("Failed to update session metadata {}: {}", key, exc)
                return False
            finally:
                tmp_path.unlink(missing_ok=True)

    def delete(self, key: str) -> bool:
        with self._session_files_lock:
            return self._delete_unlocked(key)

    def _delete_unlocked(self, key: str) -> bool:
        paths = [
            self.get_session_path(key),
            self.get_runtime_checkpoint_path(key),
            self.get_legacy_lossy_path(key),
            self.get_legacy_session_path(key),
        ]
        deleted = False
        for path in paths:
            if not path.exists():
                continue
            try:
                path.unlink()
                deleted = True
            except OSError as e:
                logger.warning("Failed to delete session file {}: {}", path, e)
        return deleted

    def read(self, key: str) -> SessionPayload | None:
        with self._session_files_lock:
            return self._read_unlocked(key)

    def _read_unlocked(self, key: str) -> SessionPayload | None:
        path = self.get_session_path(key)
        if not path.exists():
            return None
        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: str | None = None
            updated_at: str | None = None
            stored_key: str | None = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    raw_data: object = json.loads(line)
                    data = _json_object(raw_data)
                    record_type = data.get("_type")
                    if record_type == "metadata":
                        metadata_value = cast(object, data.get("metadata", {}))
                        metadata = (
                            cast(dict[str, Any], metadata_value)
                            if isinstance(metadata_value, dict)
                            else {}
                        )
                        created_at_value = cast(object, data.get("created_at"))
                        updated_at_value = cast(object, data.get("updated_at"))
                        stored_key_value = cast(object, data.get("key"))
                        created_at = (
                            created_at_value if isinstance(created_at_value, str) else None
                        )
                        updated_at = (
                            updated_at_value if isinstance(updated_at_value, str) else None
                        )
                        stored_key = (
                            stored_key_value if isinstance(stored_key_value, str) else None
                        )
                    elif record_type == _PROVIDER_STATE_RECORD_TYPE:
                        continue
                    else:
                        messages.append(data)
            _migrate_legacy_exec_session_records(messages, metadata)
            return {
                "key": stored_key or key,
                "created_at": created_at,
                "updated_at": updated_at,
                "metadata": metadata,
                "messages": messages,
            }
        except _SESSION_DATA_ERRORS as e:
            logger.warning("Failed to read session {}: {}", key, e)
            repaired = self._repair_unlocked(key, path=path)
            if repaired is not None:
                logger.info("Recovered read-only session view {} from corrupt file", key)
                return self.session_payload(repaired)
            return None

    def read_metadata(self, key: str) -> SessionMetadataPayload | None:
        with self._session_files_lock:
            return self._read_metadata_unlocked(key)

    def _read_metadata_unlocked(self, key: str) -> SessionMetadataPayload | None:
        path = self.get_session_path(key)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    raw_data: object = json.loads(line)
                    data = _json_object(raw_data)
                    if data.get("_type") != "metadata":
                        return None
                    metadata_value = cast(object, data.get("metadata", {}))
                    key_value = cast(object, data.get("key"))
                    created_at_value = cast(object, data.get("created_at"))
                    updated_at_value = cast(object, data.get("updated_at"))
                    return {
                        "key": key_value if isinstance(key_value, str) and key_value else key,
                        "created_at": (
                            created_at_value if isinstance(created_at_value, str) else None
                        ),
                        "updated_at": (
                            updated_at_value if isinstance(updated_at_value, str) else None
                        ),
                        "metadata": (
                            cast(dict[str, Any], metadata_value)
                            if isinstance(metadata_value, dict)
                            else {}
                        ),
                    }
            return None
        except _SESSION_DATA_ERRORS as e:
            logger.warning("Failed to read session metadata {}: {}", key, e)
            repaired = self._repair_unlocked(key, path=path)
            if repaired is not None:
                logger.info("Recovered read-only session metadata {} from corrupt file", key)
                return {
                    "key": repaired.key,
                    "created_at": repaired.created_at.isoformat(),
                    "updated_at": repaired.updated_at.isoformat(),
                    "metadata": repaired.metadata,
                }
            return None

    def list_sessions(self) -> list[SessionInfo]:
        with self._session_files_lock:
            return self._list_sessions_unlocked()

    def _list_sessions_unlocked(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []

        for path in self.sessions_dir.glob("*.jsonl"):
            storage_key = self.session_key_from_path(path)
            if storage_key is None:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        raw_data: object = json.loads(first_line)
                        data = _json_object(raw_data)
                        if data.get("_type") == "metadata":
                            key_value = cast(object, data.get("key"))
                            key = (
                                key_value
                                if isinstance(key_value, str) and key_value
                                else storage_key
                            )
                            metadata = cast(object, data.get("metadata", {}))
                            title = _metadata_title(metadata)
                            preview = ""
                            fallback_preview = ""
                            scanned_records = 0
                            scanned_chars = 0
                            for line in f:
                                if not line.strip():
                                    continue
                                if _is_provider_state_record_line(line):
                                    continue
                                scanned_records += 1
                                scanned_chars += len(line)
                                if (
                                    scanned_records > _SESSION_LIST_PREVIEW_MAX_RECORDS
                                    or scanned_chars > _SESSION_LIST_PREVIEW_MAX_CHARS
                                ):
                                    break
                                raw_item: object = json.loads(line)
                                item = _json_object(raw_item)
                                if item.get("_type") in {
                                    "metadata",
                                    _PROVIDER_STATE_RECORD_TYPE,
                                }:
                                    continue
                                text = _message_preview_text(item)
                                if not text:
                                    continue
                                if item.get("role") == "user":
                                    preview = text
                                    break
                                if not fallback_preview and item.get("role") == "assistant":
                                    fallback_preview = text
                            preview = preview or fallback_preview
                            fallback_time = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
                            created_at = cast(object, data.get("created_at"))
                            updated_at = cast(object, data.get("updated_at"))
                            sessions.append(
                                {
                                    "key": key,
                                    "created_at": (
                                        created_at
                                        if isinstance(created_at, str) and created_at
                                        else fallback_time
                                    ),
                                    "updated_at": (
                                        updated_at
                                        if isinstance(updated_at, str) and updated_at
                                        else fallback_time
                                    ),
                                    "title": title,
                                    "preview": preview,
                                    "path": str(path),
                                }
                            )
            except FileNotFoundError:
                continue
            except _SESSION_DATA_ERRORS:
                repaired = self._repair_unlocked(storage_key, path=path)
                if repaired is not None:
                    sessions.append(
                        {
                            "key": repaired.key,
                            "created_at": repaired.created_at.isoformat(),
                            "updated_at": repaired.updated_at.isoformat(),
                            "title": _metadata_title(repaired.metadata),
                            "preview": next(
                                (
                                    text
                                    for msg in repaired.messages
                                    if (text := _message_preview_text(msg))
                                ),
                                "",
                            ),
                            "path": str(path),
                        }
                    )
                continue
        return sorted(sessions, key=lambda item: item["updated_at"], reverse=True)


class SessionManager:
    """Manage session identity, caching, retention, and persistence."""

    def __init__(
        self,
        workspace: Path,
        *,
        store: SessionStore | None = None,
        sessions_root: Path | None = None,
    ):
        self.workspace = workspace
        self._jsonl_store = JsonlSessionStore(workspace, sessions_root=sessions_root)
        self._store: SessionStore = store if store is not None else self._jsonl_store
        self.sessions_dir = self._jsonl_store.sessions_dir
        self.legacy_sessions_dir = self._jsonl_store.legacy_sessions_dir
        self._cache: OrderedDict[str, Session] = OrderedDict()
        # Preserve identity for sessions held by active callers without retaining idle ones.
        self._overflow_cache: WeakValueDictionary[str, Session] = WeakValueDictionary()
        self._max_cached_sessions = SESSION_CACHE_MAX_SIZE
        self._delete_observer: Callable[[str], None] | None = None

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

    def set_delete_observer(self, observer: Callable[[str], None]) -> None:
        """Observe explicit session deletion for process-local state cleanup."""
        self._delete_observer = observer

    @staticmethod
    def safe_key(key: str) -> str:
        """Public helper used by HTTP handlers to map an arbitrary key to a stable filename stem."""
        return JsonlSessionStore.safe_key(key)

    @staticmethod
    def _storage_key(key: str) -> str:
        """Collision-resistant encoding for internal session storage filenames."""
        return JsonlSessionStore.storage_key(key)

    @staticmethod
    def _decode_storage_key(stem: str) -> str | None:
        """Reverse _storage_key(): decode a base64url (no-padding) stem back to the original key."""
        return JsonlSessionStore.decode_storage_key(stem)

    @staticmethod
    def decode_storage_key(stem: str) -> str | None:
        """Public decoder for components that inspect canonical session filenames."""
        return SessionManager._decode_storage_key(stem)

    @classmethod
    def _session_key_from_path(cls, path: Path) -> str | None:
        """Decode a session key only from a canonical collision-resistant filename."""
        return JsonlSessionStore.session_key_from_path(path)

    def _get_session_path(self, key: str) -> Path:
        """Get the collision-resistant workspace path for a session."""
        return self._jsonl_store.get_session_path(key)

    def _get_runtime_checkpoint_path(self, key: str) -> Path:
        """Get the private in-flight checkpoint path for a session."""
        return self._jsonl_store.get_runtime_checkpoint_path(key)

    def _get_legacy_lossy_path(self, key: str) -> Path:
        """Previous workspace session path using lossy ':' to '_' replacement."""
        return self._jsonl_store.get_legacy_lossy_path(key)

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.nanobot/sessions/)."""
        return self._jsonl_store.get_legacy_session_path(key)

    @contextmanager
    def locked_session_files(self) -> Generator[Path, None, None]:
        """Guard exceptional direct access to canonical JSONL files."""
        with self._jsonl_store.locked_session_files() as sessions_dir:
            yield sessions_dir

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

    def get_or_create_transient(
        self,
        key: str,
        *,
        disabled_tools: Collection[str] = (),
    ) -> Session:
        """Return a fresh, non-persistent session without loading history."""
        policy = SessionPolicy(
            persist=False,
            log_content=False,
            disabled_tools=frozenset(disabled_tools),
        )
        session = self.get_cached(key)
        if session is None or session.policy != policy:
            session = Session(key=key, policy=policy)
            self._remember(session)
        return session

    def _load(self, key: str) -> Session | None:
        return self._store.load(key)

    def _repair(self, key: str, *, path: Path | None = None) -> Session | None:
        """Attempt to recover a session from a corrupt JSONL file."""
        return self._jsonl_store.repair(key, path=path)

    def save(self, session: Session, *, fsync: bool = False) -> None:
        """Persist a session and retain it in the cache."""
        if not session.policy.persist:
            return

        self._store.save(session, fsync=fsync)
        self._remember(session)

    def save_runtime_checkpoint(self, session: Session) -> None:
        """Persist volatile recovery state without rewriting long history."""
        if not session.policy.persist:
            return
        if self._store is self._jsonl_store:
            self._jsonl_store.save_runtime_checkpoint(session)
            self._remember(session)
            return
        # Third-party stores keep their existing all-or-nothing semantics until
        # they opt into a dedicated checkpoint primitive.
        self.save(session)

    def rename_model_preset(self, old_name: str, new_name: str) -> int:
        """Rename a session-scoped model preset across durable and live sessions."""
        if old_name == new_name:
            return 0

        cached = dict(self._overflow_cache.items())
        cached.update(self._cache)
        keys = set(cached)
        keys.update(item["key"] for item in self._store.list_sessions())

        changed: list[Session] = []
        try:
            for key in sorted(keys):
                session = cached.get(key) or self._load(key)
                if (
                    session is None
                    or session.metadata.get(SESSION_MODEL_PRESET_METADATA_KEY) != old_name
                ):
                    continue
                session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = new_name
                changed.append(session)
                if session.policy.persist:
                    self.save(session, fsync=True)
                else:
                    self._remember(session)
        except BaseException:
            for session in reversed(changed):
                session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = old_name
                try:
                    if session.policy.persist:
                        self.save(session, fsync=True)
                    else:
                        self._remember(session)
                except Exception:
                    logger.exception(
                        "Failed to roll back model preset rename for session {}",
                        session.key,
                    )
            raise
        return len(changed)

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
        deleted = self._store.delete(key)
        if self._delete_observer is not None:
            self._delete_observer(key)
        return deleted

    def restore_sessions_to_workspace(self) -> SessionRestoreResult:
        """Restore session files to the pre-relocation path for an explicit rollback."""
        return self._jsonl_store.restore_to_workspace()

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
        *,
        fsync: bool = False,
    ) -> bool:
        """Atomically update metadata without replacing session history."""
        updated = self._store.update_metadata(key, updates, fsync=fsync)
        if updated and (session := self.get_cached(key)) is not None:
            session.metadata.update(deepcopy(updates))
        return updated

    def list_sessions(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._store.list_sessions())
