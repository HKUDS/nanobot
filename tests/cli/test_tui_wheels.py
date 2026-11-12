"""Release wheels carry a complete native bundle, with installable metadata."""

import csv
import hashlib
import io
import json
import runpy
import stat
import struct
import subprocess
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from nanobot.cli import tui_launcher
from scripts import build_tui_wheels as packager
from scripts import release_candidate
from scripts.release_candidate import (
    retain_candidate,
    verify_candidate,
    write_install_guide,
    write_manifest,
)


@pytest.fixture
def candidate(tmp_path):
    version = tomllib.loads((packager.ROOT / "pyproject.toml").read_text())["project"]["version"]
    info = f"nanobot_ai-{version}.dist-info"
    files = {
        "nanobot/__init__.py": f"__version__ = '{version}'\n".encode(),
        f"{info}/METADATA": f"Metadata-Version: 2.4\nName: nanobot-ai\nVersion: {version}\n".encode(),
        f"{info}/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for name, content in files.items():
        writer.writerow((name, packager._digest(content), len(content)))
    writer.writerow((f"{info}/RECORD", "", ""))
    files[f"{info}/RECORD"] = record.getvalue().encode()
    wheel = tmp_path / f"nanobot_ai-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return wheel, info


def make_bundle(directory, target, *, stale_source=False, wrong_architecture=False, omit=None):
    asset = f"nanobot-tui-{target}" + (".exe" if target.startswith("win32-") else "")
    binary = bytearray(128)
    if target.startswith("linux-"):
        binary[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", binary, 18, 183 if target.endswith("arm64") else 62)
    elif target.startswith("darwin-"):
        binary[:4] = b"\xcf\xfa\xed\xfe"
        struct.pack_into("<I", binary, 4, 0x0100000C if target.endswith("arm64") else 0x01000007)
    else:
        binary[:2] = b"MZ"
        struct.pack_into("<I", binary, 60, 64)
        binary[64:70] = b"PE\x00\x00\x64\x86"
    files = {name: b"license material\n" for name in tui_launcher._TUI_RELEASE_FILES}
    files[asset] = b"wrong executable" if wrong_architecture else bytes(binary)
    source = runpy.run_path(str(packager.ROOT / "tui/scripts/package-release.py"))
    files["nanobot-tui-source.tar.gz"] = source["_source_archive"](packager.ROOT / "tui")
    if stale_source:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz"):
            pass
        files["nanobot-tui-source.tar.gz"] = output.getvalue()
    version = json.loads((packager.ROOT / "tui/package.json").read_text())["dependencies"]["@opentui/core"]
    files["THIRD_PARTY_NOTICES.txt"] = (
        f"Target: {target}\n===== @opentui/core {version} (MIT) =====\n"
    ).encode()
    if omit:
        files.pop(omit)
    files["MANIFEST.sha256"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()
    ).encode()
    output = directory / f"{asset}.zip"
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    output.with_suffix(".zip.sha256").write_text(
        f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {output.name}\n"
    )
    return files


@pytest.mark.parametrize("target", packager.PLATFORMS)
def test_platform_wheel_record_permissions_and_complete_bundle(tmp_path, candidate, target):
    wheel, info = candidate
    bundle = make_bundle(tmp_path, target)
    output = packager.build_wheel(wheel, tmp_path, tmp_path / "wheels", target)
    assert output.name.endswith(f"-py3-none-{packager.PLATFORMS[target]}.whl")
    with zipfile.ZipFile(output) as archive:
        metadata = BytesParser().parsebytes(archive.read(f"{info}/WHEEL"))
        assert metadata["Root-Is-Purelib"] == "false"
        assert metadata.get_all("Tag") == [f"py3-none-{packager.PLATFORMS[target]}"]
        for name, content in bundle.items():
            path = f"nanobot/tui/bin/{name}"
            assert archive.read(path) == content
            mode = archive.getinfo(path).external_attr >> 16
            assert stat.S_ISREG(mode)
            assert stat.S_IMODE(mode) == (0o755 if name.startswith(f"nanobot-tui-{target}") else 0o644)
        rows = list(csv.reader(io.StringIO(archive.read(f"{info}/RECORD").decode())))
        assert len(rows) == len(archive.namelist())
        for name, digest, size in rows:
            if name.endswith("/RECORD"):
                assert (digest, size) == ("", "")
            else:
                data = archive.read(name)
                assert (digest, size) == (packager._digest(data), str(len(data)))
    with pytest.raises(FileExistsError):
        packager.build_wheel(wheel, tmp_path, output.parent, target)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"stale_source": True}, "source does not match"),
        ({"wrong_architecture": True}, "architecture"),
        ({"omit": "SOURCE_OFFER.md"}, "incomplete"),
    ],
)
def test_rejects_bad_native_bundle(tmp_path, candidate, kwargs, error):
    wheel, _ = candidate
    make_bundle(tmp_path, "linux-x64", **kwargs)
    with pytest.raises((ValueError, tui_launcher.TuiUnavailableError), match=error):
        packager.build_wheel(wheel, tmp_path, tmp_path / "wheels", "linux-x64")
    assert not (tmp_path / "wheels").exists()


