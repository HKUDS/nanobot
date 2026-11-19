"""Stage only the publicly available files covered by an approved release manifest."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from pathlib import Path

from nanobot.release_trust import verify_release_approval
from nanobot.releases import ReleaseManifest


def stage_release(release_dir: Path, output: Path, *, version: str, tag_commit: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Only final stable versions may be published to PyPI")
    manifest_path = release_dir / "release-manifest.json"
    proof_path = release_dir / "release-manifest.json.sigstore.json"
    for path, limit in ((manifest_path, 64 * 1024), (proof_path, 256 * 1024)):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise ValueError(f"Missing or invalid approval file: {path.name}")
    payload, proof = manifest_path.read_bytes(), proof_path.read_bytes()
    verify_release_approval(payload, proof)
    manifest = ReleaseManifest.model_validate_json(payload)
    if manifest.version != version or manifest.candidate_commit != tag_commit:
        raise ValueError("Signed release identity does not match the version and tag")

    for item in manifest.artifacts:
        path = release_dir / item.filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size != item.size:
            raise ValueError(f"Missing or changed release file: {item.filename}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item.sha256:
            raise ValueError(f"Release checksum mismatch: {item.filename}")

    output.mkdir(parents=True, exist_ok=False)
    for item in manifest.artifacts:
        if item.filename.endswith((".whl", ".tar.gz")):
            shutil.copyfile(release_dir / item.filename, output / item.filename)
    print(f"Staged signed release {version}: five wheels and one source distribution")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag-commit", required=True)
    args = parser.parse_args()
    stage_release(args.release_dir, args.output, version=args.version, tag_commit=args.tag_commit)


if __name__ == "__main__":
    main()
