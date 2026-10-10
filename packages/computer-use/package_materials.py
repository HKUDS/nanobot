"""Collect and verify this package's source, licenses and native release payload."""
import hashlib
import io
import json
import os
import plistlib
import re
import struct
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
LICENSES = ROOT / "licenses"
REVIEWED_LICENSES = {
    "MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "Zlib",
    "BSL-1.0", "0BSD", "Unicode-3.0", "MPL-2.0", "Unlicense", "LLVM-exception",
}


def source_files(root, *, exclude=()):
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in {"target", "__pycache__", ".git", ".cua-source", *exclude})
        for name in sorted(files):
            yield Path(directory) / name


def application_source(root=ROOT):
    """Deterministic first-party source, lockfile, artwork and compliance inputs."""
    paths = [p for p in source_files(root, exclude=(".build", "dist"))
             if p.suffix in {".py", ".rs", ".toml", ".lock", ".md", ".json", ".txt", ".patch"}]
    files = {"packages/computer-use/" + p.relative_to(root).as_posix(): p.read_bytes() for p in paths}
    for name in ("LICENSE", "webui/src/assets/apps/computer-use.webp"):
        files[name] = (root.parents[1] / name).read_bytes()
    output = io.BytesIO()
    # Uncompressed tar has no gzip timestamp; the outer package compresses it.
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.mode, member.size = 0o644, len(content)
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


def rust_notices(sysroot, resources, version):
    """Rust's statically linked runtime is not in cargo metadata's graph."""
    library = sysroot / "lib/rustlib/src/rust/library"
    copyright_file = next((sysroot / "share/doc").rglob("COPYRIGHT-library.html"), None)
    if not library.is_dir() or copyright_file is None:
        raise ValueError("Install this Rust toolchain's rust-src and rust-docs before packaging")
    notices = ["# Rust runtime notices\n", version,
        "Includes library sources and vendored components for all toolchain targets.\n"]
    for name in ("LICENSE-MIT", "LICENSE-APACHE"):
        source = next((path for path in (sysroot / name, sysroot / "share/doc/rust" / name)
                       if path.is_file()), None)
        if source is None:
            raise ValueError(f"Missing Rust toolchain {name}")
        notices.append(source.read_text())
    for path in source_files(library):
        if re.match(r"^(license|copying|copyright|notice)", path.name, re.I):
            notices.append(f"\n## {path.relative_to(library)}\n\n{path.read_text()}")
    (resources / "RUST-NOTICES.txt").write_text("\n".join(notices))
    (resources / "RUST-COPYRIGHT-library.html").write_bytes(copyright_file.read_bytes())


def dependency_notices(metadata, upstream, resources):
    catalog = json.loads((LICENSES / "sources.json").read_text())
    overrides = {(entry["repository"], entry["revision"]): entry for entry in catalog}
    resolved = {node["id"] for node in metadata["resolve"]["nodes"]}
    notices = ["# Third-party notices\n",
        "This list includes the target's runtime and build dependencies. Each retains its own license.\n",
        "Unchanged MPL-2.0 source is in MPL-SOURCES.tar.gz beside this notice, including the full MPL license. "
        "No additional restriction applies to that source.\n",
        "## Cua-derived code credits\n" + (LICENSES / "cua-derived.txt").read_text(),
        "## objc2 retained MIT notice\n"
        "The newer objc2 license file links to MIT instead of reproducing the grant. "
        "The earlier upstream grant and copyright are also retained here.\n"
        + (LICENSES / "objc2-legacy.txt").read_text(),
    ]
    sources = []
    for dep in sorted(metadata["packages"], key=lambda p: (p["name"], p["version"])):
        if dep["id"] not in resolved:
            continue
        directory = Path(dep["manifest_path"]).parent
        license_id = dep.get("license")
        if not license_id and directory.is_relative_to(upstream):
            license_id = "MIT"
        terms = set(re.split(r"[\s()/]+", license_id or "")) - {"", "OR", "AND", "WITH"}
        if not terms or not terms <= REVIEWED_LICENSES:
            raise ValueError(f"Review license before packaging {dep['name']}: {license_id}")
        notices.append(f"\n## {dep['name']} {dep['version']}\nLicense: {license_id}\n")
        if dep.get("authors"):
            notices.append("Authors: " + ", ".join(dep["authors"]) + "\n")
        registry = (dep.get("source") or "").startswith("registry+")
        if registry:
            notices.append(f"Source: https://crates.io/crates/{dep['name']}/{dep['version']}\n")
        local = sorted(p for p in directory.iterdir() if p.is_file()
                       and re.match(r"^(license|copying|copyright|notice)", p.name, re.I))
        if dep.get("license_file"):
            local.append(directory / dep["license_file"])
        if not local:
            if directory.is_relative_to(upstream):
                local = [upstream / "LICENSE.md"]
            elif directory == ROOT:
                local = [ROOT.parents[1] / "LICENSE"]
            else:
                vcs = json.loads((directory / ".cargo_vcs_info.json").read_text())["git"]["sha1"]
                entry = overrides.get((dep.get("repository"), vcs))
                if not entry:
                    raise ValueError(f"Missing exact license material for {dep['name']} {dep['version']}")
                notices.append("License source: " + entry["url"] + "\n")
                local = [LICENSES / entry["file"]]
        # Include embedded assets and bundled subcomponent notices, not just the crate root.
        nested = [p for p in source_files(directory)
                  if re.search(r"^(license|copying|copyright|notice)|[-_]ofl[.]", p.name, re.I)]
        for notice in sorted(set(local + nested)):
            text = notice.read_text()
            if not text.strip():
                raise ValueError(f"Empty license: {notice}")
            notices.append(f"\n### {notice.name}\n\n{text}\n")
        if "MPL-2.0" in terms:
            sources.append((directory, f"{dep['name']}-{dep['version']}"))
    # The Inter font is embedded in Cua's cursor overlay.
    font_license = upstream / "libs/cua-driver/rust/crates/cursor-overlay/assets/Inter-OFL.txt"
    if "SIL OPEN FONT LICENSE" not in font_license.read_text():
        raise ValueError("Missing Inter font license")
    with tarfile.open(resources / "MPL-SOURCES.tar.gz", "w:gz") as archive:
        archive.add(LICENSES / "uniffi.txt", arcname="LICENSE-MPL-2.0")
        for directory, name in sources:
            archive.add(directory, arcname=name)
    if not sources:
        raise ValueError("Expected pinned UniFFI source material")
    return "\n".join(notices)


def verified_bundle(directory: Path, architecture: str) -> dict[str, bytes]:
    """Verify the native payload against this package before wheel assembly."""
    from nanobot.apps.computer_use_native import APP, VERSION, package_digest

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
    source = application_source()
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
