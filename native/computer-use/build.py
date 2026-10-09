#!/usr/bin/env python3
"""Reproducible local native build. Never installs, grants access or launches it."""
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
    # Initialize downstream resolution with the upstream's exact dependency
    # versions; subsequent builds use the committed downstream lockfile.
    if not (ROOT / "Cargo.lock").exists():
        shutil.copyfile(RUST / "Cargo.lock", ROOT / "Cargo.lock")
    if options.prepare_only:
        return
    destination = options.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    run("cargo", "build", "--locked", "--manifest-path", str(ROOT / "Cargo.toml"), "-j", "4")
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
    target = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target")))
    shutil.copyfile(target / "debug/nanobot-computer-use", binary)
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
    # Resolve the complete built graph, not just the root crate's license.
    metadata = json.loads(run("cargo", "metadata", "--locked", "--format-version", "1", "--manifest-path", str(ROOT / "Cargo.toml"), stdout=subprocess.PIPE).stdout)
    notices = ["# Third-party notices\n", f"Cua source: https://github.com/trycua/cua/tree/{REVISION}; upstream PR #3019 preserves its contributor authorship.\n",
        "MPL-2.0 dependency sources are supplied unchanged in Resources/MPL-SOURCES.tar.gz, under their original MPL-2.0 terms. No additional restriction applies to those sources.\n"]
    mpl = []
    for dep in sorted(metadata["packages"], key=lambda p: (p["name"], p["version"])):
        dep_root = Path(dep["manifest_path"]).parent
        notices.append(f"\n## {dep['name']} {dep['version']}\nLicense: {dep.get('license') or 'see upstream Cua MIT license'}\n")
        if dep.get("source", "") and dep["source"].startswith("registry+"):
            notices.append(f"Source: https://crates.io/crates/{dep['name']}/{dep['version']}\n")
        if "MPL-2.0" in (dep.get("license") or ""):
            mpl.append((dep_root, f"{dep['name']}-{dep['version']}"))
        notice_files = sorted({*dep_root.glob("LICENSE*"), *dep_root.glob("COPYING*"), *dep_root.glob("NOTICE*")})
        for notice in notice_files:
            if notice.is_file():
                notices.append(f"\n### {notice.name}\n\n{notice.read_text(errors='replace')}\n")
    (package / "THIRD_PARTY_NOTICES.md").write_text("\n".join(notices))
    shutil.copyfile(package / "THIRD_PARTY_NOTICES.md", resources / "THIRD_PARTY_NOTICES.md")
    with tarfile.open(resources / "MPL-SOURCES.tar.gz", "w:gz") as sources:
        for directory, name in mpl:
            sources.add(directory, arcname=name)
    run("codesign", "--sign", "-", "--identifier", "io.nanobot.computer-use", str(app))
    run("codesign", "--verify", "--deep", "--strict", str(app))
    archive_path = destination / (package.name + ".tar.gz")
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(package, arcname=package.name)
    manifest = {"schema": 1, "version": "0.1.0", "revision": REVISION,
        "directory": package.name, "archive": str(archive_path), "architecture": platform.machine().lower(),
        "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest()}
    (destination / "native-package.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(destination / "native-package.json")


if __name__ == "__main__":
    main()
