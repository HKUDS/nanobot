"""Resume a partial index upload only when existing files match staged bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from nanobot.releases import PLATFORMS

INDEXES = {"pypi": "https://pypi.org", "testpypi": "https://test.pypi.org"}


def remove_uploaded_files(directory: Path, *, version: str, destination: str) -> int:
    """Check the complete remote release before removing any identical local files."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or destination not in INDEXES:
        raise ValueError("Expected a final stable version and supported package index")
    expected = {f"nanobot_ai-{version}-py3-none-{platform}.whl" for platform in PLATFORMS.values()}
    expected.add(f"nanobot_ai-{version}.tar.gz")
    if {item.name for item in directory.iterdir()} != expected:
        raise ValueError("Staged files do not match the complete release")
    url = f"{INDEXES[destination]}/pypi/nanobot-ai/{version}/json"
    try:
        with urlopen(url, timeout=30) as response:
            payload = response.read(4 * 1024 * 1024 + 1)
    except HTTPError as exc:
        if exc.code == 404:
            return len(expected)
        raise
    if len(payload) > 4 * 1024 * 1024:
        raise ValueError("Package index response is too large")
    data = json.loads(payload)
    if data["info"]["name"] != "nanobot-ai" or data["info"]["version"] != version:
        raise ValueError("Package index returned a different project or version")
    uploaded: set[str] = set()
    for entry in data["urls"]:
        name = entry["filename"]
        if name not in expected or name in uploaded or entry.get("yanked"):
            raise ValueError("Package index contains an unexpected, duplicate or yanked file")
        path = directory / name
        if path.is_symlink() or not path.is_file() or entry["size"] != path.stat().st_size:
            raise ValueError(f"Published file differs from the staged release: {name}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if entry["digests"]["sha256"] != digest:
            raise ValueError(f"Published file differs from the staged release: {name}")
        uploaded.add(name)
    for name in uploaded:
        (directory / name).unlink()
    return len(expected) - len(uploaded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--destination", choices=INDEXES, required=True)
    args = parser.parse_args()
    remaining = remove_uploaded_files(args.directory, version=args.version, destination=args.destination)
    print(f"Files remaining to upload: {remaining}")


if __name__ == "__main__":
    main()
