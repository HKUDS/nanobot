#!/usr/bin/env python3
"""
Skill Discovery - Search local skills by keywords.

A cross-platform skill search tool that works on macOS, Linux, and Windows.
Supports multiple languages (English, Chinese, etc.) and output formats.

Usage:
    python search_skills.py -q "keyword" [options]

Examples:
    python search_skills.py -q "video"
    python search_skills.py -q "send message" -l 5
    python search_skills.py -q "image generation" --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class Skill:
    """Represents a discovered skill."""

    name: str
    description: str
    path: Path

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
        }


class SkillFinder:
    """
    Find and search local skills.

    Supports multiple search backends:
    - ripgrep (rg): Fast, 10-100x quicker
    - Python grep: Cross-platform fallback
    """

    # Builtin skills directory (relative to this script)
    BUILTIN_SKILLS_DIR = Path(__file__).parent.parent.parent  # nanobot/skills/

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        prefer_rg: bool = True,
    ):
        """
        Initialize the skill finder.

        Args:
            skills_dir: Workspace skills directory (auto-detect if None)
            prefer_rg: Prefer ripgrep for searching (fallback to Python if unavailable)
        """
        self.workspace_skills_dir = skills_dir or self._detect_workspace_dir()
        self.builtin_skills_dir = self.BUILTIN_SKILLS_DIR
        self.prefer_rg = prefer_rg and self._has_ripgrep()

    def _detect_workspace_dir(self) -> Optional[Path]:
        """Auto-detect workspace skills directory."""
        candidates = [
            Path.home() / ".nanobot" / "workspace" / "skills",
            Path.home() / ".nanobot" / "skills",
        ]
        for path in candidates:
            if path.exists() and path.is_dir():
                return path

        # Check relative to current directory
        local_skills = Path.cwd() / "skills"
        if local_skills.exists():
            return local_skills

        return None

    @property
    def skills_dirs(self) -> list[Path]:
        """Get all skills directories to search."""
        dirs = []
        if self.workspace_skills_dir:
            dirs.append(self.workspace_skills_dir)
        if self.builtin_skills_dir.exists():
            dirs.append(self.builtin_skills_dir)
        return dirs

    @staticmethod
    def _has_ripgrep() -> bool:
        """Check if ripgrep is available."""
        try:
            subprocess.run(
                ["rg", "--version"],
                capture_output=True,
                timeout=5,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def find_all_skills(self) -> Iterator[Path]:
        """Find all SKILL.md files in all skills directories."""
        for skills_dir in self.skills_dirs:
            yield from skills_dir.rglob("SKILL.md")

    @staticmethod
    def parse_frontmatter(content: str) -> dict:
        """
        Parse YAML frontmatter from SKILL.md content.

        Simple parser for flat key-value pairs. Handles:
        - name: value
        - name: "quoted value"
        - name: 'quoted value'
        """
        metadata = {}

        if not content.startswith("---"):
            return metadata

        # Find frontmatter boundaries
        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return metadata

        frontmatter = match.group(1)

        for line in frontmatter.split("\n"):
            # Skip empty lines and comments
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Remove quotes
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]

            metadata[key] = value

        return metadata

    def load_skill(self, skill_path: Path) -> Optional[Skill]:
        """Load a skill from its SKILL.md file."""
        try:
            content = skill_path.read_text(encoding="utf-8")
            metadata = self.parse_frontmatter(content)

            name = metadata.get("name", skill_path.parent.name)
            description = metadata.get("description", "")

            return Skill(
                name=name,
                description=description,
                path=skill_path,
            )
        except Exception:
            return None

    def _search_with_ripgrep(
        self,
        keywords: list[str],
        case_insensitive: bool = True,
    ) -> list[Path]:
        """Search using ripgrep (fast)."""
        if not self.skills_dirs:
            return []

        pattern = "|".join(re.escape(k) for k in keywords)
        matches = []

        for skills_dir in self.skills_dirs:
            cmd = [
                "rg",
                "-i" if case_insensitive else "-s",
                "-l",  # List matching files only
                "--glob", "*/SKILL.md",
                pattern,
                str(skills_dir),
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                for line in result.stdout.strip().split("\n"):
                    if line:
                        matches.append(Path(line))
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        return matches

    def _search_with_python(
        self,
        keywords: list[str],
        case_insensitive: bool = True,
    ) -> list[Path]:
        """Search using pure Python (cross-platform fallback)."""
        if not self.skills_dirs:
            return []

        matches = []

        for skill_path in self.find_all_skills():
            skill = self.load_skill(skill_path)
            if not skill:
                continue

            # Search in name and description
            searchable = f"{skill.name} {skill.description}"

            for keyword in keywords:
                if case_insensitive:
                    if keyword.lower() in searchable.lower():
                        matches.append(skill_path)
                        break
                else:
                    if keyword in searchable:
                        matches.append(skill_path)
                        break

        return matches

    def search(
        self,
        query: str,
        case_insensitive: bool = True,
        limit: int = 10,
    ) -> list[Skill]:
        """
        Search skills by keywords.

        Args:
            query: Search query (space-separated keywords)
            case_insensitive: Case-insensitive search
            limit: Maximum number of results

        Returns:
            List of matching skills
        """
        # Extract keywords
        keywords = [k for k in re.split(r"\s+", query.strip()) if k]
        if not keywords:
            return []

        # Search
        if self.prefer_rg:
            paths = self._search_with_ripgrep(keywords, case_insensitive)
            if not paths:
                # Fallback to Python search
                paths = self._search_with_python(keywords, case_insensitive)
        else:
            paths = self._search_with_python(keywords, case_insensitive)

        # Load skills and limit results
        skills = []
        for path in paths[:limit]:
            skill = self.load_skill(path)
            if skill:
                skills.append(skill)

        return skills


def format_output(
    skills: list[Skill],
    json_output: bool = False,
    color: bool = True,
) -> str:
    """Format search results for output."""
    if json_output:
        return json.dumps(
            {"results": [s.to_dict() for s in skills]},
            ensure_ascii=False,
            indent=2,
        )

    if not skills:
        msg = "No skills found. Try different keywords or search remote with clawhub."
        return f"\033[33m{msg}\033[0m" if color else msg

    # Color codes
    cyan = "\033[36m" if color else ""
    reset = "\033[0m" if color else ""

    lines = []
    for skill in skills:
        lines.append(f"{cyan}{skill.name}{reset}: {skill.description}")
        lines.append(f"  → {skill.path}")

    return "\n".join(lines)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="search_skills.py",
        description="Search local skills by keywords",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -q "video"
  %(prog)s -q "send message" -l 5
  %(prog)s -q "image generation" --json
  %(prog)s -q "github" -d ~/.nanobot/workspace/skills

Tips:
  - Use multiple keywords for narrower results
  - Supports multiple languages (English, Chinese, etc.)
  - Use --json for machine-readable output
        """,
    )

    parser.add_argument(
        "-q", "--query",
        required=True,
        help="Search keywords (space-separated for multiple)",
    )
    parser.add_argument(
        "-d", "--dir",
        type=Path,
        help="Skills directory (default: auto-detect)",
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=10,
        help="Maximum results (default: 10)",
    )
    parser.add_argument(
        "-c", "--case",
        choices=["auto", "sensitive", "insensitive"],
        default="auto",
        help="Case sensitivity (default: auto)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--no-rg",
        action="store_true",
        help="Disable ripgrep, use Python search only",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    args = parser.parse_args()

    # Determine case sensitivity
    if args.case == "sensitive":
        case_insensitive = False
    elif args.case == "insensitive":
        case_insensitive = True
    else:
        # auto: case-insensitive unless query is all uppercase
        case_insensitive = not args.query.isupper()

    # Create finder and search
    finder = SkillFinder(
        skills_dir=args.dir,
        prefer_rg=not args.no_rg,
    )

    skills = finder.search(
        query=args.query,
        case_insensitive=case_insensitive,
        limit=args.limit,
    )

    # Output
    color = sys.stdout.isatty() and not args.no_color
    print(format_output(skills, json_output=args.json, color=color))


if __name__ == "__main__":
    main()