def test_rejects_mismatched_python_version(tmp_path, candidate):
    wheel, _ = candidate
    renamed = wheel.with_name(wheel.name.replace("-py3-", "-other-py3-"))
    wheel.rename(renamed)
    with pytest.raises(ValueError, match="universal wheel"):
        packager.build_wheel(renamed, tmp_path, tmp_path / "wheels", "linux-x64")


def test_rejects_damaged_python_wheel(tmp_path, candidate):
    wheel, _ = candidate
    with zipfile.ZipFile(wheel) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["nanobot/__init__.py"] = b"changed after building"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="RECORD mismatch"):
        packager.build_wheel(wheel, tmp_path, tmp_path / "wheels", "linux-x64")


def test_rejects_damaged_archive_checksum(tmp_path, candidate):
    wheel, _ = candidate
    make_bundle(tmp_path, "linux-x64")
    (tmp_path / "nanobot-tui-linux-x64.zip.sha256").write_text("0" * 64 + "  wrong.zip\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        packager.build_wheel(wheel, tmp_path, tmp_path / "wheels", "linux-x64")


@pytest.mark.parametrize(
    ("system", "machine", "target"),
    [("Darwin", "arm64", "darwin-arm64"), ("Darwin", "x86_64", "darwin-x64"),
     ("Linux", "aarch64", "linux-arm64"), ("Linux", "x86_64", "linux-x64"),
     ("Windows", "AMD64", "win32-x64")],
)
def test_installed_tui_never_downloads_or_requires_bun(tmp_path, monkeypatch, system, machine, target):
    installed = tmp_path / "site-packages/nanobot"
    launcher = installed / "cli/tui_launcher.py"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    monkeypatch.setattr(tui_launcher, "__file__", str(launcher))
    monkeypatch.delenv("NANOBOT_TUI_BIN", raising=False)
    monkeypatch.setenv("NANOBOT_TUI_NO_DOWNLOAD", "1")
    monkeypatch.setattr(tui_launcher.platform, "system", lambda: system)
    monkeypatch.setattr(tui_launcher.platform, "machine", lambda: machine)
    monkeypatch.setattr(tui_launcher, "os", SimpleNamespace(
        environ=tui_launcher.os.environ, name="nt" if system == "Windows" else "posix",
    ))
    asset = f"nanobot-tui-{target}" + (".exe" if system == "Windows" else "")
    binary = installed / "tui/bin" / asset
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"native")

    def unexpected(*args, **kwargs):
        pytest.fail("An installed platform wheel must not download or look for Bun")

    monkeypatch.setattr(tui_launcher, "_download_release_tui", unexpected)
    monkeypatch.setattr(tui_launcher.shutil, "which", unexpected)
    cache = tmp_path / "empty-cache"
    assert tui_launcher.resolve_tui_command(data_dir=cache) == [str(binary)]
    assert not cache.exists()


