"""Shared pytest fixtures for nanobot tests."""

import pytest


@pytest.fixture(autouse=True)
def isolate_home(monkeypatch, tmp_path):
    """Force HOME under tmp so tests never touch real ~/.nanobot."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
