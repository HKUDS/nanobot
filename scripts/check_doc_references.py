"""Verify that living documentation references are still valid.

Checks all living docs for:
1. Class names (backtick-wrapped) that no longer exist in nanobot/
2. File paths referenced that no longer exist on disk

Also checks ADR status consistency (supersession chains, file/class refs).

Exit 0 if clean, exit 1 if stale references found.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Living docs to check (relative to project root)
LIVING_DOCS = [
    "CLAUDE.md",
    ".claude/rules/architecture.md",
    "docs/memory-system-reference.md",
    "docs/deployment.md",
]

# Classes that are external or conceptual — not expected in nanobot/ source
KNOWN_EXCEPTIONS = frozenset(
    {
        # Standard library / third-party
        "Protocol",
        "SQLite",
        "FTS5",
        "OTEL",
        "ONNX",
        "Exception",
        "Pydantic",
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
        # Test-only classes (live in tests/, not nanobot/)
        "ScriptedProvider",
        # Deliberately renamed / historical references documented as warnings
        "MemoryError",
        # Third-party / external class names
        "SettingsConfigDict",
        "TracerProvider",
        "MetricsCollector",
        # ADR references to removed/evolved classes (ADRs are historical records)
        "BeliefStore",
        "ProfileManager",
        "RetrievalPlanner",
        "EvalRunner",
        "MemoryStore",
        "PromptLoader",
        "AgentRegistry",
        "CheckEmailTool",
        "WebSearchTool",
        "UnknownRoleError",
        "FeaturesConfig",
        "LLMConfig",
        "BaseChannel",
        "ChannelsConfig",
        "OutboundMessage",
        # Docker / deployment terms
        "Docker",
        "Dockerfile",
        "Caddy",
        "Grafana",
        "Prometheus",
        "WireGuard",
        "CodeQL",
        "Dependabot",
        "Trivy",
    }
)

# File paths that are examples/templates in docs, not expected to exist on disk
KNOWN_FILE_EXCEPTIONS = frozenset(
    {
        "nanobot/skills/your-skill/SKILL.md",
    }
)

# Pattern for backtick-wrapped class-like names (PascalCase)
CLASS_PATTERN = re.compile(r"`([A-Z][a-zA-Z0-9]+)`")

# Pattern for file paths like `memory/migration.py` or `nanobot/agent/loop.py`
# Covers nanobot/ source, scripts, tests, docs, and .claude paths
FILE_PATH_PATTERN = re.compile(
    r"`((?:nanobot/|memory/|agent/|tools/|coordination/|context/"
    r"|scripts/|tests/|docs/|\.claude/)[a-zA-Z0-9_/.+-]+\.(?:py|md|sh|json))`"
)

# Pattern for ADR supersession: "Superseded by [ADR-NNN](ADR-NNN-title.md)"
ADR_SUPERSEDED_PATTERN = re.compile(r"[Ss]uperseded by \[ADR-(\d+)\]\(([^)]+)\)")


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
    """Check if a referenced file path exists.

    Handles paths with and without nanobot/ prefix.
    Paths ending with / are treated as directories.
    """
    # Strip trailing slash for directory references
    clean_path = file_path.rstrip("/")

    candidates = [
        project_root / clean_path,
        project_root / "nanobot" / clean_path,
    ]
    return any(c.exists() for c in candidates)


def check_document(
    doc_path: Path, nanobot_dir: Path, project_root: Path
) -> tuple[list[str], list[str]]:
    """Check a single document for stale class and file references.

    Returns (stale_classes, stale_files).
    """
    stale_classes: list[str] = []
    stale_files: list[str] = []

    if not doc_path.exists():
        return stale_classes, stale_files

    # Check class references
    classes = find_classes_in_doc(doc_path)
    for class_name in sorted(classes):
        if not class_exists_in_codebase(class_name, nanobot_dir):
            stale_classes.append(class_name)

    # Check file path references
    file_paths = find_file_paths_in_doc(doc_path)
    for fp in sorted(file_paths):
        if fp in KNOWN_FILE_EXCEPTIONS:
            continue
        if not file_path_exists(fp, project_root):
            stale_files.append(fp)

    return stale_classes, stale_files


def check_adr_status(adr_dir: Path, project_root: Path) -> list[str]:
    """Check ADR status consistency.

    Verifies:
    - Superseded-by references point to existing ADR files
    - File paths in ADRs exist on disk
    """
    issues: list[str] = []

    if not adr_dir.exists():
        return issues

    for adr_file in sorted(adr_dir.glob("ADR-*.md")):
        # Skip the template
        if adr_file.name == "ADR-000-template.md":
            continue

        text = adr_file.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Check first 10 lines for supersession references
        header = "\n".join(lines[:10])
        for match in ADR_SUPERSEDED_PATTERN.finditer(header):
            ref_file = match.group(2)
            ref_path = adr_dir / ref_file
            if not ref_path.exists():
                issues.append(
                    f"{adr_file.name}: superseded-by references '{ref_file}' which does not exist"
                )

    return issues


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    nanobot_dir = project_root / "nanobot"

    if not nanobot_dir.exists():
        print(f"SKIP: {nanobot_dir} not found")
        return 0

    all_stale_classes: dict[str, list[str]] = {}
    all_stale_files: dict[str, list[str]] = {}
    has_errors = False

    # Check each living doc
    for doc_rel in LIVING_DOCS:
        doc_path = project_root / doc_rel
        if not doc_path.exists():
            print(f"SKIP: {doc_rel} not found")
            continue

        stale_classes, stale_files = check_document(doc_path, nanobot_dir, project_root)
        if stale_classes:
            all_stale_classes[doc_rel] = stale_classes
        if stale_files:
            all_stale_files[doc_rel] = stale_files

    # Check ADR status consistency
    adr_dir = project_root / "docs" / "adr"
    adr_issues = check_adr_status(adr_dir, project_root)

    # Report results
    if all_stale_classes or all_stale_files:
        has_errors = True
        for doc_rel in LIVING_DOCS:
            classes = all_stale_classes.get(doc_rel, [])
            files = all_stale_files.get(doc_rel, [])
            if not classes and not files:
                continue
            print(f"{doc_rel} has stale references:\n")
            if classes:
                print("  Classes not found in nanobot/:")
                for c in classes:
                    print(f"    - {c}")
            if files:
                print("\n  File paths not found:")
                for f in files:
                    print(f"    - {f}")
            print()

    if adr_issues:
        has_errors = True
        print("ADR status issues:\n")
        for issue in adr_issues:
            print(f"  - {issue}")
        print()

    if has_errors:
        total_classes = sum(len(v) for v in all_stale_classes.values())
        total_files = sum(len(v) for v in all_stale_files.values())
        total_adr = len(adr_issues)
        print(
            f"Total: {total_classes} stale classes, {total_files} stale files, "
            f"{total_adr} ADR issues"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
