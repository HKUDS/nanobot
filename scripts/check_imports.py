#!/usr/bin/env python3
"""Enforce module boundary rules from docs/architecture.md.

Exit 0 if all rules pass, exit 1 with details on violations.
Designed to run in CI:  python scripts/check_imports.py

Two rule types:
- RULES: forbid ALL imports (runtime + TYPE_CHECKING) from specified modules.
- RUNTIME_RULES: forbid only RUNTIME imports; TYPE_CHECKING imports are allowed.
  Used for dependency-inversion enforcement (cross-package instantiation ban).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# ── Forbidden import rules (ALL imports, including TYPE_CHECKING) ──────
# Format: (source_glob, list_of_forbidden_prefixes)
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

# ── Runtime-only forbidden imports (TYPE_CHECKING imports are allowed) ─
# These enforce dependency inversion: packages may reference types from
# other packages via TYPE_CHECKING, but must not import concrete classes
# at runtime for instantiation.
RUNTIME_RULES: list[tuple[str, list[str]]] = [
    # coordination/ must not instantiate concrete tools at runtime
    ("nanobot/coordination/**/*.py", [
        "nanobot.tools.builtin",
    ]),
    # tools/ must not instantiate coordination classes at runtime
    # (tools/setup.py is the exception — it wires tools at startup)
    ("nanobot/tools/**/*.py", [
        "nanobot.coordination",
    ]),
]

ROOT = Path(__file__).resolve().parent.parent

# Documented exceptions (lazy imports inside methods, startup wiring, etc.).
# Format: (relative_path, imported_module)
ALLOWLIST: set[tuple[str, str]] = {
    # Config.get_provider / get_api_base need provider registry for model matching.
    ("nanobot/config/schema.py", "nanobot.providers.registry"),
    # tools/setup.py is the tool registration entry point — it must import
    # Scratchpad to create placeholder instances for scratchpad tools.
    ("nanobot/tools/setup.py", "nanobot.coordination.scratchpad"),
    # tools/capability.py composes AgentRegistry by design (ADR-009).
    ("nanobot/tools/capability.py", "nanobot.coordination.registry"),
    # tools/builtin/mission.py imports MissionStatus enum (data object, not service).
    ("nanobot/tools/builtin/mission.py", "nanobot.coordination.mission"),
}


def _find_type_checking_lines(tree: ast.AST) -> set[int]:
    """Return line numbers that are inside ``if TYPE_CHECKING:`` blocks."""
    tc_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Match: if TYPE_CHECKING:
        test = node.test
        is_tc = False
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            is_tc = True
        elif isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
            is_tc = True
        if is_tc:
            for child in ast.walk(node):
                if hasattr(child, "lineno"):
                    tc_lines.add(child.lineno)
    return tc_lines


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


def _check_rules(
    rules: list[tuple[str, list[str]]],
    *,
    skip_type_checking: bool = False,
) -> list[str]:
    """Check a set of rules. If skip_type_checking, ignore TYPE_CHECKING imports."""
    violations: list[str] = []
    for glob_pattern, forbidden_prefixes in rules:
        for source_file in sorted(ROOT.glob(glob_pattern)):
            rel = source_file.relative_to(ROOT)
            try:
                tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(rel))
            except SyntaxError:
                continue
            tc_lines = _find_type_checking_lines(tree) if skip_type_checking else set()
            for lineno, module in _collect_imports(tree):
                if skip_type_checking and lineno in tc_lines:
                    continue
                for prefix in forbidden_prefixes:
                    if module == prefix or module.startswith(prefix + "."):
                        if (str(rel).replace("\\", "/"), module) in ALLOWLIST:
                            continue
                        label = "runtime " if skip_type_checking else ""
                        violations.append(
                            f"  {rel}:{lineno}  {label}imports {module}"
                            f"  (forbidden: {prefix})"
                        )
    return violations


def check() -> list[str]:
    violations = _check_rules(RULES, skip_type_checking=False)
    violations.extend(_check_rules(RUNTIME_RULES, skip_type_checking=True))
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
