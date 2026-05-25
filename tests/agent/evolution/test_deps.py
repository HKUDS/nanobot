"""Tests for evolution optional dependency detection."""

from __future__ import annotations

import builtins
import sys
from types import ModuleType

from nanobot.agent.evolution import deps


def test_evolution_extra_available_when_dspy_has_gepa(monkeypatch) -> None:
    fake_dspy = ModuleType("dspy")
    fake_dspy.GEPA = object()
    monkeypatch.setitem(sys.modules, "dspy", fake_dspy)

    assert deps.evolution_extra_available() is True


def test_evolution_extra_unavailable_when_dspy_missing_gepa(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "dspy", ModuleType("dspy"))

    assert deps.evolution_extra_available() is False


def test_evolution_extra_unavailable_when_dspy_not_installed(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "dspy", raising=False)
    real_import = builtins.__import__

    def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "dspy":
            raise ImportError("No module named 'dspy'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    assert deps.evolution_extra_available() is False


def test_require_evolution_extra_returns_none_when_available(monkeypatch) -> None:
    monkeypatch.setattr(deps, "evolution_extra_available", lambda: True)

    assert deps.require_evolution_extra() is None


def test_require_evolution_extra_returns_install_hint_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(deps, "evolution_extra_available", lambda: False)

    message = deps.require_evolution_extra()

    assert message is not None
    assert "pip install nanobot-ai[evolution]" in message