@pytest.fixture
def complete_candidate(tmp_path, candidate):
    """Actual checkout payload, with synthetic native binaries (not native execution)."""
    from hatch_build import WebUIBuildHook

    root = tmp_path / "checkout"
    subprocess.run(["git", "clone", "--shared", str(packager.ROOT), str(root)],
                   check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    metadata = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    wheel, info = candidate
    with zipfile.ZipFile(wheel) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "nanobot"], cwd=root).decode().split("\0")
    for name in filter(None, tracked):
        parts = name.split("/")
        if len(parts) > 3 and parts[1] == "channels" and parts[3] == "tests":
            continue
        files[name] = (root / name).read_bytes()
    hook = WebUIBuildHook(str(root), {}, None, {}, "", "wheel",
                          SimpleNamespace(display_info=lambda message: None))
    hook.initialize("editable", {})
    references = root / "nanobot/skills/nanobot-document/references"
    documentation = {}
    for reference in references.rglob("*.md"):
        files[reference.relative_to(root).as_posix()] = reference.read_bytes()
        name = "docs/" + reference.relative_to(references).as_posix()
        documentation[name] = (root / name).read_bytes()
    files[f"{info}/METADATA"] += f'Requires-Python: {metadata["requires-python"]}\n'.encode()
    files["nanobot/_build_commit.txt"] = f"{commit}\n".encode()
    files["nanobot/web/dist/index.html"] = b"<html>compiled fixture</html>"
    record = io.StringIO()
    writer = csv.writer(record)
    for name, content in files.items():
        if not name.endswith("/RECORD"):
            writer.writerow((name, packager._digest(content), len(content)))
    writer.writerow((f"{info}/RECORD", "", ""))
    files[f"{info}/RECORD"] = record.getvalue().encode()
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for target in packager.PLATFORMS:
        make_bundle(artifacts, target)
        packager.build_wheel(wheel, artifacts, artifacts, target, root=root)
    version = metadata["version"]
    source_files = {
        "PKG-INFO": files[f"{info}/METADATA"],
        "pyproject.toml": (root / "pyproject.toml").read_bytes(),
        **documentation,
        **{name: data for name, data in files.items() if name.startswith("nanobot/")},
    }
    with tarfile.open(artifacts / f"nanobot_ai-{version}.tar.gz", "w:gz") as archive:
        for name, data in source_files.items():
            member = tarfile.TarInfo(f"nanobot_ai-{version}/{name}")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return root, commit, artifacts


def test_complete_manifest_binds_wheels_sdist_and_fallback_archives(tmp_path, complete_candidate):
    """Real archive/RECORD checks, with synthetic binaries (not native execution)."""
    root, commit, artifacts = complete_candidate
    manifest = verify_candidate(root, artifacts, source_commit=commit)
    assert len(manifest.artifacts) == 16
    assert manifest.candidate_commit == commit
    output = artifacts / "release-manifest.json"
    write_manifest(manifest, output)
    original = output.read_bytes()
    write_manifest(verify_candidate(root, artifacts, source_commit=commit), output)
    assert output.read_bytes() == original
    with pytest.raises(FileExistsError):
        write_manifest(manifest.model_copy(update={"source_commit": "f" * 40}), output)
    guide = tmp_path / "install.md"
    write_install_guide(root, artifacts, guide, source_commit=commit)
    original_guide = guide.read_bytes()
    write_install_guide(root, artifacts, guide, source_commit=commit)
    assert guide.read_bytes() == original_guide
    assert commit.encode() in original_guide
    assert len(list(artifacts.iterdir())) == 17  # 16 artifacts and the manifest, no guide.
    with pytest.raises(ValueError, match="outside"):
        write_install_guide(root, artifacts, artifacts / "install.md", source_commit=commit)
    guide.write_text("previous reviewed handoff\n")
    with pytest.raises(FileExistsError, match="overwrite"):
        write_install_guide(root, artifacts, guide, source_commit=commit)
    assert guide.read_text() == "previous reviewed handoff\n"
    recorded = json.loads(original)
    recorded["artifacts"][0]["sha256"] = "f" * 64
    output.write_text(json.dumps(recorded))
    with pytest.raises(ValueError, match="recorded release manifest"):
        write_install_guide(root, artifacts, tmp_path / "unverified.md", source_commit=commit)
    assert not (tmp_path / "unverified.md").exists()
    output.write_bytes(original)
    damaged = artifacts / "nanobot-tui-linux-x64.zip.sha256"
    damaged.write_text("0" * 64 + "  nanobot-tui-linux-x64.zip\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_candidate(root, artifacts, source_commit=commit)
    with pytest.raises(ValueError, match="checksum mismatch"):
        write_install_guide(root, artifacts, tmp_path / "damaged.md", source_commit=commit)
    assert not (tmp_path / "damaged.md").exists()


def test_retained_candidate_keeps_checked_bytes_and_independent_source(tmp_path, complete_candidate):
    root, commit, artifacts = complete_candidate
    manifest = verify_candidate(root, artifacts, source_commit=commit)
    write_manifest(manifest, artifacts / "release-manifest.json")
    (root / "private-untracked.txt").write_text("not release input")
    output = tmp_path / "retained"
    retain_candidate(root, artifacts, output, source_commit=commit)
    identity = json.loads((output / "handoff.json").read_text())
    assert identity["candidate_commit"] == commit and identity["published"] is False
    assert identity["manifest_sha256"] == hashlib.sha256((artifacts / "release-manifest.json").read_bytes()).hexdigest()
    assert verify_candidate(root, output / "artifacts", source_commit=commit) == manifest
    for original in artifacts.iterdir():
        assert (output / "artifacts" / original.name).read_bytes() == original.read_bytes()
    independent = tmp_path / "independent"
    subprocess.run(["git", "clone", "--no-local", str(output / "source.git"), str(independent)],
                   check=True, capture_output=True)
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=independent, text=True).strip() == commit
    assert not (independent / "private-untracked.txt").exists()
    assert not (output / "source.git/objects/info/alternates").exists()
    assert str(root) not in (output / "source.git/config").read_text()
    assert verify_candidate(independent, output / "artifacts", source_commit=commit) == manifest
    with pytest.raises(FileExistsError):
        retain_candidate(root, artifacts, output, source_commit=commit)


