"""Shared fixtures for memory tests."""

import pytest
from pathlib import Path


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace with memory directory."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return tmp_path


@pytest.fixture
def memory_file(workspace):
    """Create a sample structured MEMORY.md."""
    content = """# Long-term Memory

## User
- [fact] User is based in Shanghai
- [fact] User is a backend developer

## Preferences
- [preference] User prefers Python over JavaScript
- [preference] User likes dark mode

## Projects
- [project] Working on nanobot memory feature

## Decisions
- [decision] Use SQLite for local storage

## Notes
- [fact] User timezone is UTC+8
"""
    (workspace / "memory" / "MEMORY.md").write_text(content)
    return workspace


@pytest.fixture
def daily_notes(workspace):
    """Create sample daily note files."""
    (workspace / "memory" / "2026-02-08.md").write_text(
        "# 2026-02-08\n\n"
        "Debugged Docker networking issue.\n"
        "Port conflict with nginx on port 80.\n\n"
        "Discussed long-term memory design for nanobot.\n"
        "User wants to keep it lightweight.\n"
    )
    (workspace / "memory" / "2026-02-07.md").write_text(
        "# 2026-02-07\n\n"
        "Set up CI/CD pipeline with GitHub Actions.\n"
        "All tests passing on Python 3.11 and 3.12.\n"
    )
    return workspace
