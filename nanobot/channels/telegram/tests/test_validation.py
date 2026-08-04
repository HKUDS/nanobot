from __future__ import annotations

import httpx
import pytest

from nanobot.channels.telegram import validation as telegram_validation
from nanobot.channels.telegram.manifest import SETUP_SPEC
from nanobot.channels.validation import validate_channel_config
from nanobot.config.loader import save_config
from nanobot.config.schema import Config


def test_telegram_setup_exposes_proxy_as_an_optional_secret() -> None:
    proxy = SETUP_SPEC.fields["proxy"]

    assert proxy.kind == "secret"
    assert "proxy" not in SETUP_SPEC.simple_required_fields


def test_get_me_builds_http_client_with_explicit_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    proxy = "socks5://proxy-user:proxy-pass@127.0.0.1:1080"
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"ok": True, "result": {"id": 42}}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url: str) -> FakeResponse:
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setattr(telegram_validation.httpx, "Client", FakeClient)

    result = telegram_validation._get_me(token, proxy)

    assert result["ok"] is True
    assert captured["kwargs"] == {
        "timeout": 4.0,
        "proxy": proxy,
        "trust_env": False,
    }
    assert captured["url"] == f"https://api.telegram.org/bot{token}/getMe"


def test_validate_telegram_bad_token_is_invalid(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    result = validate_channel_config("telegram", {"channels.telegram.token": "not-a-token"})

    assert result["status"] == "invalid"
    assert result["can_enable"] is False
    assert result["missing_fields"] == []


@pytest.mark.parametrize("status_code", [401, 404])
def test_validate_telegram_rejects_denied_tokens_without_exposing_them(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"telegram": {"token": token}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def raise_http_error(token_value: str, _proxy: str | None) -> dict:
        request = httpx.Request("GET", f"https://api.telegram.org/bot{token_value}/getMe")
        response = httpx.Response(status_code, request=request)
        raise httpx.HTTPStatusError("rejected", request=request, response=response)

    monkeypatch.setattr(telegram_validation, "_get_me", raise_http_error)

    result = validate_channel_config("telegram", {"channels.telegram.token": ""})

    assert result["status"] == "invalid"
    assert result["can_enable"] is False
    assert token not in str(result)
    assert any(
        f"HTTP {status_code}" in check.get("message", "") for check in result["checks"]
    )


def test_validate_telegram_keeps_transient_http_failures_retryable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"telegram": {"token": token}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def raise_http_error(token_value: str, _proxy: str | None) -> dict:
        request = httpx.Request("GET", f"https://api.telegram.org/bot{token_value}/getMe")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)

    monkeypatch.setattr(telegram_validation, "_get_me", raise_http_error)

    result = validate_channel_config("telegram", {"channels.telegram.token": ""})

    assert result["status"] == "configured"
    assert result["can_enable"] is True
    assert token not in str(result)
    assert any("HTTP 503" in check.get("message", "") for check in result["checks"])


def test_validate_telegram_marks_proxy_transport_failures_without_exposing_proxy(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    proxy = "http://proxy-user:proxy-pass@127.0.0.1:7890"
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate(
            {"channels": {"telegram": {"token": token, "proxy": proxy}}}
        ),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def raise_proxy_error(_token: str, _proxy: str | None) -> dict:
        raise httpx.ProxyError("proxy credentials rejected")

    monkeypatch.setattr(telegram_validation, "_get_me", raise_proxy_error)

    result = validate_channel_config("telegram")

    assert result["status"] == "configured"
    assert result["can_enable"] is True
    assert proxy not in str(result)
    assert any(check["id"] == "proxy_connection" for check in result["checks"])


def test_validate_telegram_uses_saved_proxy_without_exposing_it(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    proxy = "socks5://proxy-user:proxy-pass@127.0.0.1:1080"
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate(
            {"channels": {"telegram": {"token": token, "proxy": proxy}}}
        ),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    captured: dict[str, str | None] = {}

    def fake_get_me(token_value: str, proxy_value: str | None) -> dict:
        captured.update(token=token_value, proxy=proxy_value)
        return {"ok": True, "result": {"id": 42, "username": "working_bot"}}

    monkeypatch.setattr(telegram_validation, "_get_me", fake_get_me)

    result = validate_channel_config("telegram")

    assert result["status"] == "connected"
    assert captured == {"token": token, "proxy": proxy}
    assert proxy not in str(result)


def test_validate_telegram_resolves_saved_secret_env_refs_without_exposing_them(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    token_ref = "${TELEGRAM_TOKEN_TEST}"
    proxy_ref = "${TELEGRAM_PROXY_TEST}"
    proxy = "http://proxy-user:proxy-pass@127.0.0.1:7890"
    monkeypatch.setenv("TELEGRAM_TOKEN_TEST", token)
    monkeypatch.setenv("TELEGRAM_PROXY_TEST", proxy)
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate(
            {"channels": {"telegram": {"token": token_ref, "proxy": proxy_ref}}}
        ),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    captured: dict[str, str | None] = {}

    def fake_get_me(token_value: str, proxy_value: str | None) -> dict:
        captured.update(token=token_value, proxy=proxy_value)
        return {"ok": True, "result": {"id": 42, "username": "working_bot"}}

    monkeypatch.setattr(telegram_validation, "_get_me", fake_get_me)

    result = validate_channel_config("telegram")

    assert result["status"] == "connected"
    assert captured == {"token": token, "proxy": proxy}
    assert token_ref not in str(result)
    assert token not in str(result)
    assert proxy_ref not in str(result)
    assert proxy not in str(result)


def test_validate_telegram_rejects_unset_proxy_env_ref_without_connecting(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    proxy_ref = "${TELEGRAM_MISSING_PROXY_TEST}"
    monkeypatch.delenv("TELEGRAM_MISSING_PROXY_TEST", raising=False)
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate(
            {"channels": {"telegram": {"token": token, "proxy": proxy_ref}}}
        ),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def fail_get_me(*_args) -> dict:
        pytest.fail("an unresolved proxy reference must not fall back to direct access")

    monkeypatch.setattr(telegram_validation, "_get_me", fail_get_me)

    result = validate_channel_config("telegram")

    assert result["status"] == "invalid"
    assert result["can_enable"] is False
    assert proxy_ref not in str(result)
    assert any(check["id"] == "proxy_env" for check in result["checks"])


def test_validate_telegram_uses_proxy_submitted_with_new_token(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    proxy = "http://127.0.0.1:7890"
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    captured: dict[str, str | None] = {}

    def fake_get_me(token_value: str, proxy_value: str | None) -> dict:
        captured.update(token=token_value, proxy=proxy_value)
        return {"ok": True, "result": {"id": 42, "username": "new_bot"}}

    monkeypatch.setattr(telegram_validation, "_get_me", fake_get_me)

    result = validate_channel_config(
        "telegram",
        {
            "channels.telegram.token": token,
            "channels.telegram.proxy": proxy,
        },
    )

    assert result["status"] == "connected"
    assert captured == {"token": token, "proxy": proxy}


@pytest.mark.parametrize("proxy", ["127.0.0.1:7890", "http://[", "http://localhost:not-a-port"])
def test_validate_telegram_rejects_invalid_proxy_without_trying_token(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    proxy: str,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def fail_get_me(*_args) -> dict:
        pytest.fail("invalid proxy must stop before getMe")

    monkeypatch.setattr(telegram_validation, "_get_me", fail_get_me)

    result = validate_channel_config(
        "telegram",
        {
            "channels.telegram.token": token,
            "channels.telegram.proxy": proxy,
        },
    )

    assert result["status"] == "invalid"
    assert result["can_enable"] is False
    assert proxy not in str(result)
    assert any(check["id"] == "proxy_format" for check in result["checks"])