def test_interrupted_retention_has_no_accepted_handoff(tmp_path, complete_candidate, monkeypatch):
    root, commit, artifacts = complete_candidate
    write_manifest(verify_candidate(root, artifacts, source_commit=commit), artifacts / "release-manifest.json")

    def interrupted_copy(source, target):
        raise OSError("controlled interrupted copy")

    monkeypatch.setattr(release_candidate.shutil, "copyfile", interrupted_copy)
    output = tmp_path / "interrupted"
    with pytest.raises(OSError, match="interrupted copy"):
        retain_candidate(root, artifacts, output, source_commit=commit)
    assert not (output / "handoff.json").exists()


@pytest.mark.parametrize("mutation", ["wheel-code", "wheel-webui", "source-code", "source-missing", "source-extra"])
def test_complete_candidate_rejects_mixed_or_incomplete_application_payload(tmp_path, complete_candidate, mutation):
    root, commit, artifacts = complete_candidate
    # These are intact archives with valid versions/commit markers and RECORDs.
    # A stale intermediate or a stray local file can still be packaged correctly.
    if mutation.startswith("wheel-"):
        wheel = next(artifacts.glob("*-macosx_13_0_arm64.whl"))
        with zipfile.ZipFile(wheel) as archive:
            entries = archive.infolist()
            files = {entry.filename: archive.read(entry) for entry in entries}
        name = "nanobot/__init__.py" if mutation == "wheel-code" else "nanobot/web/dist/index.html"
        files[name] += b"\n# stale build\n"
        record_name = next(name for name in files if name.endswith(".dist-info/RECORD"))
        record = io.StringIO()
        writer = csv.writer(record)
        for name, data in files.items():
            writer.writerow((name, "", "") if name == record_name else (name, packager._digest(data), len(data)))
        files[record_name] = record.getvalue().encode()
        with zipfile.ZipFile(wheel, "w") as archive:
            for entry in entries:
                archive.writestr(entry, files[entry.filename])
    else:
        source = next(artifacts.glob("nanobot_ai-*.tar.gz"))
        files = packager.source_files(source.read_bytes())
        module = next(name for name in files if name.endswith("/nanobot/agent/loop.py"))
        if mutation == "source-code":
            files[module] += b"\n# stale build\n"
        elif mutation == "source-missing":
            del files[module]
        else:
            files[module.split("/", 1)[0] + "/nanobot/local-settings.json"] = b'{"local": true}'
        with tarfile.open(source, "w:gz") as archive:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match="application payload"):
        verify_candidate(root, artifacts, source_commit=commit)
    assert not (artifacts / "release-manifest.json").exists()
