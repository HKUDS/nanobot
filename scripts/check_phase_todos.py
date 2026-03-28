#!/usr/bin/env python3
"""Verify TODO comments referencing completed phases are resolved.

Scans Python files for '# TODO Phase N' comments.
Fails if a completed phase has unresolved TODOs.

Exit 0 if clean, exit 1 if violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Phases that have been completed.  TODOs referencing these phases are bugs
# --- the work should have been done when the phase shipped.
COMPLETED_PHASES: frozenset[int] = frozenset({1, 2, 3, 4, 5, 6})

# Pattern matches: # TODO Phase 3, # TODO phase 3, # TODO: Phase 3, etc.
_TODO_PHASE_RE = re.compile(r"#\s*TODO[:\s]*Phase\s+(\d+)", re.IGNORECASE)

ROOT = Path(__file__).resolve().parent.parent


def scan_phase_todos() -> list[str]:
    """Scan nanobot/**/*.py for TODO Phase N comments referencing completed phases."""
    violations: list[str] = []
    nanobot_dir = ROOT / "nanobot"
    if not nanobot_dir.is_dir():
        return violations

    for py_file in sorted(nanobot_dir.rglob("*.py")):
        rel = py_file.relative_to(ROOT)
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(lines, start=1):
            match = _TODO_PHASE_RE.search(line)
            if match:
                phase_num = int(match.group(1))
                if phase_num in COMPLETED_PHASES:
                    violations.append(
                        f"  {rel}:{lineno}  TODO references completed "
                        f"Phase {phase_num}: {line.strip()}"
                    )
    return violations


def main() -> int:
    violations = scan_phase_todos()
    if violations:
        print(f"Phase TODO violations ({len(violations)}):\n")
        print("\n".join(violations))
        print(
            f"\nThese TODOs reference completed phases {sorted(COMPLETED_PHASES)}."
            "\nEither resolve the TODO or update COMPLETED_PHASES."
        )
        return 1
    print("Phase TODOs OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
