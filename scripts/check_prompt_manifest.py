#!/usr/bin/env python3
"""Verify prompt template files match their manifest hashes.

Ensures prompt changes are intentional — any modification to a prompt
template file must be accompanied by an updated ``prompts_manifest.json``.

Usage:
    python scripts/check_prompt_manifest.py          # verify (CI mode)
    python scripts/check_prompt_manifest.py --update  # regenerate manifest
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "nanobot" / "templates" / "prompts"
MANIFEST_FILE = ROOT / "prompts_manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan_prompts() -> dict[str, str]:
    """Return {filename: sha256} for all .md files in the prompts directory."""
    if not PROMPTS_DIR.is_dir():
        return {}
    return {p.name: _sha256(p) for p in sorted(PROMPTS_DIR.glob("*.md"))}


def _load_manifest() -> dict[str, str]:
    if not MANIFEST_FILE.exists():
        return {}
    data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return data.get("prompts", {})


def update() -> None:
    """Regenerate prompts_manifest.json from current prompt files."""
    current = _scan_prompts()
    payload = {
        "_comment": (
            "SHA-256 hashes of prompt template files. Verified by "
            "scripts/check_prompt_manifest.py in CI. "
            "Update with: python scripts/check_prompt_manifest.py --update"
        ),
        "prompts": current,
    }
    MANIFEST_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {MANIFEST_FILE.relative_to(ROOT)} with {len(current)} prompts.")


def verify() -> list[str]:
    """Compare prompt files against manifest. Returns list of error strings."""
    manifest = _load_manifest()
    current = _scan_prompts()
    errors: list[str] = []

    if not manifest and not current:
        return errors  # nothing to check

    if not MANIFEST_FILE.exists():
        errors.append("prompts_manifest.json not found — run with --update to create it.")
        return errors

    # Check for missing files (in manifest but not on disk)
    for name in sorted(set(manifest) - set(current)):
        errors.append(f"  MISSING: {name} listed in manifest but not found on disk")

    # Check for untracked files (on disk but not in manifest)
    for name in sorted(set(current) - set(manifest)):
        errors.append(f"  UNTRACKED: {name} exists on disk but not in manifest")

    # Check for hash mismatches
    for name in sorted(set(manifest) & set(current)):
        if manifest[name] != current[name]:
            errors.append(f"  CHANGED: {name} hash mismatch (update manifest if intentional)")

    return errors


def main() -> int:
    if "--update" in sys.argv:
        update()
        return 0

    errors = verify()
    if errors:
        print(f"Prompt manifest verification failed ({len(errors)} issues):\n")
        for e in errors:
            print(e)
        print(f"\nTo update the manifest: python {Path(__file__).name} --update")
        return 1

    manifest = _load_manifest()
    print(f"Prompt manifest OK — {len(manifest)} prompts verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
