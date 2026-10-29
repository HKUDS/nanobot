"""Pure restart intent and process handoff, plus slash-command notices.

Entrypoints inject ``RestartController.request`` into their agent and transports.
Delivery adapters commit the returned ticket only after writing/draining the reply.
The owner then performs its normal cleanup and raises ``ProcessRestart``. Catch it
outside all installation/data leases and call ``execute()`` there; it is deliberately
not an Exception so application error handlers cannot swallow a lifecycle handoff.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast

RESTART_NOTIFY_CHANNEL_ENV = "NANOBOT_RESTART_NOTIFY_CHANNEL"
RESTART_NOTIFY_CHAT_ID_ENV = "NANOBOT_RESTART_NOTIFY_CHAT_ID"
RESTART_NOTIFY_METADATA_ENV = "NANOBOT_RESTART_NOTIFY_METADATA"
RESTART_STARTED_AT_ENV = "NANOBOT_RESTART_STARTED_AT"

RestartMode = Literal["auto", "exec", "spawn", "exit"]


@dataclass(frozen=True)
class RestartTicket:
    """One accepted intent; delivery adapters commit after acknowledgement."""

    commit: Callable[[], None]


class RestartRequest(Protocol):
    def __call__(self) -> RestartTicket | None:
        """Accept one intent, or return None when shutdown/restart is pending."""
        ...


class RestartController:
    """Coordinate one restart with the application's normal shutdown path."""

    def __init__(self) -> None:
        self.shutdown_event = asyncio.Event()
        self.committed = False
        self._accepted = False

    def request(self) -> RestartTicket | None:
        if self._accepted or self.shutdown_event.is_set():
            return None
        self._accepted = True
        return RestartTicket(commit=self._commit)

    def _commit(self) -> None:
        if self.shutdown_event.is_set():
            return
        self.committed = True
        self.shutdown_event.set()


class ProcessRestart(BaseException):
    """Unwind the entrypoint's leases before executing a replacement process."""

    def __init__(self, execute: Callable[[], None]) -> None:
        super().__init__("process restart requested")
        self.execute = execute


def resolve_restart_mode(mode: RestartMode) -> Literal["exec", "spawn", "exit"]:
    if mode == "auto":
        return "spawn" if sys.platform == "win32" else "exec"
    return mode


def replace_process(
    argv: Sequence[str], *, mode: RestartMode, cwd: Path,
    env: Mapping[str, str] | None = None,
) -> None:
    """Run only after cleanup/lease release; spawn and exit return to the entrypoint."""
    resolved = resolve_restart_mode(mode)
    if resolved == "exit":
        return
    environment = dict(os.environ if env is None else env)
    if resolved == "exec":
        os.chdir(cwd)
        os.execve(argv[0], list(argv), environment)
        return
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(list(argv), cwd=cwd, env=environment, **kwargs)


def standalone_restart(*, mode: RestartMode, args: Sequence[str]) -> ProcessRestart:
    """Capture a classic CLI restart; its owner raises this after cleanup.

    The standalone entry supplies its launch selectors and ``agent --classic``,
    excluding one-shot ``--message`` input. Never replay update-worker argv here;
    the gateway has its own canonical launch plan.
    """
    argv = [sys.executable, "-m", "nanobot", *args]
    cwd = Path.cwd()
    return ProcessRestart(lambda: replace_process(argv, mode=mode, cwd=cwd))


@dataclass(frozen=True)
class RestartNotice:
    channel: str
    chat_id: str
    started_at_raw: str
    metadata: dict[str, Any] = field(default_factory=dict)


def format_restart_completed_message(started_at_raw: str) -> str:
    """Build restart completion text and include elapsed time when available."""
    elapsed_suffix = ""
    if started_at_raw:
        with suppress(ValueError):
            elapsed_s = max(0.0, time.time() - float(started_at_raw))
            elapsed_suffix = f" in {elapsed_s:.1f}s"
    return f"Restart completed{elapsed_suffix}."


def set_restart_notice_to_env(
    *, channel: str, chat_id: str, metadata: dict[str, Any] | None = None,
) -> None:
    """Write restart notice env values for the next process."""
    from nanobot.bus.events import INBOUND_META_TURN_ID

    os.environ[RESTART_NOTIFY_CHANNEL_ENV] = channel
    os.environ[RESTART_NOTIFY_CHAT_ID_ENV] = chat_id
    os.environ[RESTART_STARTED_AT_ENV] = str(time.time())
    persisted_metadata = dict(metadata or {})
    persisted_metadata.pop(INBOUND_META_TURN_ID, None)
    if persisted_metadata:
        try:
            os.environ[RESTART_NOTIFY_METADATA_ENV] = json.dumps(
                persisted_metadata,
                default=str,
            )
        except (TypeError, ValueError):
            os.environ.pop(RESTART_NOTIFY_METADATA_ENV, None)
    else:
        os.environ.pop(RESTART_NOTIFY_METADATA_ENV, None)


def consume_restart_notice_from_env() -> RestartNotice | None:
    """Read and clear restart notice env values once for this process."""
    channel = os.environ.pop(RESTART_NOTIFY_CHANNEL_ENV, "").strip()
    chat_id = os.environ.pop(RESTART_NOTIFY_CHAT_ID_ENV, "").strip()
    started_at_raw = os.environ.pop(RESTART_STARTED_AT_ENV, "").strip()
    metadata_raw = os.environ.pop(RESTART_NOTIFY_METADATA_ENV, "").strip()
    if not (channel and chat_id):
        return None
    metadata: dict[str, Any] = {}
    if metadata_raw:
        try:
            parsed = json.loads(metadata_raw)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            metadata = cast(dict[str, Any], parsed)
    return RestartNotice(
        channel=channel,
        chat_id=chat_id,
        started_at_raw=started_at_raw,
        metadata=metadata,
    )


def should_show_cli_restart_notice(notice: RestartNotice, session_id: str) -> bool:
    """Return True when a restart notice should be shown in this CLI session."""
    if notice.channel != "cli":
        return False
    if ":" in session_id:
        _, cli_chat_id = session_id.split(":", 1)
    else:
        cli_chat_id = session_id
    return not notice.chat_id or notice.chat_id == cli_chat_id
