"""Native distribution must retain source/attribution, not only SPDX labels."""
import io
import json
import runpy
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def collector():
    path = Path(__file__).resolve().parents[2] / "packages/computer-use/package_materials.py"
    return runpy.run_path(str(path))["dependency_notices"]


def dependency(directory, name, license_id="MIT"):
    directory.mkdir(parents=True)
    (directory / "Cargo.toml").write_text("# fixture\n")
    return {"id": name, "name": name, "version": "1.0.0", "license": license_id,
            "manifest_path": str(directory / "Cargo.toml"), "source": "registry+fixture",
            "repository": "https://example.invalid/upstream"}


def graph(*packages):
    return {"packages": list(packages), "resolve": {"nodes": [{"id": p["id"]} for p in packages]}}


def test_application_source_contains_build_inputs_not_generated_cache(tmp_path):
    path = Path(__file__).resolve().parents[2] / "packages/computer-use/package_materials.py"
    collect = runpy.run_path(str(path))["application_source"]
    root = tmp_path / "packages/computer-use"
    inputs = {"Cargo.lock": "pinned dependencies", "build.py": "# builder",
              "src/main.rs": "fn main() {}", "patches/sdk.patch": "SDK patch",
              "licenses/cua-derived.txt": "derived attribution"}
    for name, content in inputs.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    for cache in (".cua-source", "target", ".build", "dist", "__pycache__"):
        file = root / cache / "generated.rs"
        file.parent.mkdir()
        file.write_text("not first-party source")
    for name in ("LICENSE", "webui/src/assets/apps/computer-use.webp"):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"source material")
    raw = collect(root)
    assert raw == collect(root)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        assert set(archive.getnames()) == {
            *("packages/computer-use/" + name for name in inputs),
            "LICENSE", "webui/src/assets/apps/computer-use.webp",
        }


def test_missing_exact_license_and_unreviewed_license_stop_packaging(tmp_path, collector):
    crate = tmp_path / "crate"
    dep = dependency(crate, "new-dependency")
    (crate / ".cargo_vcs_info.json").write_text(json.dumps({"git": {"sha1": "a" * 40}}))
    with pytest.raises(ValueError, match="Missing exact license material"):
        collector(graph(dep), tmp_path / "upstream", tmp_path)
    dep["license"] = "GPL-3.0-only"
    with pytest.raises(ValueError, match="Review license before packaging"):
        collector(graph(dep), tmp_path / "upstream", tmp_path)


def test_nested_font_notice_and_complete_mpl_crate_travel_with_binary(tmp_path, collector):
    upstream = tmp_path / "upstream"
    (upstream / "LICENSE.md").parent.mkdir()
    (upstream / "LICENSE.md").write_text("fixture Cua MIT notice")
    font = upstream / "libs/cua-driver/rust/crates/cursor-overlay"
    overlay = dependency(font, "cursor-overlay")
    (font / "assets").mkdir()
    (font / "assets/Inter-OFL.txt").write_text("Inter Project Authors — SIL OPEN FONT LICENSE")
    mpl = tmp_path / "uniffi_core"
    uniffi = dependency(mpl, "uniffi_core", "MPL-2.0")
    (mpl / "LICENSE").write_text("fixture MPL license")
    (mpl / "src").mkdir()
    (mpl / "src/lib.rs").write_text("// Complete unchanged source fixture\n")
    (mpl / "build.rs").write_text("fn main() {}\n")
    notices = collector(graph(overlay, uniffi), upstream, tmp_path)
    assert "Inter Project Authors — SIL OPEN FONT LICENSE" in notices
    assert "yabai" in notices and "Steven Sheldon" in notices
    with tarfile.open(tmp_path / "MPL-SOURCES.tar.gz") as archive:
        assert {"LICENSE-MPL-2.0", "uniffi_core-1.0.0/Cargo.toml",
                "uniffi_core-1.0.0/src/lib.rs", "uniffi_core-1.0.0/build.rs"} <= set(archive.getnames())
        assert b"Mozilla Public License Version 2.0" in archive.extractfile("LICENSE-MPL-2.0").read()
