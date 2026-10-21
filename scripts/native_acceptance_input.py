"""Bind native acceptance to the exact wheel produced by this workflow run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from zipfile import ZipFile


def acceptance_input(directory: Path, *, tag: str, commit: str,
                     manifest_sha256: str = "", version: str = "") -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Acceptance requires an exact candidate commit")
    if manifest_sha256:
        manifest_bytes = (directory / "release-manifest.json").read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
            raise ValueError("Candidate manifest differs from the build output")
        manifest = json.loads(manifest_bytes)
        if manifest["candidate_commit"] != commit:
            raise ValueError("Candidate commit differs from the build output")
        version = manifest["version"]
    if not re.fullmatch(r"[0-9][A-Za-z0-9.]*", version):
        raise ValueError("Invalid acceptance version")
    filename = f"nanobot_ai-{version}-py3-none-{tag}.whl"
    wheel = directory / filename
    if wheel.is_symlink() or not wheel.is_file():
        raise ValueError("Acceptance requires the exact native wheel")
    with wheel.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    if manifest_sha256:
        records = [item for item in manifest["artifacts"] if item["filename"] == filename]
        if len(records) != 1 or (records[0]["sha256"], records[0]["size"]) != (sha256, wheel.stat().st_size):
            raise ValueError("Candidate wheel differs from its manifest")
    with ZipFile(wheel) as archive:
        if archive.read("nanobot/_build_commit.txt").decode().strip() != commit:
            raise ValueError("Wheel build commit differs from the acceptance target")
    return {"wheel": str(wheel.resolve()), "version": version, "commit": commit,
            "wheel_sha256": sha256, "manifest_sha256": manifest_sha256}


def main() -> None:
    root = Path(os.environ["RUNNER_TEMP"])
    candidate = os.environ["CANDIDATE"] == "true"
    if candidate:
        commit = os.environ["EXPECTED_COMMIT"]
        manifest_sha256 = os.environ["EXPECTED_MANIFEST"]
        if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
            raise ValueError("Candidate acceptance requires the build's manifest hash")
        version = ""
    else:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        manifest_sha256 = ""
        version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    record = acceptance_input(root / "native-wheel", tag=os.environ["WHEEL_TAG"], commit=commit,
                              manifest_sha256=manifest_sha256, version=version)
    (root / "native-input.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as stream:
        for key in ("wheel", "version", "commit"):
            if "\n" in record[key] or "\r" in record[key]:
                raise ValueError("Invalid acceptance environment value")
            stream.write(f"ACCEPTANCE_{key.upper()}={record[key]}\n")


if __name__ == "__main__":
    main()
