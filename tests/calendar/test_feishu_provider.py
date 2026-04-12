"""Tests for Feishu calendar provider internals."""

from __future__ import annotations

from types import SimpleNamespace

from nanobot.calendar.providers import FeishuCalendarProvider


def test_feishu_refresh_preserves_identity_fields(monkeypatch) -> None:
    provider = FeishuCalendarProvider(app_id="app", app_secret="sec")
    provider._token_cache = {  # noqa: SLF001
        "access_token": "old_access",
        "refresh_token": "old_refresh",
        "open_id": "ou_xxx",
        "user_id": "u_xxx",
    }
    saved: dict[str, object] = {}

    class _FakeRefreshAPI:
        @staticmethod
        def create(request):  # noqa: ANN001
            _ = request
            return SimpleNamespace(
                success=lambda: True,
                data=SimpleNamespace(
                    access_token="new_access",
                    refresh_token="new_refresh",
                    expires_in=7200,
                    refresh_expires_in=2592000,
                ),
            )

    class _FakeClient:
        authen = SimpleNamespace(v1=SimpleNamespace(refresh_access_token=_FakeRefreshAPI()))

    monkeypatch.setattr(provider, "_build_lark_client", lambda: _FakeClient())
    monkeypatch.setattr(provider, "_save_token", lambda token: saved.update(token))

    refreshed = provider._do_refresh("old_refresh")  # noqa: SLF001

    assert refreshed["open_id"] == "ou_xxx"
    assert refreshed["user_id"] == "u_xxx"
    assert saved["open_id"] == "ou_xxx"
    assert saved["user_id"] == "u_xxx"
