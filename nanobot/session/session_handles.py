"""Short, pronounceable public handles for persisted sessions."""

from __future__ import annotations

import hashlib
import math
import re
import secrets
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from nanobot.session.manager import SessionManager

SESSION_HANDLE_METADATA_KEY = "session_handle"

_MAX_SESSION_KEY_CHARS = 512
_MAX_HANDLE_CHARS = 16
_HANDLE_RE = re.compile(rf"^[a-z]{{4,{_MAX_HANDLE_CHARS}}}$")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
_SYLLABLES = (
    "ba", "be", "bi", "bo",
    "da", "de", "di", "do",
    "fa", "fe", "fi", "fo",
    "ga", "ge", "gi", "go",
    "ha", "he", "hi", "ho",
    "ja", "je", "ji", "jo",
    "ka", "ke", "ki", "ko", "ku",
    "la", "le", "li", "lo", "lu",
    "ma", "me", "mi", "mo", "mu",
    "na", "ne", "ni", "no", "nu",
    "pa", "pe", "pi", "po",
    "ra", "re", "ri", "ro", "ru",
    "sa", "se", "si", "so", "su",
    "ta", "te", "ti", "to", "tu",
    "va",
)
_END_SYLLABLES = (
    "la", "le", "li", "lo", "lu",
    "ma", "me", "mi", "mo", "mu",
    "na", "ne", "ni", "no", "nu",
    "ra", "re", "ri", "ro", "ru",
    "sa", "se", "si", "so", "su",
    "ta", "te", "ti", "to", "tu",
    "va", "ve", "vi", "vo", "vu",
    "ya", "ye", "yi", "yo", "yu",
)
_SYLLABLE_COUNTS = (2, 3, 4)
_BLOCKED_NAMES = frozenset({"dago", "homo", "kike", "pedo", "rape"})

assert len(_SYLLABLES) == 64
assert len(set(_SYLLABLES)) == len(_SYLLABLES)
assert len(_END_SYLLABLES) == 40
assert len(set(_END_SYLLABLES)) == len(_END_SYLLABLES)


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


def session_handle_for_name(session_key: str, name: str) -> SessionHandle:
    """Build a trusted handle from a persisted name and its private session key."""
    key = _clean_session_key(session_key)
    normalized = normalize_session_handle(name)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return SessionHandle(
        id=f"handle_{digest[:32]}",
        name=normalized,
        session_key=key,
    )


def _clean_session_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > _MAX_SESSION_KEY_CHARS:
        raise ValueError("session key is invalid")
    return key


def _tier_size(syllable_count: int) -> int:
    return len(_SYLLABLES) ** (syllable_count - 1) * len(_END_SYLLABLES)


def _name_parts_at(syllable_count: int, index: int) -> tuple[str, ...]:
    """Decode one permutation index without materializing the candidate space."""
    size = _tier_size(syllable_count)
    if not 0 <= index < size:
        raise ValueError("session handle candidate index is invalid")
    choices: list[str] = []
    index, ending = divmod(index, len(_END_SYLLABLES))
    choices.append(_END_SYLLABLES[ending])
    for _ in range(syllable_count - 1):
        index, syllable = divmod(index, len(_SYLLABLES))
        choices.append(_SYLLABLES[syllable])
    choices.reverse()
    return tuple(choices)


def _candidate_indexes(syllable_count: int):
    """Visit every candidate once in a stable, non-alphabetical order."""
    size = _tier_size(syllable_count)
    seed = hashlib.sha256(f"nanobot-handle-v1:{syllable_count}".encode()).digest()
    start = int.from_bytes(seed[:8], "big") % size
    step = int.from_bytes(seed[8:16], "big") % size or 1
    while math.gcd(step, size) != 1:
        step += 1
    for offset in range(size):
        yield (start + offset * step) % size


def _allocate_name(used: set[str]) -> str:
    for syllable_count in _SYLLABLE_COUNTS:
        for index in _candidate_indexes(syllable_count):
            parts = _name_parts_at(syllable_count, index)
            if len(set(parts)) != len(parts):
                continue
            name = "".join(parts)
            if name not in used and name not in _BLOCKED_NAMES:
                return name
    while True:
        name = "".join(secrets.choice(_ALPHABET) for _ in range(12))
        if name not in used and name not in _BLOCKED_NAMES:
            return name


class SessionHandleResolver:
    """Allocate and resolve handles stored in canonical session metadata."""

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions

    def _ensure_all(self) -> dict[str, SessionHandle]:
        with self._sessions.locked_session_files():
            rows = sorted(
                self._sessions.list_sessions(),
                key=lambda row: (
                    str(row.get("created_at", "")),
                    str(row.get("key", "")),
                ),
            )
            used: set[str] = set()
            names: dict[str, str] = {}
            pending: list[str] = []
            for row in rows:
                raw_key: Any = row.get("key")
                if not isinstance(raw_key, str):
                    continue
                payload = self._sessions.read_session_metadata(raw_key)
                raw_metadata = payload.get("metadata") if payload is not None else None
                metadata = (
                    cast(dict[str, Any], raw_metadata)
                    if isinstance(raw_metadata, dict)
                    else {}
                )
                raw_name = metadata.get(SESSION_HANDLE_METADATA_KEY)
                try:
                    name = normalize_session_handle(raw_name) if isinstance(raw_name, str) else ""
                except ValueError:
                    name = ""
                if not name or name in used:
                    pending.append(raw_key)
                    continue
                names[raw_key] = name
                used.add(name)

            for key in pending:
                name = _allocate_name(used)
                if not self._sessions.update_session_metadata(
                    key,
                    {SESSION_HANDLE_METADATA_KEY: name},
                    fsync=True,
                ):
                    continue
                names[key] = name
                used.add(name)

            return {
                key: session_handle_for_name(key, name)
                for key, name in names.items()
            }

    def handle_for_session(self, session_key: str) -> SessionHandle | None:
        try:
            key = _clean_session_key(session_key)
        except ValueError:
            return None
        return self._ensure_all().get(key)

    def list_all(self) -> list[SessionHandle]:
        return sorted(self._ensure_all().values(), key=lambda handle: handle.name)

    def list_all_by_key(self) -> dict[str, SessionHandle]:
        return self._ensure_all()

    def resolve(self, name: str) -> SessionHandle | None:
        try:
            normalized = normalize_session_handle(name)
        except ValueError:
            return None
        return next(
            (
                handle
                for handle in self._ensure_all().values()
                if handle.name == normalized
            ),
            None,
        )
