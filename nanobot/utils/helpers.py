"""Utility functions for nanobot."""

import re
from pathlib import Path
from datetime import datetime


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_path() -> Path:
    """~/.nanobot data directory."""
    return ensure_dir(Path.home() / ".nanobot")


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure workspace path. Defaults to ~/.nanobot/workspace."""
    path = Path(workspace).expanduser() if workspace else Path.home() / ".nanobot" / "workspace"
    return ensure_dir(path)


def timestamp() -> str:
    """Current ISO timestamp."""
    return datetime.now().isoformat()


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Sync bundled markdown templates to workspace recursively.

    Only creates missing files and preserves relative template paths.
    """
    from importlib.resources import files as pkg_files
    try:
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.rglob("*.md"):
        try:
            rel = Path(str(item.relative_to(tpl)))
        except Exception:
            continue
        # Deprecated: file-based memory docs are informational only and should
        # not be materialized into workspace runtime state.
        if rel.parts and rel.parts[0] == "memory":
            continue
        _write(item, workspace / rel)
    skills_dir = ensure_dir(workspace / "skills")
    _sync_workspace_skills(skills_dir, added)

    if added and not silent:
        from rich.console import Console
        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")
    return added


def _sync_workspace_skills(workspace_skills: Path, added: list[str]) -> None:
    """Export bundled skills into workspace/skills (create-only, no overwrite)."""
    from importlib.resources import files as pkg_files

    try:
        builtin = pkg_files("nanobot") / "skills"
    except Exception:
        return
    if not builtin.is_dir():
        return

    for src in builtin.rglob("*"):
        if not src.is_file():
            continue
        try:
            rel = Path(str(src.relative_to(builtin)))
        except Exception:
            continue
        if "__pycache__" in rel.parts or rel.suffix == ".pyc":
            continue
        dest = workspace_skills / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        # Keep console output concise: show only SKILL.md creations.
        if dest.name == "SKILL.md":
            added.append(str(dest.relative_to(workspace_skills.parent)))
