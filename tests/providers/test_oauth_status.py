from __future__ import annotations

import time
from types import SimpleNamespace

from nanobot.providers.oauth_status import (
    DAY_MS,
    OAuthProviderStatus,
    OAuthRuntimeWarningTracker,
    format_oauth_expiry_delta,
    get_oauth_provider_status,
    oauth_expires_soon,
    oauth_expiry_warning,
)
from nanobot.providers.registry import find_by_name


def test_openai_codex_status_accepts_refreshable_expired_token(monkeypatch) -> None:
    token = SimpleNamespace(
        access="access-token",
        refresh="refresh-token",
        expires=1,
        account_id="acct-codex",
    )
    monkeypatch.setattr("oauth_cli_kit.storage.FileTokenStorage.load", lambda _self: token)

    status = get_oauth_provider_status(find_by_name("openai_codex"))

    assert status.configured is True
    assert status.account == "acct-codex"
    assert status.expires_at == 1


def test_github_copilot_status_uses_stored_github_oauth_token(monkeypatch) -> None:
    expires_at = int(time.time() * 1000) + 10 * DAY_MS
    token = SimpleNamespace(access="github-token", expires=expires_at, account_id="octocat")
    monkeypatch.setattr(
        "nanobot.providers.github_copilot_provider.get_github_copilot_login_status",
        lambda: token,
    )

    status = get_oauth_provider_status(find_by_name("github_copilot"))

    assert status.configured is True
    assert status.account == "octocat"
    assert status.expires_at == expires_at


def test_oauth_expiry_warning_only_within_threshold() -> None:
    now_ms = 1_000_000
    spec = find_by_name("openai_codex")
    expired = OAuthProviderStatus(True, "acct", now_ms - DAY_MS, True)
    soon = OAuthProviderStatus(True, "acct", now_ms + 3 * DAY_MS, True)
    later = OAuthProviderStatus(True, "acct", now_ms + 8 * DAY_MS, True)

    assert oauth_expires_soon(expired, threshold_days=7, now_ms=now_ms) is True
    assert oauth_expires_soon(soon, threshold_days=7, now_ms=now_ms) is True
    assert oauth_expiry_warning(spec, soon, threshold_days=7, now_ms=now_ms) == (
        "OpenAI Codex OAuth token expires in 3 days. "
        "Run: nanobot provider login openai-codex"
    )
    assert oauth_expires_soon(later, threshold_days=7, now_ms=now_ms) is False
    assert oauth_expiry_warning(spec, later, threshold_days=7, now_ms=now_ms) is None


def test_format_oauth_expiry_delta_uses_hours_for_short_windows() -> None:
    assert format_oauth_expiry_delta(1) == "in 1 hour"
    assert format_oauth_expiry_delta(25 * 60 * 60 * 1000) == "in 25 hours"


def test_runtime_warning_tracker_logs_once(monkeypatch) -> None:
    expires_at = int(time.time() * 1000) + 60 * 60 * 1000

    def fake_status(spec):
        assert spec.name == "openai_codex"
        return OAuthProviderStatus(True, "acct-test", expires_at, True)

    monkeypatch.setattr("nanobot.providers.oauth_status.get_oauth_provider_status", fake_status)

    tracker = OAuthRuntimeWarningTracker()

    first = tracker.warn_for_provider("openai-codex")
    second = tracker.warn_for_provider("openai_codex")

    assert first == (
        "OpenAI Codex OAuth token expires in 1 hour. "
        "Run: nanobot provider login openai-codex"
    )
    assert second is None
