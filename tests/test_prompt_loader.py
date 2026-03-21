"""Tests for nanobot.agent.prompt_loader — template loading and caching."""

from __future__ import annotations

from pathlib import Path

import nanobot.agent.prompt_loader as _prompt_loader_mod
from nanobot.agent.prompt_loader import PromptLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_prompt(base: Path, name: str, content: str) -> Path:
    d = base / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Core loading
# ---------------------------------------------------------------------------


class TestPromptLoaderGet:
    def test_builtin_prompt(self, tmp_path: Path):
        """Built-in prompts should load from templates/prompts/."""
        builtin_dir = tmp_path / "templates" / "prompts"
        builtin_dir.mkdir(parents=True)
        (builtin_dir / "plan.md").write_text("Plan prompt text")

        # Monkey-patch the built-in dir
        mod = _prompt_loader_mod

        orig = mod._BUILTIN_DIR
        mod._BUILTIN_DIR = builtin_dir
        try:
            loader = PromptLoader()
            assert loader.get("plan") == "Plan prompt text"
        finally:
            mod._BUILTIN_DIR = orig

    def test_missing_prompt_returns_empty(self):
        loader = PromptLoader()
        # With an invalid workspace, falls through to builtin; if not found → ""
        loader._workspace = Path("/nonexistent")
        mod = _prompt_loader_mod

        orig = mod._BUILTIN_DIR
        mod._BUILTIN_DIR = Path("/also_nonexistent")
        try:
            result = loader.get("totally_missing")
            assert result == ""
        finally:
            mod._BUILTIN_DIR = orig

    def test_caching(self, tmp_path: Path):
        """Second call for the same name should use cache."""
        builtin_dir = tmp_path / "templates" / "prompts"
        builtin_dir.mkdir(parents=True)
        (builtin_dir / "greet.md").write_text("Hello")

        mod = _prompt_loader_mod

        orig = mod._BUILTIN_DIR
        mod._BUILTIN_DIR = builtin_dir
        try:
            loader = PromptLoader()
            first = loader.get("greet")
            # Modify the file on disk — should still return cached
            (builtin_dir / "greet.md").write_text("Changed")
            second = loader.get("greet")
            assert first == second == "Hello"
        finally:
            mod._BUILTIN_DIR = orig


# ---------------------------------------------------------------------------
# Workspace overrides
# ---------------------------------------------------------------------------


class TestWorkspaceOverride:
    def test_override_takes_precedence(self, tmp_path: Path):
        """Workspace prompts/ directory overrides builtins."""
        builtin_dir = tmp_path / "builtins" / "prompts"
        builtin_dir.mkdir(parents=True)
        (builtin_dir / "plan.md").write_text("builtin plan")

        workspace = tmp_path / "workspace"
        _write_prompt(workspace, "plan", "overridden plan")

        mod = _prompt_loader_mod

        orig = mod._BUILTIN_DIR
        mod._BUILTIN_DIR = builtin_dir
        try:
            loader = PromptLoader(workspace=workspace)
            assert loader.get("plan") == "overridden plan"
        finally:
            mod._BUILTIN_DIR = orig

    def test_fallback_to_builtin(self, tmp_path: Path):
        """When workspace override doesn't exist, fall back to builtin."""
        builtin_dir = tmp_path / "builtins" / "prompts"
        builtin_dir.mkdir(parents=True)
        (builtin_dir / "plan.md").write_text("builtin plan")

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        mod = _prompt_loader_mod

        orig = mod._BUILTIN_DIR
        mod._BUILTIN_DIR = builtin_dir
        try:
            loader = PromptLoader(workspace=workspace)
            assert loader.get("plan") == "builtin plan"
        finally:
            mod._BUILTIN_DIR = orig


# ---------------------------------------------------------------------------
# Preload & clear
# ---------------------------------------------------------------------------


class TestPreloadAndClear:
    def test_preload_populates_cache(self, tmp_path: Path):
        builtin_dir = tmp_path / "prompts"
        builtin_dir.mkdir()
        (builtin_dir / "a.md").write_text("aaa")
        (builtin_dir / "b.md").write_text("bbb")

        mod = _prompt_loader_mod

        orig = mod._BUILTIN_DIR
        mod._BUILTIN_DIR = builtin_dir
        try:
            loader = PromptLoader()
            loader.preload()
            assert "a" in loader._cache
            assert "b" in loader._cache
        finally:
            mod._BUILTIN_DIR = orig

    def test_clear_drops_cache(self):
        loader = PromptLoader()
        loader._cache["test"] = "value"
        loader.clear()
        assert "test" not in loader._cache

    def test_preload_no_dir_is_noop(self, tmp_path: Path):
        """Preload with a non-existent builtin dir should not crash."""
        mod = _prompt_loader_mod

        orig = mod._BUILTIN_DIR
        mod._BUILTIN_DIR = tmp_path / "nonexistent"
        try:
            loader = PromptLoader()
            loader.preload()  # no error
            assert loader._cache == {}
        finally:
            mod._BUILTIN_DIR = orig


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TestRender:
    @staticmethod
    def _make_loader(tmp_path: Path, files: dict[str, str]) -> PromptLoader:
        mod = _prompt_loader_mod

        prompts_dir = tmp_path / "templates" / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (prompts_dir / f"{name}.md").write_text(content)
        loader = PromptLoader()
        # Store original so fixture can restore it; tests use finally blocks
        loader._orig_dir = mod._BUILTIN_DIR  # type: ignore[attr-defined]
        mod._BUILTIN_DIR = prompts_dir
        return loader

    @staticmethod
    def _restore(loader: PromptLoader) -> None:
        mod = _prompt_loader_mod

        mod._BUILTIN_DIR = loader._orig_dir  # type: ignore[attr-defined]

    def test_substitutes_known_variables(self, tmp_path: Path) -> None:
        loader = self._make_loader(tmp_path, {"greeting": "Hello, {name}! Welcome to {place}."})
        try:
            result = loader.render("greeting", name="Alice", place="Wonderland")
            assert result == "Hello, Alice! Welcome to Wonderland."
        finally:
            self._restore(loader)

    def test_leaves_unknown_variables_untouched(self, tmp_path: Path) -> None:
        loader = self._make_loader(tmp_path, {"greeting": "Hello, {name}! Welcome to {place}."})
        try:
            result = loader.render("greeting", name="Alice")
            assert result == "Hello, Alice! Welcome to {place}."
        finally:
            self._restore(loader)

    def test_no_variables_same_as_get(self, tmp_path: Path) -> None:
        loader = self._make_loader(tmp_path, {"static": "No variables here."})
        try:
            result = loader.render("static")
            assert result == "No variables here."
        finally:
            self._restore(loader)

    def test_escaped_braces_survive(self, tmp_path: Path) -> None:
        loader = self._make_loader(tmp_path, {"escaped": "Use {{key}} for cache lookup."})
        try:
            result = loader.render("escaped")
            assert result == "Use {key} for cache lookup."
        finally:
            self._restore(loader)

    def test_render_missing_prompt_returns_empty(self, tmp_path: Path) -> None:
        loader = self._make_loader(tmp_path, {})
        try:
            result = loader.render("nonexistent", foo="bar")
            assert result == ""
        finally:
            self._restore(loader)


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------


class TestModuleSingleton:
    def test_singleton_exists(self):
        from nanobot.agent.prompt_loader import prompts

        assert isinstance(prompts, PromptLoader)

    def test_singleton_is_stable(self):
        from nanobot.agent.prompt_loader import prompts as p1
        from nanobot.agent.prompt_loader import prompts as p2

        assert p1 is p2
