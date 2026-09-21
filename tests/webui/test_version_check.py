from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import nanobot.webui.version_check as version_check


@pytest.fixture(autouse=True)
def _reset_version_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_check, "_cache", (0.0, None))
    monkeypatch.setattr(version_check.time, "monotonic", lambda: 1_000.0)


def _pypi_response(latest: object) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"info": {"version": latest}}
    return response


def test_version_check_reports_only_a_newer_release_and_caches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get = MagicMock(return_value=_pypi_response("1.3.0"))
    monkeypatch.setattr(version_check, "__version__", "1.2.0")
    monkeypatch.setattr(version_check.httpx, "get", get)

    expected = {
        "currentVersion": "1.2.0",
        "latestVersion": "1.3.0",
        "pypiUrl": "https://pypi.org/project/nanobot-ai/",
    }
    assert version_check.check_for_update() == expected
    assert version_check.check_for_update() == expected
    get.assert_called_once_with(
        "https://pypi.org/pypi/nanobot-ai/json",
        timeout=5.0,
        follow_redirects=True,
    )


@pytest.mark.parametrize("latest", ["1.2.0", "1.1.9", "not-a-version", 42, None])
def test_version_check_ignores_non_newer_or_invalid_releases(
    monkeypatch: pytest.MonkeyPatch,
    latest: object,
) -> None:
    monkeypatch.setattr(version_check, "__version__", "1.2.0")
    monkeypatch.setattr(version_check.httpx, "get", lambda *_args, **_kwargs: _pypi_response(latest))

    assert version_check.check_for_update() is None


def test_version_check_treats_network_failure_as_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get = MagicMock(side_effect=TimeoutError("offline"))
    monkeypatch.setattr(version_check.httpx, "get", get)

    assert version_check.check_for_update() is None

    # Failures are not cached, so a later explicit check can recover.
    assert version_check.check_for_update() is None
    assert get.call_count == 2
