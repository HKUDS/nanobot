#!/usr/bin/env python3
"""Enforce per-module coverage thresholds for critical routing files.

Exit 0 if all thresholds pass, exit 1 with details on violations.
Designed to run in CI:  python scripts/check_module_coverage.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERAGE_JSON = ROOT / "coverage.json"

# (module_relative_path, minimum_percent_covered)
MODULE_THRESHOLDS: list[tuple[str, float]] = [
    ("nanobot/coordination/coordinator.py", 80.0),
    ("nanobot/coordination/delegation.py", 75.0),
    ("nanobot/coordination/registry.py", 90.0),
]


def main() -> int:
    if not COVERAGE_JSON.exists():
        print(
            f"ERROR: {COVERAGE_JSON} not found. Run 'make test-cov' first.",
            file=sys.stderr,
        )
        return 1

    with open(COVERAGE_JSON) as f:
        data = json.load(f)

    files = data.get("files", {})
    violations: list[str] = []

    for module_path, threshold in MODULE_THRESHOLDS:
        file_data = files.get(module_path)
        if file_data is None:
            violations.append(f"  {module_path}: not found in coverage report")
            continue

        pct = file_data["summary"]["percent_covered"]
        if pct < threshold:
            violations.append(f"  {module_path}: {pct:.1f}% < {threshold:.1f}% threshold")
        else:
            print(f"  {module_path}: {pct:.1f}% >= {threshold:.1f}%")

    if violations:
        print("\nModule coverage violations:", file=sys.stderr)
        for v in violations:
            print(v, file=sys.stderr)
        return 1

    print("\nAll module coverage thresholds met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
