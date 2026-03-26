"""CLI commands for workspace management."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from nanobot import __logo__
from nanobot.cli._shared import console

workspace_app = typer.Typer(help="Manage workspace files and storage")


def _prune_uploads(uploads_dir: Path, *, dry_run: bool = True) -> tuple[list[Path], list[Path]]:
    """Remove upload files not tracked in the content-hash manifest.

    Returns (removed, kept) lists.  When *dry_run* is True, files are
    identified but not deleted.
    """
    manifest_path = uploads_dir / ".manifest.json"
    if not manifest_path.exists():
        return [], list(
            f for f in uploads_dir.iterdir() if f.is_file() and f.name != ".manifest.json"
        )

    try:
        manifest: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], []

    tracked_names = set(manifest.values())
    removed: list[Path] = []
    kept: list[Path] = []

    for f in sorted(uploads_dir.iterdir()):
        if not f.is_file() or f.name == ".manifest.json":
            continue
        if f.name in tracked_names:
            kept.append(f)
        else:
            removed.append(f)
            if not dry_run:
                f.unlink()

    # Clean stale manifest entries (file referenced but missing on disk)
    if not dry_run:
        cleaned: dict[str, str] = {
            h: name for h, name in manifest.items() if (uploads_dir / name).exists()
        }
        if len(cleaned) != len(manifest):
            manifest_path.write_text(
                json.dumps(cleaned, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    return removed, kept


@workspace_app.command("prune-uploads")
def prune_uploads(
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Preview without deleting"),
) -> None:
    """Remove uploaded files not tracked in the content-hash manifest."""
    from nanobot.config.loader import load_config

    config = load_config()
    uploads_dir = config.workspace_path / "uploads"

    if not uploads_dir.exists():
        console.print("[dim]No uploads directory found.[/dim]")
        return

    removed, kept = _prune_uploads(uploads_dir, dry_run=dry_run)

    if not removed and not kept:
        console.print("[dim]Uploads directory is empty.[/dim]")
        return

    table = Table(title=f"{__logo__} Upload Pruning {'(dry run)' if dry_run else ''}")
    table.add_column("Status", style="cyan")
    table.add_column("File")
    table.add_column("Size")

    for f in removed:
        size = f.stat().st_size if f.exists() else 0
        table.add_row(
            "[red]REMOVE[/red]" if not dry_run else "[yellow]WOULD REMOVE[/yellow]",
            f.name,
            f"{size / 1024:.1f} KB",
        )
    for f in kept:
        table.add_row("[green]KEEP[/green]", f.name, f"{f.stat().st_size / 1024:.1f} KB")

    console.print(table)

    total_removed = sum(f.stat().st_size for f in removed if f.exists())
    console.print(
        f"\n{'Would free' if dry_run else 'Freed'}: {total_removed / 1024 / 1024:.1f} MB "
        f"({len(removed)} files)"
    )
    if dry_run and removed:
        console.print("[dim]Run with --execute to actually delete.[/dim]")
