"""Tests for Dream enabled flag + custom template paths (#3282)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import Dream, MemoryStore, _resolve_dream_template_path
from nanobot.config.schema import DreamConfig


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_dream_config_enabled_defaults_true() -> None:
    cfg = DreamConfig()

    assert cfg.enabled is True


def test_dream_config_enabled_accepts_false_via_alias() -> None:
    cfg = DreamConfig.model_validate({"enabled": False})

    assert cfg.enabled is False


def test_dream_config_template_paths_default_none() -> None:
    cfg = DreamConfig()

    assert cfg.phase1_template is None
    assert cfg.phase2_template is None


def test_dream_config_template_paths_accept_strings_via_camel_case() -> None:
    cfg = DreamConfig.model_validate({
        "phase1Template": "templates/dream_a.md",
        "phase2Template": "/abs/dream_b.md",
    })

    assert cfg.phase1_template == "templates/dream_a.md"
    assert cfg.phase2_template == "/abs/dream_b.md"


def test_dream_config_dumps_template_paths_with_camel_case_aliases() -> None:
    cfg = DreamConfig(phase1_template="a.md", phase2_template="b.md")

    dumped = cfg.model_dump(by_alias=True)

    assert dumped["phase1Template"] == "a.md"
    assert dumped["phase2Template"] == "b.md"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_resolve_template_path_returns_none_for_none() -> None:
    assert _resolve_dream_template_path(None, Path("/ws")) is None


def test_resolve_template_path_accepts_absolute(tmp_path: Path) -> None:
    abs_template = tmp_path / "mine.md"
    abs_template.write_text("x")

    resolved = _resolve_dream_template_path(str(abs_template), Path("/ws"))

    assert resolved == abs_template


def test_resolve_template_path_resolves_relative_against_workspace(tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir()
    rel_template = tmp_path / "templates" / "p1.md"
    rel_template.write_text("x")

    resolved = _resolve_dream_template_path("templates/p1.md", tmp_path)

    assert resolved == rel_template


def test_resolve_template_path_expands_tilde(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows expanduser uses USERPROFILE, not HOME
    (tmp_path / "custom.md").write_text("x")

    resolved = _resolve_dream_template_path("~/custom.md", Path("/other-ws"))

    assert resolved == tmp_path / "custom.md"


# ---------------------------------------------------------------------------
# Dream validation (conditional on enabled)
# ---------------------------------------------------------------------------


def _make_dream(store: MemoryStore) -> Dream:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock()
    return Dream(store=store, provider=provider, model="test-model")


def test_validate_templates_raises_when_enabled_and_path_missing(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    dream = _make_dream(store)
    dream.enabled = True
    dream.phase1_template_path = tmp_path / "does-not-exist.md"

    with pytest.raises(FileNotFoundError) as exc:
        dream.validate_templates()

    assert "phase1_template" in str(exc.value)


def test_validate_templates_noop_when_disabled_even_with_bad_path(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    dream = _make_dream(store)
    dream.enabled = False
    dream.phase1_template_path = tmp_path / "still-missing.md"
    dream.phase2_template_path = tmp_path / "also-missing.md"

    # Should not raise — Dream is disabled, template paths are irrelevant.
    dream.validate_templates()


def test_validate_templates_passes_when_enabled_and_paths_exist(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    dream = _make_dream(store)
    dream.enabled = True
    good = tmp_path / "ok.md"
    good.write_text("content")
    dream.phase1_template_path = good
    dream.phase2_template_path = good

    dream.validate_templates()


def test_validate_templates_noop_when_paths_are_none(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    dream = _make_dream(store)
    dream.enabled = True
    dream.phase1_template_path = None
    dream.phase2_template_path = None

    dream.validate_templates()


# ---------------------------------------------------------------------------
# Render source
# ---------------------------------------------------------------------------


def test_render_phase1_uses_custom_template_when_path_set(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    dream = _make_dream(store)
    custom = tmp_path / "my_phase1.md"
    custom.write_text("CUSTOM_PHASE1 {{ stale_threshold_days }}")
    dream.phase1_template_path = custom

    rendered = dream._render_phase1_prompt(stale_threshold_days=14)

    assert rendered.startswith("CUSTOM_PHASE1 14")


def test_render_phase1_uses_builtin_when_path_none(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    dream = _make_dream(store)
    dream.phase1_template_path = None

    rendered = dream._render_phase1_prompt(stale_threshold_days=14)

    # Builtin prompt is long and references MEMORY.md consolidation — sanity checks.
    assert len(rendered) > 100
    assert "CUSTOM_PHASE1" not in rendered


def test_render_phase2_uses_custom_template_when_path_set(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    dream = _make_dream(store)
    custom = tmp_path / "my_phase2.md"
    custom.write_text("CUSTOM_PHASE2 {{ skill_creator_path }}")
    dream.phase2_template_path = custom

    rendered = dream._render_phase2_prompt(skill_creator_path="/path/skill-creator/SKILL.md")

    assert rendered.startswith("CUSTOM_PHASE2 /path/skill-creator/SKILL.md")


def test_render_phase2_uses_builtin_when_path_none(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    dream = _make_dream(store)
    dream.phase2_template_path = None

    rendered = dream._render_phase2_prompt(skill_creator_path="/x/y/SKILL.md")

    assert len(rendered) > 100
    assert "CUSTOM_PHASE2" not in rendered
