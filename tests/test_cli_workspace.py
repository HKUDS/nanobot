"""Tests for the workspace CLI commands."""

from __future__ import annotations

import json
from pathlib import Path


class TestPruneUploads:
    """Tests for `nanobot workspace prune-uploads`."""

    def test_removes_files_not_in_manifest(self, tmp_path: Path) -> None:
        from nanobot.cli.workspace import _prune_uploads

        # Create an orphan file (not tracked in manifest)
        orphan = tmp_path / "orphan.xlsx"
        orphan.write_bytes(b"stale data")
        # Create a tracked file
        tracked = tmp_path / "tracked.csv"
        tracked.write_bytes(b"good data")
        manifest = {"abc123": "tracked.csv"}
        (tmp_path / ".manifest.json").write_text(json.dumps(manifest))

        removed, kept = _prune_uploads(tmp_path, dry_run=False)
        assert len(removed) == 1
        assert removed[0].name == "orphan.xlsx"
        assert not orphan.exists()
        assert tracked.exists()

    def test_dry_run_does_not_delete(self, tmp_path: Path) -> None:
        from nanobot.cli.workspace import _prune_uploads

        orphan = tmp_path / "orphan.txt"
        orphan.write_bytes(b"data")
        (tmp_path / ".manifest.json").write_text(json.dumps({}))

        removed, kept = _prune_uploads(tmp_path, dry_run=True)
        assert len(removed) == 1
        assert orphan.exists()  # NOT deleted in dry-run

    def test_no_manifest_removes_nothing(self, tmp_path: Path) -> None:
        from nanobot.cli.workspace import _prune_uploads

        existing = tmp_path / "file.txt"
        existing.write_bytes(b"data")

        removed, kept = _prune_uploads(tmp_path, dry_run=False)
        # Without a manifest, we can't know what's tracked — remove nothing
        assert len(removed) == 0
        assert existing.exists()

    def test_prune_also_cleans_stale_manifest_entries(self, tmp_path: Path) -> None:
        from nanobot.cli.workspace import _prune_uploads

        # Manifest references a file that no longer exists on disk
        manifest = {"hash1": "gone.txt", "hash2": "exists.txt"}
        (tmp_path / ".manifest.json").write_text(json.dumps(manifest))
        (tmp_path / "exists.txt").write_bytes(b"data")

        _prune_uploads(tmp_path, dry_run=False)
        updated = json.loads((tmp_path / ".manifest.json").read_text())
        assert "hash1" not in updated  # stale entry removed
        assert "hash2" in updated  # valid entry kept

    def test_empty_uploads_dir(self, tmp_path: Path) -> None:
        from nanobot.cli.workspace import _prune_uploads

        (tmp_path / ".manifest.json").write_text(json.dumps({}))
        removed, kept = _prune_uploads(tmp_path, dry_run=False)
        assert len(removed) == 0
        assert len(kept) == 0
