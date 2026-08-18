"""Create one self-contained, licensed native TUI release archive."""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import zipfile
from pathlib import Path

_SUPPORTED_TARGETS = {
    "darwin-arm64",
    "darwin-x64",
    "linux-arm64",
    "linux-x64",
    "win32-x64",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_archive(root: Path) -> bytes:
    included = [
        "README.md",
        "RELINKING.md",
        "SOURCE_OFFER.md",
        "package.json",
        "bun.lock",
        "tsconfig.json",
        "src",
        "scripts/build.ts",
        "scripts/prepare-target.ts",
        "scripts/release-notices.ts",
        "scripts/package-release.py",
        "licenses",
    ]
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for relative in included:
            path = root / relative
            if not path.exists():
                raise FileNotFoundError(path)
            archive.add(path, arcname=Path("nanobot-tui-source") / relative)
    return output.getvalue()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: package-release.py <target>")
    target = sys.argv[1]
    if target not in _SUPPORTED_TARGETS:
        raise SystemExit(f"unsupported target: {target}")
    root = Path(__file__).resolve().parent.parent
    project_root = root.parent
    extension = ".exe" if target.startswith("win32-") else ""
    asset = f"nanobot-tui-{target}{extension}"
    dist = root / "dist"

    files = {
        asset: (dist / asset).read_bytes(),
        "THIRD_PARTY_NOTICES.txt": (dist / f"{asset}.THIRD_PARTY_NOTICES.txt").read_bytes(),
        "RELINKING.md": (root / "RELINKING.md").read_bytes(),
        "SOURCE_OFFER.md": (root / "SOURCE_OFFER.md").read_bytes(),
        "LICENSE": (project_root / "LICENSE").read_bytes(),
        "BUN-1.3.13-LICENSE.md": (root / "licenses" / "BUN-1.3.13-LICENSE.md").read_bytes(),
        "LGPL-2.0.txt": (root / "licenses" / "LGPL-2.0.txt").read_bytes(),
        "LGPL-2.1.txt": (root / "licenses" / "LGPL-2.1.txt").read_bytes(),
        "nanobot-tui-source.tar.gz": _source_archive(root),
    }
    manifest = "".join(f"{_sha256(content)}  {name}\n" for name, content in files.items()).encode()
    files["MANIFEST.sha256"] = manifest

    output = dist / f"{asset}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    digest = _sha256(output.read_bytes())
    output.with_name(f"{output.name}.sha256").write_text(
        f"{digest}  {output.name}\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
