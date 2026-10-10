"""Verify the complete macOS payload before adding it to a platform wheel."""
from __future__ import annotations

import hashlib
import io
import json
import plistlib
import runpy
import struct
import tarfile
from pathlib import Path, PurePosixPath

from nanobot.apps.computer_use_native import APP, VERSION, package_digest

ROOT = Path(__file__).resolve().parents[1]


def verified_bundle(directory: Path, architecture: str, *, root: Path = ROOT) -> dict[str, bytes]:
    digest = package_digest(directory, architecture=architecture)
    if not digest:
        raise ValueError(f"Missing Computer Use payload for {architecture}")
    manifest = json.loads((directory / "native-package.json").read_text())
    raw = (directory / "native-package.tar.gz").read_bytes()
    if len(raw) > 200 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Computer Use archive checksum mismatch")
    if manifest.get("profile") != "release" or manifest.get("minimum_macos") != "14.2":
        raise ValueError("Computer Use requires a reviewed release profile and minimum OS")
    files: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                raise ValueError("Unsafe Computer Use package path")
            if member.isdir():
                continue
            total += member.size
            if not member.isfile() or member.name in files or total > 512 * 1024 * 1024:
                raise ValueError("Invalid Computer Use package entry")
            stream = archive.extractfile(member)
            assert stream is not None
            files[member.name] = stream.read()
    prefix = f"nanobot-computer-use-{VERSION}-darwin/"
    contents = prefix + APP + "/Contents/"
    resources = contents + "Resources/"
    required = [prefix + "LICENSE", prefix + "THIRD_PARTY_NOTICES.md",
        resources + "Cua-MIT-LICENSE.md", resources + "nanobot-MIT-LICENSE",
        resources + "THIRD_PARTY_NOTICES.md", resources + "MPL-SOURCES.tar.gz",
        resources + "RUST-NOTICES.txt", resources + "RUST-COPYRIGHT-library.html",
        resources + "NANOBOT-SOURCES.tar", resources + "PROVENANCE.md",
        resources + "AppIcon.png", resources + "cursor-themes/io.nanobot.computer-use.cua-theme",
        contents + "Info.plist", contents + "MacOS/nanobot-computer-use",
        contents + "_CodeSignature/CodeResources"]
    if any(not files.get(name) for name in required):
        raise ValueError("Computer Use package is missing executable, signature, source or license material")
    info = plistlib.loads(files[contents + "Info.plist"])
    if (info.get("CFBundleIdentifier") != "io.nanobot.computer-use"
            or info.get("CFBundleDisplayName") != "nanobot Computer Use"
            or info.get("LSMinimumSystemVersion") != "14.2"):
        raise ValueError("Computer Use application identity does not match")
    binary = files[contents + "MacOS/nanobot-computer-use"]
    cpu = {"arm64": 0x0100000C, "x86_64": 0x01000007}[architecture]
    if len(binary) < 8 or binary[:4] != b"\xcf\xfa\xed\xfe" or struct.unpack_from("<I", binary, 4)[0] != cpu:
        raise ValueError("Computer Use executable architecture does not match")
    material = runpy.run_path(str(root / "native/computer-use/package_materials.py"))
    source = material["application_source"](root / "native/computer-use")
    if (source != files[resources + "NANOBOT-SOURCES.tar"]
            or hashlib.sha256(source).hexdigest() != manifest.get("source_sha256")):
        raise ValueError("Computer Use sources do not match the release checkout; rebuild it")
    notices = files[prefix + "THIRD_PARTY_NOTICES.md"]
    if notices != files[resources + "THIRD_PARTY_NOTICES.md"] or any(
        word not in notices for word in (b"yabai", b"Steven Sheldon", b"Inter Project Authors", b"Mozilla Public License Version 2.0")
    ):
        raise ValueError("Computer Use attribution is incomplete")
    with tarfile.open(fileobj=io.BytesIO(files[resources + "MPL-SOURCES.tar.gz"]), mode="r:gz") as mpl:
        names = mpl.getnames()
        if "LICENSE-MPL-2.0" not in names or not any(name.startswith("uniffi_core-") and name.endswith(".rs") for name in names):
            raise ValueError("Computer Use MPL source is incomplete")
    # Relative, relocatable inputs only. No developer paths enter a wheel.
    manifest["archive"] = "native-package.tar.gz"
    return {"native-package.tar.gz": raw, "native-package.json": (json.dumps(manifest, indent=2) + "\n").encode()}
