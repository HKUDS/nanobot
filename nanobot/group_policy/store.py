"""Per-scope group reply policy overrides set from chat.

``config.json`` already carries ``channels.<channel>.groupPolicyOverrides`` as
the static source of truth. This store holds the *runtime* overrides created
with the in-chat ``/group`` command, so an operator can silence a busy topic
without editing config and restarting.

Persistent storage at ``<data_dir>/group_policy.json``. Scope keys are
``"<channel>:<chat_id>"`` or ``"<channel>:<chat_id>:<thread_id>"``; the channel
is part of the key so Telegram and Discord overrides cannot collide.

Resolution order, most specific first:

1. runtime topic override (this store)
2. runtime chat override (this store)
3. static topic override (``config.json``)
4. static chat override (``config.json``)
5. channel-wide ``groupPolicy``

The store is intentionally small and mirrors ``nanobot.pairing.store``: a JSON
file, a process lock, atomic writes, and no external database.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]

# Mirrors the group policy values channels accept. Kept as plain strings so the
# store does not import any channel package.
POLICIES = ("mention", "open")

_LOCK = threading.Lock()


def _store_path() -> Path:
    return get_data_dir() / "group_policy.json"


def _scope_key(channel: str, chat_id: str, thread_id: Any | None = None) -> str:
    """Build a scope key: ``channel:chat`` or ``channel:chat:thread``."""
    base = f"{channel}:{chat_id}"
    if thread_id is None or str(thread_id) == "":
        return base
    return f"{base}:{thread_id}"


def _load() -> dict[str, str]:
    path = _store_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logger.warning("Corrupted group policy store, resetting")
        return {}
    except OSError:
        # A transiently busy file is not corruption. Propagate so mutating
        # callers fail loudly instead of persisting an empty view that would
        # erase every override.
        logger.warning("Group policy store temporarily unreadable: {}", path)
        raise
    if not isinstance(data, dict):
        logger.warning("Corrupted group policy store, resetting")
        return {}
    overrides = data.get("overrides")
    if not isinstance(overrides, dict):
        return {}
    return {
        str(scope): str(policy)
        for scope, policy in cast(dict[str, Any], overrides).items()
        if str(policy) in POLICIES
    }


def _save(overrides: dict[str, str]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"overrides": dict(sorted(overrides.items()))}
    _write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False))


def resolve_policy(
    channel: str,
    chat_id: str,
    *,
    thread_id: Any | None,
    static_overrides: dict[str, str] | None,
    default_policy: str,
) -> str:
    """Resolve the effective policy for one scope.

    Runtime overrides win over static config, and a topic scope wins over its
    parent chat. Falls back to ``default_policy`` when nothing matches.
    """
    topic_scope = _scope_key(channel, chat_id, thread_id)
    chat_scope = _scope_key(channel, chat_id)
    runtime = _load()

    if thread_id is not None and str(thread_id) != "":
        runtime_topic = runtime.get(topic_scope)
        if runtime_topic is not None:
            return runtime_topic

    runtime_chat = runtime.get(chat_scope)
    if runtime_chat is not None:
        return runtime_chat

    if static_overrides:
        if thread_id is not None and str(thread_id) != "":
            raw_topic = static_overrides.get(f"{chat_id}:{thread_id}")
            if raw_topic is not None:
                return str(raw_topic)
        raw_chat = static_overrides.get(str(chat_id))
        if raw_chat is not None:
            return str(raw_chat)

    return default_policy


def set_policy(
    channel: str,
    chat_id: str,
    policy: str,
    *,
    thread_id: Any | None = None,
) -> str:
    """Persist an override and return the scope key it was stored under."""
    if policy not in POLICIES:
        raise ValueError(f"unsupported policy: {policy}")
    scope = _scope_key(channel, chat_id, thread_id)
    with _LOCK:
        overrides = _load()
        overrides[scope] = policy
        _save(overrides)
    return scope


def clear_policy(
    channel: str,
    chat_id: str,
    *,
    thread_id: Any | None = None,
) -> bool:
    """Remove one override. Returns ``True`` when something was removed."""
    scope = _scope_key(channel, chat_id, thread_id)
    with _LOCK:
        overrides = _load()
        if scope not in overrides:
            return False
        del overrides[scope]
        _save(overrides)
    return True


def list_policies(channel: str | None = None) -> list[tuple[str, str]]:
    """Return ``(scope, policy)`` pairs, optionally filtered by channel."""
    items = sorted(_load().items())
    if channel is None:
        return items
    prefix = f"{channel}:"
    return [(scope, policy) for scope, policy in items if scope.startswith(prefix)]
