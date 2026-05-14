import json
from pathlib import Path

import pytest

from nanobot.telegram_healthcheck import run_healthcheck
from nanobot.telegram_polling_health import TelegramHealthState, TelegramPollingHealthRequest


def test_telegram_health_state_mark_ok_writes_state_file(tmp_path: Path) -> None:
    state_path = tmp_path / "telegram-health.json"
    state = TelegramHealthState(path=state_path)

    state.mark_ok("poll ok")

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["detail"] == "poll ok"
    assert isinstance(payload["last_ok"], float)
    assert payload["consecutive_errors"] == 0


def test_run_healthcheck_is_healthy_when_telegram_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"channels": {"telegram": {"enabled": false}}}', encoding="utf-8")

    monkeypatch.setattr("nanobot.telegram_healthcheck._proc1_cmdline", lambda: ["nanobot", "gateway"])
    monkeypatch.setattr("nanobot.telegram_healthcheck._config_path_from_args", lambda _args: config_path)

    assert run_healthcheck() == 0


def test_run_healthcheck_is_unhealthy_when_state_file_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"channels": {"telegram": {"enabled": true}}}', encoding="utf-8")
    state_path = tmp_path / "missing-health.json"

    monkeypatch.setattr("nanobot.telegram_healthcheck._proc1_cmdline", lambda: ["nanobot", "gateway"])
    monkeypatch.setattr("nanobot.telegram_healthcheck._config_path_from_args", lambda _args: config_path)
    monkeypatch.setattr("nanobot.telegram_healthcheck._env_path", lambda _name, _default: state_path)

    assert run_healthcheck() == 1


@pytest.mark.asyncio
async def test_polling_health_request_marks_ok_on_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = TelegramHealthState(path=tmp_path / "telegram-health.json")
    request = object.__new__(TelegramPollingHealthRequest)
    request._health_state = state

    async def fake_do_request(self, url: str, method: str, **kwargs):
        return (200, b"{}")

    monkeypatch.setattr("telegram.request.HTTPXRequest.do_request", fake_do_request)

    result = await request.do_request("https://example.com", "GET")

    payload = json.loads(state.path.read_text(encoding="utf-8"))
    assert result == (200, b"{}")
    assert payload["status"] == "ok"
    assert payload["consecutive_errors"] == 0


@pytest.mark.asyncio
async def test_polling_health_request_marks_error_on_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = TelegramHealthState(path=tmp_path / "telegram-health.json")
    request = object.__new__(TelegramPollingHealthRequest)
    request._health_state = state

    async def fake_do_request(self, url: str, method: str, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("telegram.request.HTTPXRequest.do_request", fake_do_request)

    with pytest.raises(RuntimeError, match="boom"):
        await request.do_request("https://example.com", "GET")

    payload = json.loads(state.path.read_text(encoding="utf-8"))
    assert payload["status"] == "error"
    assert payload["last_error"] == "boom"
    assert payload["consecutive_errors"] == 1
