#!/usr/bin/env python3
"""Enforce module boundary rules from docs/architecture.md.

Exit 0 if all rules pass, exit 1 with details on violations.
Designed to run in CI:  python scripts/check_imports.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# ── Forbidden import rules ────────────────────────────────────────────
# Format: (source_glob, list_of_forbidden_prefixes)
# A source file matching source_glob must NOT import any module whose
# dotted path starts with one of the forbidden prefixes.
RULES: list[tuple[str, list[str]]] = [
    ("nanobot/channels/**/*.py", [
        "nanobot.agent",
        "nanobot.tools",
        "nanobot.memory",
        "nanobot.coordination",
    ]),
    ("nanobot/providers/**/*.py", [
        "nanobot.agent",
        "nanobot.channels",
    ]),
    ("nanobot/config/**/*.py", [
        "nanobot.agent",
        "nanobot.channels",
        "nanobot.providers",
    ]),
    ("nanobot/bus/**/*.py", [
        "nanobot.agent",
        "nanobot.channels",
        "nanobot.providers",
    ]),
    ("nanobot/tools/**/*.py", [
        "nanobot.channels",
    ]),
    ("nanobot/memory/**/*.py", [
        "nanobot.channels",
        "nanobot.tools",
    ]),
]

ROOT = Path(__file__).resolve().parent.parent

# Documented exceptions (lazy imports inside methods).
# Format: (relative_path, line_number, imported_module)
ALLOWLIST: set[tuple[str, str]] = {
    # Config.get_provider / get_api_base need provider registry for model matching.
    ("nanobot/config/schema.py", "nanobot.providers.registry"),
}


def _collect_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (line_number, dotted_module) for all imports in an AST."""
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.lineno, node.module))
    return imports


def check() -> list[str]:
    violations: list[str] = []
    for glob_pattern, forbidden_prefixes in RULES:
        for source_file in sorted(ROOT.glob(glob_pattern)):
            rel = source_file.relative_to(ROOT)
            try:
                tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(rel))
            except SyntaxError:
                continue
            for lineno, module in _collect_imports(tree):
                for prefix in forbidden_prefixes:
                    if module == prefix or module.startswith(prefix + "."):
                        if (str(rel).replace("\\", "/"), module) in ALLOWLIST:
                            continue
                        violations.append(f"  {rel}:{lineno}  imports {module}  (forbidden: {prefix})")
    return violations


def main() -> int:
    violations = check()
    if violations:
        print(f"Import boundary violations ({len(violations)}):\n")
        print("\n".join(violations))
        return 1
    print("Import boundaries OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
