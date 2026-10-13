"""Release wheels carry a complete native bundle, with installable metadata."""

import csv
import hashlib
import io
import json
import runpy
import stat
import struct
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from nanobot.cli import tui_launcher
from scripts import build_tui_wheels as packager


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
