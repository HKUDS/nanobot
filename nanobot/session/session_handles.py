"""Stable public handles derived from persisted session keys."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, TypedDict

from nanobot.session.manager import SessionManager

_MAX_SESSION_KEY_CHARS = 512
_HANDLE_RE = re.compile(r"^[a-z]{2,16}-[0-9a-f]{10}$")

_HANDLE_NAMES = tuple(
    """
    ada abel adil aiko alba alex alia alma amir amos anil anja arlo asha ava bea
    ben blair bruno cara carl cato celia chen chloe clara cleo cora dahlia daisy
    dana dante dara dario dev dina drew eden eira eli elio ella elsa emil emma
    enzo eric esme eva farah felix finn flora freya gabe gia gwen hana harper
    hazel heidi hugo ida ila iman ines iris ivan jade jamie joel jona jude jules
    juno kai ken kira lana lara leif lena leo lia liam lila lina liv lois lola
    luca lucy mabel mae malik mara marco maya mila mina mira nadia nate neve nico
    nina noah nora omar oren orla otto owen pablo piper priya quinn rafi remy ren
    rhea rio robin rosa ruby sage sami sara sena shay silas sofia sol sora tariq
    tavi tess theo timo uma val vera vida wes will wren xena yara yasmin yuki zara
    zeno zoe
    """.split()
)


class SessionHandlePayload(TypedDict):
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class SessionHandle:
    """Public identity plus the private key used for internal routing."""

    id: str
    name: str
    session_key: str

    def public_payload(self) -> SessionHandlePayload:
        return {"id": self.id, "name": self.name}


def normalize_session_handle(value: str) -> str:
    """Return the canonical bare handle accepted at model and UI boundaries."""
    name = value.strip().removeprefix("@").casefold()
    if _HANDLE_RE.fullmatch(name) is None:
        raise ValueError("session handle is invalid")
    return name


def session_handle_for_key(session_key: str) -> SessionHandle:
    """Derive a stable handle without creating a second persistence lifecycle."""
    key = session_key.strip()
    if not key or len(key) > _MAX_SESSION_KEY_CHARS:
        raise ValueError("session key is invalid")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    word = _HANDLE_NAMES[int(digest[:8], 16) % len(_HANDLE_NAMES)]
    return SessionHandle(
        id=f"handle_{digest[:32]}",
        name=f"{word}-{digest[32:42]}",
        session_key=key,
    )


class SessionHandleResolver:
    """Resolve derived handles against the current persisted-session list."""

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions

    def list_all(self) -> list[SessionHandle]:
        handles: list[SessionHandle] = []
        for row in self._sessions.list_sessions():
            raw_key: Any = row.get("key")
            if not isinstance(raw_key, str):
                continue
            try:
                handles.append(session_handle_for_key(raw_key))
            except ValueError:
                continue
        return sorted(handles, key=lambda handle: handle.name)

    def resolve(self, name: str) -> SessionHandle | None:
        try:
            normalized = normalize_session_handle(name)
        except ValueError:
            return None
        matches = [handle for handle in self.list_all() if handle.name == normalized]
        return matches[0] if len(matches) == 1 else None
