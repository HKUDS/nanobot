"""One-time script to bootstrap .manifest.json from existing uploads.

Scans the uploads directory, hashes each file, keeps the first occurrence
of each hash, and marks duplicates for removal. Run with --execute to delete.

Usage:
    python scripts/bootstrap_upload_manifest.py [--execute]
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

UPLOADS_DIR = Path.home() / ".nanobot" / "workspace" / "uploads"


def main() -> None:
    execute = "--execute" in sys.argv

    if not UPLOADS_DIR.exists():
        print(f"No uploads directory at {UPLOADS_DIR}")
        return

    manifest: dict[str, str] = {}
    duplicates: list[Path] = []
    kept: list[Path] = []

    for f in sorted(UPLOADS_DIR.iterdir()):
        if not f.is_file() or f.name == ".manifest.json":
            continue
        content_hash = hashlib.sha256(f.read_bytes()).hexdigest()
        if content_hash in manifest:
            duplicates.append(f)
        else:
            manifest[content_hash] = f.name
            kept.append(f)

    print(f"Unique files: {len(kept)}")
    print(f"Duplicates:   {len(duplicates)}")
    saved_bytes = sum(f.stat().st_size for f in duplicates)
    print(f"Space to free: {saved_bytes / 1024 / 1024:.1f} MB")
    print()

    for f in duplicates:
        action = "DELETING" if execute else "WOULD DELETE"
        print(f"  {action}: {f.name} ({f.stat().st_size / 1024:.1f} KB)")
        if execute:
            f.unlink()

    if execute:
        manifest_path = UPLOADS_DIR / ".manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nManifest written with {len(manifest)} entries.")
        print(f"Freed {saved_bytes / 1024 / 1024:.1f} MB")
    else:
        print("\nDry run. Pass --execute to actually delete.")


if __name__ == "__main__":
    main()
