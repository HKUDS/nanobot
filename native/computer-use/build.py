#!/usr/bin/env python3
"""Build a distributable native payload. Never grant access or launch the app."""
import argparse
import hashlib
import io
import json
import os
import platform
import plistlib
import shutil
import subprocess
import tarfile
from pathlib import Path

from package_materials import application_source, dependency_notices, rust_notices

ROOT = Path(__file__).resolve().parent
REVISION = "d27f6a89d8aeef0f56363ee9bb60bbc565912b1e"
UPSTREAM = ROOT.parent / ".cua-source"
RUST = UPSTREAM / "libs/cua-driver/rust"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Local trycua/cua Git checkout containing the pinned revision")
    parser.add_argument("--output", required=True, type=Path, help="New output directory; never overwritten")
    parser.add_argument("--prepare-only", action="store_true")
    options = parser.parse_args()
    if not UPSTREAM.exists():
        archive = run("git", "-C", str(options.source), "archive", REVISION,
            "libs/cua-driver/rust", "LICENSE.md", stdout=subprocess.PIPE).stdout
        UPSTREAM.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(UPSTREAM, filter="data")
        (UPSTREAM / ".revision").write_text(REVISION)
    if (UPSTREAM / ".revision").read_text() != REVISION:
        raise SystemExit("Prepared source revision differs; use a separate clean build directory.")
    for patch in sorted((ROOT / "patches").glob("*.patch")):
        command = ["git", "apply", "--directory=native/.cua-source"]
        applied = subprocess.run([*command, "--reverse", "--check", str(patch)],
            cwd=ROOT.parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if applied.returncode:
            run(*command, "--check", str(patch), cwd=ROOT.parents[1])
            run(*command, str(patch), cwd=ROOT.parents[1])
    # Initialize downstream resolution with the upstream's exact dependency
    # versions; subsequent builds use the committed downstream lockfile.
    if not (ROOT / "Cargo.lock").exists():
        shutil.copyfile(RUST / "Cargo.lock", ROOT / "Cargo.lock")
    if options.prepare_only:
        return
    destination = options.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    # Retain build-time proc-macro debug info to avoid Rust's broken stripped
    # dylibs on newer macOS (rust-lang/rust#157750). The app remains a release build.
    build_env = {**os.environ, "MACOSX_DEPLOYMENT_TARGET": "14.2",
        "CARGO_PROFILE_RELEASE_BUILD_OVERRIDE_DEBUG": "1"}
    run("cargo", "build", "--release", "--locked", "--manifest-path", str(ROOT / "Cargo.toml"), "-j", "4", env=build_env)
    run("python3", str(ROOT / "build_theme.py"), str(destination / "theme.lottie"))
    run("cargo", "run", "--locked", "--manifest-path", str(RUST / "Cargo.toml"), "-p", "cursor-theme-cli", "--",
        "build", str(destination / "theme.lottie"), "--output", str(destination / "io.nanobot.computer-use.cua-theme"))
    package = destination / "nanobot-computer-use-0.1.0-darwin"
    app = package / "nanobot Computer Use.app"
    contents = app / "Contents"
    binary = contents / "MacOS/nanobot-computer-use"
    resources = contents / "Resources"
    binary.parent.mkdir(parents=True)
    (resources / "cursor-themes").mkdir(parents=True)
    sysroot = Path(run("rustc", "--print", "sysroot", stdout=subprocess.PIPE, text=True).stdout.strip())
    rust_version = run("rustc", "--version", "--verbose", stdout=subprocess.PIPE, text=True).stdout
    rust_notices(sysroot, resources, rust_version)
    target = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target")))
    shutil.copyfile(target / "release/nanobot-computer-use", binary)
    binary.chmod(0o755)
    run("strip", "-x", str(binary))
    shutil.copyfile(destination / "io.nanobot.computer-use.cua-theme", resources / "cursor-themes/io.nanobot.computer-use.cua-theme")
    shutil.copyfile(UPSTREAM / "LICENSE.md", package / "LICENSE")
    shutil.copyfile(UPSTREAM / "LICENSE.md", resources / "Cua-MIT-LICENSE.md")
    shutil.copyfile(ROOT.parents[1] / "LICENSE", resources / "nanobot-MIT-LICENSE")
    shutil.copyfile(ROOT / "README.md", resources / "PROVENANCE.md")
    run("sips", "-s", "format", "png", str(ROOT.parents[1] / "webui/src/assets/apps/computer-use.webp"), "--out", str(resources / "AppIcon.png"), stdout=subprocess.DEVNULL)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "io.nanobot.computer-use", "CFBundleName": "nanobot Computer Use",
        "CFBundleDisplayName": "nanobot Computer Use", "CFBundleExecutable": binary.name,
        "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "CFBundleShortVersionString": "0.1.0",
        "CFBundleIconFile": "AppIcon.png", "LSUIElement": True, "LSMinimumSystemVersion": "14.2",
        "NSHighResolutionCapable": True,
    }))
    triple = {"arm64": "aarch64-apple-darwin", "x86_64": "x86_64-apple-darwin"}[platform.machine().lower()]
    metadata = json.loads(run("cargo", "metadata", "--locked", "--format-version", "1", "--filter-platform", triple,
        "--manifest-path", str(ROOT / "Cargo.toml"), stdout=subprocess.PIPE).stdout)
    notices = (f"Cua source: https://github.com/trycua/cua/tree/{REVISION}\n"
        "Nanobot's MIT SDK patch is in NANOBOT-SOURCES.tar (native/computer-use/patches).\n\n"
        "Rust runtime attribution is in RUST-NOTICES.txt and RUST-COPYRIGHT-library.html.\n\n"
        + dependency_notices(metadata, UPSTREAM, resources))
    (package / "THIRD_PARTY_NOTICES.md").write_text(notices)
    shutil.copyfile(package / "THIRD_PARTY_NOTICES.md", resources / "THIRD_PARTY_NOTICES.md")
    source = application_source()
    (resources / "NANOBOT-SOURCES.tar").write_bytes(source)
    run("codesign", "--sign", "-", "--identifier", "io.nanobot.computer-use", str(app))
    run("codesign", "--verify", "--deep", "--strict", str(app))
    archive_path = destination / "native-package.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(package, arcname=package.name)
    manifest = {"schema": 1, "version": "0.1.0", "revision": REVISION,
        "directory": package.name, "archive": archive_path.name, "architecture": platform.machine().lower(),
        "source_sha256": hashlib.sha256(source).hexdigest(), "profile": "release", "minimum_macos": "14.2",
        "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest()}
    (destination / "native-package.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(destination / "native-package.json")


if __name__ == "__main__":
    main()
