"""Verify that living documentation references are still valid.

Checks docs/architecture.md for:
1. Class names (backtick-wrapped) that no longer exist in nanobot/
2. File paths referenced that no longer exist on disk

Exit 0 if clean, exit 1 if stale references found.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Classes that are external or conceptual — not expected in nanobot/ source
KNOWN_EXCEPTIONS = frozenset(
    {
        # Standard library / third-party
        "Protocol",
        "SQLite",
        "FTS5",
        "OTEL",
        "ONNX",
        # Conceptual / shorthand references (not actual class names)
        "BFS",
        "CTE",
        "RRF",
        "CRUD",
        "DAG",
        # Generic terms that appear in backticks but aren't classes
        "check_imports.py",
        "check_structure.py",
        "check_prompt_manifest.py",
        "check_doc_references.py",
        "agent_factory.py",
        "tools/setup.py",
        # Type annotations or protocol references
        "TYPE_CHECKING",
        # Python builtins / common terms that match PascalCase
        "True",
        "False",
        "None",
        "No",
    }
)

# Pattern for backtick-wrapped class-like names (PascalCase)
CLASS_PATTERN = re.compile(r"`([A-Z][a-zA-Z0-9]+)`")

# Pattern for file paths like `memory/migration.py` or `nanobot/agent/loop.py`
FILE_PATH_PATTERN = re.compile(
    r"`((?:nanobot/|memory/|agent/|tools/|coordination/|context/)[a-z_/]+\.py)`"
)


def find_classes_in_doc(doc_path: Path) -> set[str]:
    """Extract PascalCase class names from backtick-wrapped references."""
    text = doc_path.read_text(encoding="utf-8")
    matches = CLASS_PATTERN.findall(text)
    return {m for m in matches if m not in KNOWN_EXCEPTIONS}


def find_file_paths_in_doc(doc_path: Path) -> set[str]:
    """Extract file paths referenced in backtick-wrapped references."""
    text = doc_path.read_text(encoding="utf-8")
    return set(FILE_PATH_PATTERN.findall(text))


def class_exists_in_codebase(class_name: str, search_dir: Path) -> bool:
    """Check if a class definition exists anywhere in nanobot/."""
    try:
        result = subprocess.run(
            ["grep", "-r", f"class {class_name}", str(search_dir), "--include=*.py", "-l"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Fallback: manual search
        for py_file in search_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                if f"class {class_name}" in content:
                    return True
            except (OSError, UnicodeDecodeError):
                continue
        return False


def file_path_exists(file_path: str, project_root: Path) -> bool:
    """Check if a referenced file path exists."""
    # Try both with and without nanobot/ prefix
    candidates = [
        project_root / file_path,
        project_root / "nanobot" / file_path,
    ]
    return any(c.exists() for c in candidates)


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    doc_path = project_root / "docs" / "architecture.md"
    nanobot_dir = project_root / "nanobot"

    if not doc_path.exists():
        print(f"SKIP: {doc_path} not found")
        return 0

    if not nanobot_dir.exists():
        print(f"SKIP: {nanobot_dir} not found")
        return 0

    stale_classes: list[str] = []
    stale_files: list[str] = []

    # Check class references
    classes = find_classes_in_doc(doc_path)
    for class_name in sorted(classes):
        if not class_exists_in_codebase(class_name, nanobot_dir):
            stale_classes.append(class_name)

    # Check file path references
    file_paths = find_file_paths_in_doc(doc_path)
    for fp in sorted(file_paths):
        if not file_path_exists(fp, project_root):
            stale_files.append(fp)

    if stale_classes or stale_files:
        print("docs/architecture.md has stale references:\n")
        if stale_classes:
            print("  Classes not found in nanobot/:")
            for c in stale_classes:
                print(f"    - {c}")
        if stale_files:
            print("\n  File paths not found:")
            for f in stale_files:
                print(f"    - {f}")
        print(f"\nTotal: {len(stale_classes)} stale classes, {len(stale_files)} stale files")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
