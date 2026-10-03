"""Runtime group reply policy overrides (``/group`` command).

``nanobot.group_policy`` stores overrides created from chat so an operator can
silence a single busy topic without editing ``config.json`` and restarting.
Runtime overrides take precedence over the static
``channels.<channel>.groupPolicyOverrides`` config, and a topic scope wins over
its parent chat.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.group_policy import (
    clear_policy,
    list_policies,
    resolve_policy,
    set_policy,
)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.group_policy.store.get_data_dir", lambda: tmp_path)


def _resolve(
    chat_id: str = "-100",
    *,
    thread_id: object | None = None,
    static: dict[str, str] | None = None,
    default: str = "open",
) -> str:
    return resolve_policy(
        "telegram",
        chat_id,
        thread_id=thread_id,
        static_overrides=static,
        default_policy=default,
    )


def test_default_policy_used_when_nothing_is_set() -> None:
    assert _resolve(default="mention") == "mention"
    assert _resolve(default="open") == "open"


def test_static_chat_override_applies() -> None:
    assert _resolve(static={"-100": "mention"}) == "mention"


def test_static_topic_override_wins_over_static_chat() -> None:
    static = {"-100": "open", "-100:7819": "mention"}
    assert _resolve(static=static, thread_id=7819) == "mention"
    assert _resolve(static=static, thread_id=7818) == "open"


def test_runtime_override_wins_over_static_config() -> None:
    set_policy("telegram", "-100", "mention")
    assert _resolve(static={"-100": "open"}) == "mention"


def test_runtime_topic_override_wins_over_runtime_chat() -> None:
    set_policy("telegram", "-100", "open")
    set_policy("telegram", "-100", "mention", thread_id=7819)

    assert _resolve(thread_id=7819) == "mention"
    # A sibling topic keeps the chat-level runtime override.
    assert _resolve(thread_id=7818) == "open"


def test_runtime_topic_override_does_not_leak_across_chats() -> None:
    set_policy("telegram", "-100", "mention", thread_id=7819)
    assert _resolve(chat_id="-200", thread_id=7819, default="open") == "open"


def test_runtime_override_does_not_leak_across_channels() -> None:
    set_policy("telegram", "-100", "mention")
    assert (
        resolve_policy(
            "discord",
            "-100",
            thread_id=None,
            static_overrides=None,
            default_policy="open",
        )
        == "open"
    )


def test_clear_policy_removes_override() -> None:
    set_policy("telegram", "-100", "mention")
    assert _resolve() == "mention"

    assert clear_policy("telegram", "-100") is True
    assert _resolve(default="open") == "open"


def test_clear_policy_reports_when_nothing_was_set() -> None:
    assert clear_policy("telegram", "-100") is False


def test_clear_topic_keeps_chat_override() -> None:
    set_policy("telegram", "-100", "open")
    set_policy("telegram", "-100", "mention", thread_id=7819)

    assert clear_policy("telegram", "-100", thread_id=7819) is True
    assert _resolve(thread_id=7819) == "open"


def test_unsupported_policy_is_rejected() -> None:
    with pytest.raises(ValueError):
        set_policy("telegram", "-100", "sometimes")


def test_list_policies_filters_by_channel() -> None:
    set_policy("telegram", "-100", "mention")
    set_policy("telegram", "-100", "open", thread_id=7819)
    set_policy("discord", "-300", "mention")

    telegram = list_policies("telegram")
    assert telegram == [
        ("telegram:-100", "mention"),
        ("telegram:-100:7819", "open"),
    ]
    assert ("discord:-300", "mention") in list_policies()


def test_overrides_persist_across_calls() -> None:
    set_policy("telegram", "-100", "mention", thread_id=7819)
    # A fresh resolve reads from disk rather than any in-memory cache.
    assert _resolve(thread_id=7819, default="open") == "mention"
