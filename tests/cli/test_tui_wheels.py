"""Release wheels carry a complete native bundle, with installable metadata."""

import csv
import hashlib
import io
import json
import plistlib
import runpy
import stat
import struct
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.cli import tui_launcher
from scripts import build_tui_wheels as packager
from scripts.computer_use_release import verified_bundle


def make_computer_use_bundle(directory, target, *, omit=None):
    from nanobot.apps.computer_use_native import APP, REVISION, VERSION

    output = directory / target
    output.mkdir()
    source = runpy.run_path(str(packager.ROOT / "native/computer-use/package_materials.py"))["application_source"]()
    prefix = f"nanobot-computer-use-{VERSION}-darwin/"
    contents = prefix + APP + "/Contents/"
    resources = contents + "Resources/"
    binary = b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C if target.endswith("arm64") else 0x01000007)
    mpl = io.BytesIO()
    with tarfile.open(fileobj=mpl, mode="w:gz") as archive:
        for name in ("LICENSE-MPL-2.0", "uniffi_core-0.31.0/src/lib.rs"):
            member = tarfile.TarInfo(name)
            member.size = 7
            archive.addfile(member, io.BytesIO(b"fixture"))
    notices = b"fixture: yabai; Steven Sheldon; Inter Project Authors; Mozilla Public License Version 2.0"
    files = {
        prefix + "LICENSE": b"fixture license",
        prefix + "THIRD_PARTY_NOTICES.md": notices,
        contents + "Info.plist": plistlib.dumps({"CFBundleIdentifier": "io.nanobot.computer-use",
            "CFBundleDisplayName": "nanobot Computer Use", "LSMinimumSystemVersion": "14.2"}),
        contents + "MacOS/nanobot-computer-use": binary,
        contents + "_CodeSignature/CodeResources": b"fixture signature",
        resources + "NANOBOT-SOURCES.tar": source,
        resources + "MPL-SOURCES.tar.gz": mpl.getvalue(),
        resources + "THIRD_PARTY_NOTICES.md": notices,
    }
    for name in ("Cua-MIT-LICENSE.md", "nanobot-MIT-LICENSE", "PROVENANCE.md", "AppIcon.png",
                 "cursor-themes/io.nanobot.computer-use.cua-theme", "RUST-NOTICES.txt", "RUST-COPYRIGHT-library.html"):
        files[resources + name] = b"fixture material"
    if omit:
        files.pop(resources + omit)
    archive_path = output / "native-package.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    (output / "native-package.json").write_text(json.dumps({
        "schema": 1, "version": VERSION, "revision": REVISION, "profile": "release", "minimum_macos": "14.2",
        "architecture": "arm64" if target.endswith("arm64") else "x86_64",
        "archive": archive_path.name, "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(source).hexdigest(),
    }))
    return output


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
    if target.startswith("darwin-"):
        make_computer_use_bundle(tmp_path, target)
    output = packager.build_wheel(wheel, tmp_path, tmp_path / "wheels", target, computer_use_dir=tmp_path)
    assert output.name.endswith(f"-py3-none-{packager.PLATFORMS[target]}.whl")
    with zipfile.ZipFile(output) as archive:
        metadata = BytesParser().parsebytes(archive.read(f"{info}/WHEEL"))
        assert metadata["Root-Is-Purelib"] == "false"
        assert metadata.get_all("Tag") == [f"py3-none-{packager.PLATFORMS[target]}"]
        native = [name for name in archive.namelist() if name.startswith("nanobot/apps/computer_use_bundle/")]
        assert len(native) == (2 if target.startswith("darwin-") else 0)
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
        packager.build_wheel(wheel, tmp_path, output.parent, target, computer_use_dir=tmp_path)


def test_mac_wheel_refuses_missing_native_payload(tmp_path, candidate):
    make_bundle(tmp_path, "darwin-arm64")
    with pytest.raises(ValueError, match="--computer-use-dir"):
        packager.build_wheel(candidate[0], tmp_path, tmp_path / "wheels", "darwin-arm64")
    assert not list((tmp_path / "wheels").glob("*.whl"))


@pytest.mark.parametrize("omitted", ["Cua-MIT-LICENSE.md", "MPL-SOURCES.tar.gz", "NANOBOT-SOURCES.tar", "RUST-NOTICES.txt"])
def test_native_package_refuses_missing_compliance_material(tmp_path, omitted):
    directory = make_computer_use_bundle(tmp_path, "darwin-arm64", omit=omitted)
    with pytest.raises(ValueError, match="missing.*material"):
        verified_bundle(directory, "arm64")


def test_native_package_refuses_stale_source_and_wrong_architecture(tmp_path):
    directory = make_computer_use_bundle(tmp_path, "darwin-arm64")
    with pytest.raises(ValueError, match="manifest is invalid"):
        verified_bundle(directory, "x86_64")
    manifest = directory / "native-package.json"
    value = json.loads(manifest.read_text())
    value["source_sha256"] = "0" * 64
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="sources do not match"):
        verified_bundle(directory, "arm64")


@pytest.mark.asyncio
async def test_default_native_install_is_inert_pinned_and_reinstallable(tmp_path, monkeypatch):
    from nanobot.apps import computer_use_native, cua_driver
    from nanobot.config.loader import load_config, save_config
    from nanobot.config.schema import Config

    directory = make_computer_use_bundle(tmp_path, "darwin-arm64")
    monkeypatch.setattr(computer_use_native, "BUNDLE_DIR", directory)
    monkeypatch.setattr(cua_driver.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cua_driver.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(cua_driver.platform, "mac_ver", lambda: ("14.2", (), ""))
    spawn = AsyncMock(return_value=AsyncMock(wait=AsyncMock(return_value=0)))
    monkeypatch.setattr(cua_driver.asyncio, "create_subprocess_exec", spawn)
    config_path = tmp_path / "instance/config.json"
    save_config(Config(), config_path)
    driver = cua_driver.CuaDriver(config_path)
    assert driver.native and not driver.installed()
    await driver.install()  # No register_package or config-specific staging.
    assert driver.installed() and not load_config(config_path).tools.mcp_servers
    assert spawn.call_args.args[:4] == ("/usr/bin/codesign", "--verify", "--deep", "--strict")
    assert spawn.call_count == 1
    assert not (driver.root / "native-package.json").exists()
    cfg = load_config(config_path)
    cfg.tools.mcp_servers["cua-driver"] = driver.configuration("observe")
    save_config(cfg, config_path)
    with pytest.raises(cua_driver.DriverError, match="Disable Computer Use"):
        await driver.uninstall()
    cfg.tools.mcp_servers.clear()
    save_config(cfg, config_path)
    # A Python distribution update cannot silently replace the installed native identity.
    manifest = directory / "native-package.json"
    original = manifest.read_text()
    value = json.loads(original)
    value["sha256"] = "a" * 64
    manifest.write_text(json.dumps(value))
    existing = cua_driver.CuaDriver(config_path)
    assert existing.installed() and existing.release == driver.release
    monkeypatch.setattr(existing, "stop", AsyncMock())
    await existing.uninstall()
    with pytest.raises(cua_driver.DriverError, match="checksum failed"):
        await cua_driver.CuaDriver(config_path).install()
    assert not existing.directory.exists()
    manifest.write_text(original)
    fresh = cua_driver.CuaDriver(config_path)
    await fresh.install()
    assert fresh.installed() and not load_config(config_path).tools.mcp_servers


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
