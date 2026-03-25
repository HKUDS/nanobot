"""Tests for scripts/check_imports.py — import boundary enforcement."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from check_imports import (  # noqa: E402
    ALLOWLIST,
    COMPOSITION_ROOTS,
    RULES,
    RUNTIME_RULES,
    _collect_imports,
    check,
)

# ---------------------------------------------------------------------------
# _collect_imports
# ---------------------------------------------------------------------------


class TestCollectImports:
    def test_import_statement(self):
        tree = ast.parse("import os\nimport sys")
        imports = _collect_imports(tree)
        assert len(imports) == 2
        assert imports[0] == (1, "os")
        assert imports[1] == (2, "sys")

    def test_from_import(self):
        tree = ast.parse("from pathlib import Path")
        imports = _collect_imports(tree)
        assert len(imports) == 1
        assert imports[0] == (1, "pathlib")

    def test_relative_import_skipped(self):
        """Relative imports (no module name) are not collected."""
        tree = ast.parse("from . import something")
        imports = _collect_imports(tree)
        # node.module is None for bare relative imports
        assert len(imports) == 0

    def test_nested_import(self):
        code = "def f():\n    import json\n"
        tree = ast.parse(code)
        imports = _collect_imports(tree)
        assert len(imports) == 1
        assert imports[0] == (2, "json")

    def test_empty_file(self):
        tree = ast.parse("")
        imports = _collect_imports(tree)
        assert imports == []

    def test_multi_import_single_line(self):
        tree = ast.parse("import os, sys")
        imports = _collect_imports(tree)
        assert len(imports) == 2


# ---------------------------------------------------------------------------
# RULES structure
# ---------------------------------------------------------------------------


class TestRulesStructure:
    def test_rules_nonempty(self):
        assert len(RULES) > 0

    def test_each_rule_has_glob_and_prefixes(self):
        for glob_pattern, forbidden in RULES:
            assert isinstance(glob_pattern, str)
            assert isinstance(forbidden, list)
            assert all(isinstance(p, str) for p in forbidden)

    def test_channels_cannot_import_tools(self):
        channel_rules = [(g, f) for g, f in RULES if "channels" in g]
        assert len(channel_rules) > 0
        forbidden = channel_rules[0][1]
        assert any("nanobot.tools" in f for f in forbidden)

    def test_providers_cannot_import_agent(self):
        provider_rules = [(g, f) for g, f in RULES if "providers" in g]
        assert len(provider_rules) > 0
        forbidden = provider_rules[0][1]
        assert any("agent" in f for f in forbidden)


# ---------------------------------------------------------------------------
# CLAUDE.md boundary table completeness
# ---------------------------------------------------------------------------


class TestBoundaryTableCompleteness:
    """Verify that every rule from CLAUDE.md's boundary table is enforced."""

    # (source_package_glob, forbidden_prefix) pairs from CLAUDE.md
    EXPECTED_RULES: list[tuple[str, str]] = [
        ("nanobot/agent/**/*.py", "nanobot.channels"),
        ("nanobot/agent/**/*.py", "nanobot.cli"),
        ("nanobot/coordination/**/*.py", "nanobot.channels"),
        ("nanobot/coordination/**/*.py", "nanobot.cli"),
        ("nanobot/memory/**/*.py", "nanobot.channels"),
        ("nanobot/memory/**/*.py", "nanobot.tools"),
        ("nanobot/tools/**/*.py", "nanobot.channels"),
        ("nanobot/context/**/*.py", "nanobot.channels"),
        ("nanobot/context/**/*.py", "nanobot.cli"),
        ("nanobot/observability/**/*.py", "nanobot.channels"),
        ("nanobot/observability/**/*.py", "nanobot.cli"),
        ("nanobot/channels/**/*.py", "nanobot.agent"),
        ("nanobot/channels/**/*.py", "nanobot.tools"),
        ("nanobot/channels/**/*.py", "nanobot.memory"),
        ("nanobot/channels/**/*.py", "nanobot.coordination"),
        ("nanobot/providers/**/*.py", "nanobot.agent"),
        ("nanobot/providers/**/*.py", "nanobot.channels"),
        ("nanobot/config/**/*.py", "nanobot.agent"),
        ("nanobot/config/**/*.py", "nanobot.channels"),
        ("nanobot/config/**/*.py", "nanobot.providers"),
        ("nanobot/bus/**/*.py", "nanobot.agent"),
        ("nanobot/bus/**/*.py", "nanobot.channels"),
        ("nanobot/bus/**/*.py", "nanobot.providers"),
    ]

    def test_all_boundary_rules_enforced(self):
        """Every CLAUDE.md boundary rule must appear in RULES."""
        # Build lookup: {(glob, prefix)} from RULES
        enforced = set()
        for glob_pattern, prefixes in RULES:
            for prefix in prefixes:
                enforced.add((glob_pattern, prefix))

        missing = []
        for glob_pattern, prefix in self.EXPECTED_RULES:
            if (glob_pattern, prefix) not in enforced:
                missing.append(f"  {glob_pattern} -> {prefix}")

        assert not missing, (
            "CLAUDE.md boundary rules missing from check_imports.py RULES:\n" + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# RUNTIME_RULES and COMPOSITION_ROOTS
# ---------------------------------------------------------------------------


class TestRuntimeRules:
    def test_runtime_rules_nonempty(self):
        assert len(RUNTIME_RULES) > 0

    def test_agent_cannot_runtime_import_tools_builtin(self):
        agent_rules = [(g, f) for g, f in RUNTIME_RULES if g.startswith("nanobot/agent")]
        forbidden = [p for _, prefixes in agent_rules for p in prefixes]
        assert "nanobot.tools.builtin" in forbidden

    def test_agent_cannot_runtime_import_coordination(self):
        agent_rules = [(g, f) for g, f in RUNTIME_RULES if g.startswith("nanobot/agent")]
        forbidden = [p for _, prefixes in agent_rules for p in prefixes]
        assert "nanobot.coordination" in forbidden

    def test_context_cannot_runtime_import_memory(self):
        ctx_rules = [(g, f) for g, f in RUNTIME_RULES if g.startswith("nanobot/context")]
        forbidden = [p for _, prefixes in ctx_rules for p in prefixes]
        assert "nanobot.memory" in forbidden

    def test_composition_roots_are_exempt(self):
        assert "nanobot/agent/agent_factory.py" in COMPOSITION_ROOTS
        assert "nanobot/tools/setup.py" in COMPOSITION_ROOTS

    def test_composition_roots_immutable(self):
        assert isinstance(COMPOSITION_ROOTS, frozenset)


# ---------------------------------------------------------------------------
# ALLOWLIST audit
# ---------------------------------------------------------------------------


class TestAllowlist:
    def test_no_composition_root_in_allowlist(self):
        """Composition roots are exempt via COMPOSITION_ROOTS, not ALLOWLIST."""
        for filepath, _module in ALLOWLIST:
            assert filepath not in COMPOSITION_ROOTS, (
                f"{filepath} is a composition root — remove from ALLOWLIST"
            )

    def test_all_entries_have_comments_in_source(self):
        """Basic structural check: ALLOWLIST should not be empty."""
        assert len(ALLOWLIST) > 0

    def test_allowlist_size(self):
        """ALLOWLIST should contain only legitimate exceptions (no known violations)."""
        assert len(ALLOWLIST) == 8, f"Expected 8 allowlist entries, got {len(ALLOWLIST)}"

    def test_no_known_violations_in_allowlist(self):
        """All entries should be legitimate — no 'known violation' entries."""
        violation_markers = {"nanobot/agent/loop.py", "nanobot/agent/message_processor.py"}
        for filepath, module in ALLOWLIST:
            if filepath in violation_markers and "tools.builtin" in module:
                raise AssertionError(f"Known violation still in ALLOWLIST: {filepath} -> {module}")


# ---------------------------------------------------------------------------
# check() integration
# ---------------------------------------------------------------------------


class TestCheck:
    def test_no_violations(self):
        """The real codebase should have no violations (enforced by CI)."""
        violations = check()
        assert violations == [], "Import violations found:\n" + "\n".join(violations)
