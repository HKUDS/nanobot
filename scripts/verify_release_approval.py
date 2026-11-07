"""Check a maintainer's exact release approval before requesting a signature.

This script only reads data. It must run from the protected workflow checkout,
never from a downloaded candidate, and must never import or execute that package.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from nanobot.releases import ReleaseManifest


def verify_manifest(path: Path, *, sha256: str, version: str,
                    source_commit: str, candidate_commit: str) -> ReleaseManifest:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("Expected a bounded, regular release manifest")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != sha256:
        raise ValueError("Manifest differs from the maintainer-approved digest")
    manifest = ReleaseManifest.model_validate_json(payload)
    if (manifest.version, manifest.source_commit, manifest.candidate_commit) != (version, source_commit, candidate_commit):
        raise ValueError("Manifest differs from the maintainer-approved release identity")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    for name in ("sha256", "version", "source-commit", "candidate-commit"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    manifest = verify_manifest(args.manifest, sha256=args.sha256, version=args.version,
                               source_commit=args.source_commit, candidate_commit=args.candidate_commit)
    print(f"Verified exact approval for {manifest.version}; no candidate code was executed")


if __name__ == "__main__":
    main()
