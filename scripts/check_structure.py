#!/usr/bin/env python3
"""Enforce structural rules from CLAUDE.md.

Exit 0 if all hard-gate rules pass, exit 1 with details on violations.
Advisory warnings are printed but do not cause failure.

Designed to run in CI:  python scripts/check_structure.py

Hard gates (exit 1):
- File >500 LOC without ``# size-exception: <reason>``
- Package >15 top-level .py files (excluding __init__.py)
- ``__init__.py`` with >12 ``__all__`` entries
- Catch-all filenames (utils.py, helpers.py, common.py, misc.py)
- ``except Exception`` without ``# crash-barrier: <reason>``
- ``__init__.py`` missing ``__all__``
- Missing ``from __future__ import annotations``

Advisory warnings (printed, no failure):
- File >300 LOC (early warning)
- Constructor >7 parameters
- ``__init__.py`` export count approaching 12 (>=10)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "nanobot"

# Packages to check (top-level directories under nanobot/)
PACKAGES = [d for d in sorted(PKG.iterdir()) if d.is_dir() and (d / "__init__.py").exists()]

CATCH_ALL_NAMES = frozenset({"utils.py", "helpers.py", "common.py", "misc.py"})


def _posix_rel(path: Path) -> str:
    """Return path relative to ROOT with forward slashes (cross-platform)."""
    return str(path.relative_to(ROOT)).replace("\\", "/")


# Files/directories exempt from checks (test fixtures, templates, etc.)
EXEMPT_DIRS = frozenset({"templates", "__pycache__", "skills"})


def _count_lines(path: Path) -> int:
    """Count non-empty lines in a Python file."""
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except (OSError, UnicodeDecodeError):
        return 0


def _all_py_files() -> list[Path]:
    """Return all .py files under nanobot/, excluding exempt dirs."""
    files: list[Path] = []
    for f in sorted(PKG.rglob("*.py")):
        parts = f.relative_to(PKG).parts
        if any(p in EXEMPT_DIRS or p == "__pycache__" for p in parts):
            continue
        files.append(f)
    return files


# ---------------------------------------------------------------------------
# Hard gate checks
# ---------------------------------------------------------------------------


def check_file_size(files: list[Path]) -> tuple[list[str], list[str]]:
    """Check file LOC limits. >500 is hard, >300 is advisory."""
    violations: list[str] = []
    warnings: list[str] = []
    for f in files:
        if f.name == "__init__.py":
            continue
        loc = _count_lines(f)
        rel = _posix_rel(f)
        # Check for size-exception marker
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        has_exception = "# size-exception:" in text
        if loc > 500 and not has_exception:
            violations.append(f"  {rel}: {loc} LOC (limit 500, add '# size-exception: <reason>')")
        elif loc > 300:
            warnings.append(f"  {rel}: {loc} LOC (advisory limit 300)")
    return violations, warnings


def check_package_file_count() -> list[str]:
    """Check that no package has >15 top-level .py files (excluding __init__.py)."""
    violations: list[str] = []
    for pkg_dir in PACKAGES:
        if pkg_dir.name in EXEMPT_DIRS:
            continue
        top_files = [
            f
            for f in sorted(pkg_dir.iterdir())
            if f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
        ]
        if len(top_files) > 15:
            rel = _posix_rel(pkg_dir)
            violations.append(f"  {rel}/: {len(top_files)} top-level .py files (limit 15)")
    return violations


def check_init_exports() -> tuple[list[str], list[str]]:
    """Check __init__.py export counts. >12 is hard, >=10 is advisory."""
    violations: list[str] = []
    warnings: list[str] = []
    for init_file in sorted(PKG.rglob("__init__.py")):
        parts = init_file.relative_to(PKG).parts
        if any(p in EXEMPT_DIRS for p in parts):
            continue
        try:
            tree = ast.parse(init_file.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List | ast.Tuple):
                            count = len(node.value.elts)
                            rel = _posix_rel(init_file)
                            if count > 12:
                                violations.append(f"  {rel}: {count} __all__ exports (limit 12)")
                            elif count >= 10:
                                warnings.append(
                                    f"  {rel}: {count} __all__ exports (approaching limit 12)"
                                )
    return violations, warnings


def check_catch_all_filenames(files: list[Path]) -> list[str]:
    """Check for prohibited catch-all filenames."""
    violations: list[str] = []
    for f in files:
        if f.name in CATCH_ALL_NAMES:
            rel = _posix_rel(f)
            violations.append(f"  {rel}: prohibited catch-all filename")
    return violations


def check_crash_barriers(files: list[Path]) -> list[str]:
    """Check that ``except Exception`` has ``# crash-barrier:`` comment.

    Only flags clauses where the *bare* ``Exception`` type is caught
    (possibly in a tuple).  Specific subclasses like ``httpx.TimeoutException``
    are not flagged — the word "Exception" appears but the catch is narrow.
    """
    violations: list[str] = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            lines = f.read_text(encoding="utf-8").splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        rel = _posix_rel(f)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                # bare ``except:`` — also questionable but not our check
                continue
            # Collect all exception types in the handler
            caught_types: list[ast.expr] = []
            if isinstance(node.type, ast.Tuple):
                caught_types.extend(node.type.elts)
            else:
                caught_types.append(node.type)
            # Check if bare ``Exception`` (not a subclass) is among them
            has_bare_exception = any(
                (isinstance(t, ast.Name) and t.id == "Exception") for t in caught_types
            )
            if not has_bare_exception:
                continue
            # Check for crash-barrier comment on same or previous line
            lineno = node.lineno
            line_text = lines[lineno - 1] if lineno <= len(lines) else ""
            prev_text = lines[lineno - 2] if lineno >= 2 else ""
            if "# crash-barrier:" in line_text or "# crash-barrier:" in prev_text:
                continue
            stripped = line_text.strip()
            violations.append(f"  {rel}:{lineno}  {stripped}")
    return violations


def check_init_all_defined() -> list[str]:
    """Check that every __init__.py defines __all__."""
    violations: list[str] = []
    for init_file in sorted(PKG.rglob("__init__.py")):
        parts = init_file.relative_to(PKG).parts
        if any(p in EXEMPT_DIRS for p in parts):
            continue
        try:
            text = init_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Skip empty __init__.py files (namespace packages)
        if not text.strip():
            continue
        if "__all__" not in text:
            rel = _posix_rel(init_file)
            violations.append(f"  {rel}: missing __all__")
    return violations


def check_future_annotations(files: list[Path]) -> list[str]:
    """Check that every module starts with ``from __future__ import annotations``."""
    violations: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Skip empty files
        if not text.strip():
            continue
        if "from __future__ import annotations" not in text:
            rel = _posix_rel(f)
            violations.append(f"  {rel}: missing 'from __future__ import annotations'")
    return violations


# ---------------------------------------------------------------------------
# Advisory checks
# ---------------------------------------------------------------------------


def check_constructor_params(files: list[Path]) -> list[str]:
    """Advisory: check for constructors with >7 parameters."""
    warnings: list[str] = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except (SyntaxError, OSError):
            continue
        rel = _posix_rel(f)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "__init__":
                continue
            args = node.args
            # Count all params except 'self'
            total = len(args.args) - 1  # subtract self
            total += len(args.kwonlyargs)
            if total > 7:
                # Find enclosing class name
                class_name = "?"
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.ClassDef):
                        for child in ast.iter_child_nodes(parent):
                            if child is node:
                                class_name = parent.name
                                break
                warnings.append(
                    f"  {rel}:{node.lineno}  {class_name}.__init__ has {total} params (advisory limit 7)"
                )
    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _load_baseline() -> set[str]:
    """Load known violations from baseline file.

    The baseline file (``scripts/.structure-baseline``) lists one violation
    per line (the indented string produced by each check).  Lines starting
    with ``#`` are comments.  Empty lines are ignored.

    Known violations are printed as "tracked" but do not cause failure.
    Any NEW violation (not in baseline) causes exit 1.
    """
    baseline_path = ROOT / "scripts" / ".structure-baseline"
    if not baseline_path.exists():
        return set()
    entries: set[str] = set()
    for line in baseline_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # Normalise: ensure leading two-space indent matches violation format
            entries.add(stripped if stripped.startswith(" ") else f"  {stripped}")
    return entries


def main() -> int:
    files = _all_py_files()
    all_violations: list[str] = []
    all_warnings: list[str] = []

    # Hard gates
    v, w = check_file_size(files)
    if v:
        all_violations.append("File size violations (>500 LOC):")
        all_violations.extend(v)
    all_warnings.extend(w)

    v = check_package_file_count()
    if v:
        all_violations.append("Package file count violations (>15):")
        all_violations.extend(v)

    v, w = check_init_exports()
    if v:
        all_violations.append("__init__.py export violations (>12):")
        all_violations.extend(v)
    all_warnings.extend(w)

    v = check_catch_all_filenames(files)
    if v:
        all_violations.append("Catch-all filename violations:")
        all_violations.extend(v)

    v = check_crash_barriers(files)
    if v:
        all_violations.append("Missing crash-barrier comments:")
        all_violations.extend(v)

    v = check_init_all_defined()
    if v:
        all_violations.append("Missing __all__ in __init__.py:")
        all_violations.extend(v)

    v = check_future_annotations(files)
    if v:
        all_violations.append("Missing 'from __future__ import annotations':")
        all_violations.extend(v)

    # Advisory
    w = check_constructor_params(files)
    all_warnings.extend(w)

    # Separate new violations from baselined (tracked) ones
    baseline = _load_baseline()
    new_violations: list[str] = []
    tracked: list[str] = []
    for line in all_violations:
        if line.startswith("  ") and line.strip() in {b.strip() for b in baseline}:
            tracked.append(line)
        elif line.startswith("  "):
            new_violations.append(line)
        else:
            # Section headers — keep if they have new violations following
            new_violations.append(line)

    # Clean up section headers that have no new violations after them
    cleaned: list[str] = []
    for i, line in enumerate(new_violations):
        if not line.startswith("  "):
            # Section header — check if next lines have violations
            has_violations = False
            for j in range(i + 1, len(new_violations)):
                if not new_violations[j].startswith("  "):
                    break
                has_violations = True
            if has_violations:
                cleaned.append(line)
        else:
            cleaned.append(line)
    new_violations = cleaned

    # Report
    if all_warnings:
        print(f"Advisory warnings ({len(all_warnings)}):\n")
        for w_line in all_warnings:
            print(w_line)
        print()

    if tracked:
        print(f"Tracked violations ({len(tracked)}, in baseline):\n")
        for t_line in tracked:
            print(t_line)
        print()

    if new_violations:
        print(f"NEW structural violations ({len(new_violations)}):\n")
        for v_line in new_violations:
            print(v_line)
        return 1

    print("Structure OK (no new violations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
