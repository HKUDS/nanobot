#!/usr/bin/env python3
"""Regenerate docs/README.md navigation tree from docs/*.md headings."""

import re
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
README = DOCS_DIR / "README.md"

# Files to include and their sort order
DOC_ORDER = [
    "project-structure.md",
    "project-commands.md",
    "code-principle.md",
    "code-snippets-study.md",
    "codex-worklog.md",
]


def extract_entries(filepath: Path) -> list[str]:
    """Extract navigation entries from a markdown file."""
    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines()
    entries: list[str] = []
    in_code_block = False

    for i, line in enumerate(lines):
        # Track code blocks to skip headings inside them
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # ## level headings → direct entry
        m = re.match(r"^## (.+)", line)
        if m:
            title = m.group(1).strip()
            entries.append(title)
            continue

        # ### 记录 N → look for nearby - 标题: or - 任务目标:
        m = re.match(r"^### (记录 \d+)", line)
        if m:
            record_label = m.group(1)
            # Search next 10 lines for title
            subtitle = ""
            for j in range(i + 1, min(i + 10, len(lines))):
                sm = re.match(r"^-\s*(标题|任务目标)\s*:\s*(.+)", lines[j])
                if sm:
                    subtitle = sm.group(2).strip()
                    break
            if subtitle:
                entries.append(f"{record_label}：{subtitle}")
            else:
                entries.append(record_label)

    return entries


def build_tree() -> str:
    """Build the full navigation tree."""
    lines = ["# docs/ 文档导航", ""]

    # Only include user-managed docs in defined order
    ordered = [name for name in DOC_ORDER if (DOCS_DIR / name).exists()]

    for idx, doc_name in enumerate(ordered):
        filepath = DOCS_DIR / doc_name
        if not filepath.exists():
            continue

        entries = extract_entries(filepath)

        # Tree connectors
        is_last = idx == len(ordered) - 1
        prefix = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "

        lines.append(f"{prefix}{doc_name}")

        for ei, entry in enumerate(entries):
            is_last_entry = ei == len(entries) - 1
            connector = "└── " if is_last_entry else "├── "
            lines.append(f"{child_prefix}{connector}{entry}")

        if not is_last:
            lines.append(f"{child_prefix}")

    return "\n".join(lines) + "\n"


def main():
    if not DOCS_DIR.exists():
        print(f"docs/ directory not found: {DOCS_DIR}", file=sys.stderr)
        sys.exit(1)

    tree = build_tree()
    README.write_text(tree, encoding="utf-8")
    print(f"Updated {README}")


if __name__ == "__main__":
    main()
