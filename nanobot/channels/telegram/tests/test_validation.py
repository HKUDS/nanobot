from __future__ import annotations

import httpx
import pytest

from nanobot.channels.telegram import validation as telegram_validation
from nanobot.channels.validation import validate_channel_config
from nanobot.config.loader import save_config
from nanobot.config.schema import Config


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

    def raise_http_error(url: str, **_kwargs) -> dict:
        request = httpx.Request("GET", url)
        response = httpx.Response(status_code, request=request)
        raise httpx.HTTPStatusError("rejected", request=request, response=response)

    monkeypatch.setattr(telegram_validation, "http_get", raise_http_error)

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

    def raise_http_error(url: str, **_kwargs) -> dict:
        request = httpx.Request("GET", url)
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)

    monkeypatch.setattr(telegram_validation, "http_get", raise_http_error)

    result = validate_channel_config("telegram", {"channels.telegram.token": ""})

    assert result["status"] == "configured"
    assert result["can_enable"] is True
    assert token not in str(result)
    assert any("HTTP 503" in check.get("message", "") for check in result["checks"])
