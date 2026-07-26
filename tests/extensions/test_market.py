import json
import subprocess

import pytest

from nanobot.extensions.market import ExtensionMarketplace


def test_market_search_normalizes_npm_packages(monkeypatch) -> None:
    payload = [
        {
            "name": "pi-example",
            "version": "1.2.3",
            "description": "Example",
            "keywords": ["pi-package"],
            "publisher": {"username": "alice"},
            "links": {"repository": "https://example.com/repo"},
        }
    ]

    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", run)

    package = ExtensionMarketplace().search("example", ecosystem="pi")[0]

    assert package.name == "pi-example"
    assert package.ecosystem == "pi"
    assert package.publisher == "alice"
    assert package.repository == "https://example.com/repo"


def test_market_rejects_unknown_ecosystem() -> None:
    with pytest.raises(ValueError, match="unknown extension ecosystem"):
        ExtensionMarketplace().search(ecosystem="other")


def test_market_ignores_fuzzy_npm_results(monkeypatch) -> None:
    payload = [
        {
            "name": "unrelated",
            "version": "1.0.0",
            "keywords": ["pi"],
        }
    ]

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            0,
            json.dumps(payload),
            "",
        ),
    )

    assert ExtensionMarketplace().search(ecosystem="pi") == ()


def test_market_rejects_invalid_npm_json(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "not json", ""),
    )

    with pytest.raises(RuntimeError, match="invalid marketplace response"):
        ExtensionMarketplace().search(ecosystem="pi")
