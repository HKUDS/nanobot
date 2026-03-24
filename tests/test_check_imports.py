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

from check_imports import RULES, _collect_imports, check  # noqa: E402

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
# check() integration
# ---------------------------------------------------------------------------


class TestCheck:
    def test_no_violations(self):
        """The real codebase should have no violations (enforced by CI)."""
        violations = check()
        assert violations == [], "Import violations found:\n" + "\n".join(violations)
