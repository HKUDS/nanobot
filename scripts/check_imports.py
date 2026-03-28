#!/usr/bin/env python3
"""Enforce module boundary rules from CLAUDE.md and docs/architecture.md.

Exit 0 if all rules pass, exit 1 with details on violations.
Designed to run in CI:  python scripts/check_imports.py

Three rule types:
- RULES: forbid ALL imports (runtime + TYPE_CHECKING) from specified modules.
- RUNTIME_RULES: forbid only RUNTIME imports; TYPE_CHECKING imports are allowed.
  Used for dependency-inversion enforcement (cross-package instantiation ban).
  Files listed in COMPOSITION_ROOTS are exempt from RUNTIME_RULES — they are
  responsible for constructing and wiring subsystems by design.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ── Forbidden import rules (ALL imports, including TYPE_CHECKING) ──────
# Format: (source_glob, list_of_forbidden_prefixes)
#
# These enforce the import direction table in CLAUDE.md § "Package Boundaries".
RULES: list[tuple[str, list[str]]] = [
    # --- Infrastructure packages: must never import from orchestration/domain ---
    (
        "nanobot/channels/**/*.py",
        [
            "nanobot.agent",
            "nanobot.tools",
            "nanobot.memory",
            "nanobot.coordination",
        ],
    ),
    (
        "nanobot/providers/**/*.py",
        [
            "nanobot.agent",
            "nanobot.channels",
        ],
    ),
    (
        "nanobot/config/**/*.py",
        [
            "nanobot.agent",
            "nanobot.channels",
            "nanobot.providers",
        ],
    ),
    (
        "nanobot/bus/**/*.py",
        [
            "nanobot.agent",
            "nanobot.channels",
            "nanobot.providers",
        ],
    ),
    # --- Domain packages: must never import from channels/cli ---
    (
        "nanobot/tools/**/*.py",
        [
            "nanobot.channels",
        ],
    ),
    (
        "nanobot/memory/**/*.py",
        [
            "nanobot.channels",
            "nanobot.tools",
        ],
    ),
    (
        "nanobot/agent/**/*.py",
        [
            "nanobot.channels",
            "nanobot.cli",
        ],
    ),
    (
        "nanobot/coordination/**/*.py",
        [
            "nanobot.channels",
            "nanobot.cli",
        ],
    ),
    (
        "nanobot/context/**/*.py",
        [
            "nanobot.channels",
            "nanobot.cli",
        ],
    ),
    (
        "nanobot/observability/**/*.py",
        [
            "nanobot.channels",
            "nanobot.cli",
        ],
    ),
]

# ── Runtime-only forbidden imports (TYPE_CHECKING imports are allowed) ─
# These enforce dependency inversion: packages may reference types from
# other packages via TYPE_CHECKING, but must not import concrete classes
# at runtime for instantiation or isinstance checks.
#
# Files in COMPOSITION_ROOTS are exempt from these rules — they are the
# canonical wiring points that construct and inject subsystems.
RUNTIME_RULES: list[tuple[str, list[str]]] = [
    # coordination/ must not runtime-import concrete tools
    (
        "nanobot/coordination/**/*.py",
        [
            "nanobot.tools.builtin",
        ],
    ),
    # tools/ must not runtime-import coordination classes
    (
        "nanobot/tools/**/*.py",
        [
            "nanobot.coordination",
        ],
    ),
    # agent/ orchestration must not runtime-import from domain subsystems —
    # all wiring flows through agent_factory.py (exempt as composition root)
    (
        "nanobot/agent/**/*.py",
        [
            "nanobot.tools.builtin",
            "nanobot.coordination",
        ],
    ),
    # context/ must not runtime-import memory or concrete tool classes —
    # MemoryStore is injected from agent_factory.py
    (
        "nanobot/context/**/*.py",
        [
            "nanobot.memory",
            "nanobot.tools.builtin",
        ],
    ),
]

# ── Composition roots: files exempt from RUNTIME_RULES ─────────────────
# These files construct and wire subsystems by design.  They are the ONLY
# places where cross-package instantiation is permitted.
COMPOSITION_ROOTS: frozenset[str] = frozenset(
    {
        "nanobot/agent/agent_factory.py",  # primary composition root
        "nanobot/tools/setup.py",  # tool registration entry point
    }
)

ROOT = Path(__file__).resolve().parent.parent

# ── Allowlist: documented exceptions ───────────────────────────────────
# Each entry is (relative_path, imported_module).
#
# Entries are separated into two categories:
# - Legitimate: structurally correct (data objects, deferred lookups)
# - Known violations: tracked for future resolution
ALLOWLIST: set[tuple[str, str]] = {
    # ── Legitimate exceptions: deferred config lookups ─────────────────
    # Config.get_provider / get_api_base need provider registry for model matching.
    ("nanobot/config/schema.py", "nanobot.providers.registry"),
    # ── Legitimate exceptions: data object imports (enums, dataclasses) ─
    # MissionStatus enum (data object, not service).
    ("nanobot/tools/builtin/mission.py", "nanobot.coordination.mission"),
    # DelegationResult dataclass (data object, not service instantiation).
    ("nanobot/coordination/delegation.py", "nanobot.tools.builtin.delegate"),
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
    exempt_files: frozenset[str] = frozenset(),
) -> list[str]:
    """Check a set of rules.

    If *skip_type_checking*, ignore imports inside ``if TYPE_CHECKING:`` blocks.
    Files whose relative path (forward-slash normalised) appears in
    *exempt_files* are skipped entirely.
    """
    violations: list[str] = []
    for glob_pattern, forbidden_prefixes in rules:
        for source_file in sorted(ROOT.glob(glob_pattern)):
            rel = source_file.relative_to(ROOT)
            rel_posix = str(rel).replace("\\", "/")
            if rel_posix in exempt_files:
                continue
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
                        if (rel_posix, module) in ALLOWLIST:
                            continue
                        label = "runtime " if skip_type_checking else ""
                        violations.append(
                            f"  {rel}:{lineno}  {label}imports {module}  (forbidden: {prefix})"
                        )
    return violations


def _is_type_checking_guard(node: ast.If) -> bool:
    """Return True if the ``if`` node is ``if TYPE_CHECKING:``."""
    test = node.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


def _check_type_checking_imports_exist(
    tree: ast.AST,
    filepath: Path,
    nanobot_root: Path,
) -> list[str]:
    """Verify TYPE_CHECKING imports reference modules that exist on disk.

    Walks the AST for ``if TYPE_CHECKING:`` blocks, finds all ``ImportFrom``
    nodes inside, and checks that the referenced module path resolves to a
    real ``.py`` file or ``__init__.py`` directory.  Only checks imports from
    the ``nanobot`` package (third-party and stdlib are skipped).
    """
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not _is_type_checking_guard(node):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.ImportFrom):
                continue
            module = child.module
            if not module or not module.startswith("nanobot"):
                continue
            module_path = module.replace(".", "/")
            if (nanobot_root.parent / f"{module_path}.py").exists() or (
                nanobot_root.parent / module_path / "__init__.py"
            ).exists():
                continue
            violations.append(
                f"  {filepath}:{child.lineno}  TYPE_CHECKING import "
                f"from non-existent module '{module}'"
            )
    return violations


def check_type_checking_existence() -> list[str]:
    """Check all nanobot source files for TYPE_CHECKING imports of missing modules."""
    nanobot_root = ROOT / "nanobot"
    violations: list[str] = []
    for source_file in sorted(nanobot_root.rglob("*.py")):
        rel = source_file.relative_to(ROOT)
        try:
            tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(rel))
        except SyntaxError:
            continue
        violations.extend(_check_type_checking_imports_exist(tree, rel, nanobot_root))
    return violations


def check() -> list[str]:
    violations = _check_rules(RULES, skip_type_checking=False)
    violations.extend(
        _check_rules(
            RUNTIME_RULES,
            skip_type_checking=True,
            exempt_files=COMPOSITION_ROOTS,
        )
    )
    violations.extend(check_type_checking_existence())
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
