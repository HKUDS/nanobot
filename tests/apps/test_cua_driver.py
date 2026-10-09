from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest

from nanobot.apps import cua_driver
from nanobot.apps.cua_driver import CuaDriver, DriverError, Release


def package(target="linux-x86_64", *, unsafe=False, notices=True):
    release = Release(target, "")
    output = io.BytesIO()
    if target.startswith("windows-"):
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(f"{release.directory}/{release.executable}", b"driver")
            if notices:
                for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                    archive.writestr(f"{release.directory}/{name}", b"fixture license notice")
    else:
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            member = tarfile.TarInfo(f"{release.directory}/{release.executable}")
            member.size = 6
            member.mode = 0o755
            archive.addfile(member, io.BytesIO(b"driver"))
            if notices:
                for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                    notice = tarfile.TarInfo(f"{release.directory}/{name}")
                    notice.size = len(b"fixture license notice")
                    archive.addfile(notice, io.BytesIO(b"fixture license notice"))
            if unsafe:
                link = tarfile.TarInfo(f"{release.directory}/escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../../outside"
                archive.addfile(link)
    data = output.getvalue()
    return Release(target, hashlib.sha256(data).hexdigest()), data


def serve(monkeypatch, release, data):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=data)

    monkeypatch.setattr(cua_driver, "host_release", lambda: release)
    monkeypatch.setattr(cua_driver, "PinnedDNSAsyncTransport", lambda: httpx.MockTransport(handler))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["darwin-universal", "linux-x86_64", "linux-arm64", "windows-x86_64", "windows-arm64"])
async def test_install_is_verified_idempotent_and_does_not_enable(tmp_path, monkeypatch, target):
    from unittest.mock import AsyncMock

    release, data = package(target)
    requests = serve(monkeypatch, release, data)
    spawn = AsyncMock(return_value=AsyncMock(wait=AsyncMock(return_value=0)))
    monkeypatch.setattr(cua_driver.asyncio, "create_subprocess_exec", spawn)
    driver = CuaDriver(tmp_path / "config.json")
    await driver.install()
    assert driver.executable.read_bytes() == b"driver"
    for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        assert (driver.directory / notice).read_bytes() == b"fixture license notice"
    assert driver.info(None)["installed"]
    assert driver.info(None)["mode"] == "off"
    assert driver.info(None)["permission_app"] == "CuaDriver"
    assert not driver.config_path.exists()
    await driver.install()
    assert len(requests) == 1
    if target.startswith("darwin-"):
        # Only verify the unmodified upstream bundle; installation never launches it.
        spawn.assert_awaited_once()
        assert spawn.call_args.args[:4] == ("/usr/bin/codesign", "--verify", "--deep", "--strict")
        assert Path(spawn.call_args.args[4]).name == "CuaDriver.app"
        assert list(driver.directory.glob("*.app")) == [driver.directory / "CuaDriver.app"]
    else:
        spawn.assert_not_awaited()
    config = driver.configuration("observe")
    assert config.enabled_tools == cua_driver.OBSERVE_TOOLS
    assert config.retry_tool_calls is False and config.image_output == "inline"
    assert "click" not in config.enabled_tools
    assert "check_permissions" not in config.enabled_tools  # setup is never agent-controlled
    assert driver.owns(config)
    assert "click" in driver.configuration("control").enabled_tools


@pytest.mark.asyncio
async def test_macos_signature_failure_does_not_install_or_resign(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    release, data = package("darwin-universal")
    serve(monkeypatch, release, data)
    spawn = AsyncMock(return_value=AsyncMock(wait=AsyncMock(return_value=1)))
    monkeypatch.setattr(cua_driver.asyncio, "create_subprocess_exec", spawn)
    driver = CuaDriver(tmp_path / "config.json")
    with pytest.raises(DriverError, match="signature verification failed"):
        await driver.install()
    assert not driver.directory.exists()
    assert not driver.config_path.exists()
    spawn.assert_awaited_once()
    assert spawn.call_args.args[:4] == ("/usr/bin/codesign", "--verify", "--deep", "--strict")


@pytest.mark.asyncio
async def test_checksum_failure_publishes_nothing_and_can_retry(tmp_path, monkeypatch):
    release, data = package()
    serve(monkeypatch, release, data + b"tampered")
    driver = CuaDriver(tmp_path / "config.json")
    with pytest.raises(DriverError, match="checksum"):
        await driver.install()
    assert not driver.directory.exists()
    assert list(driver.root.glob("install-*")) == []
    serve(monkeypatch, release, data)
    await driver.install()
    assert driver.installed()


@pytest.mark.asyncio
async def test_package_missing_license_notices_is_not_installed(tmp_path, monkeypatch):
    release, data = package(notices=False)
    serve(monkeypatch, release, data)
    driver = CuaDriver(tmp_path / "config.json")
    with pytest.raises(DriverError, match="license notices"):
        await driver.install()
    assert not driver.directory.exists()


@pytest.mark.asyncio
async def test_archive_cannot_escape_staging(tmp_path, monkeypatch):
    release, data = package(unsafe=True)
    serve(monkeypatch, release, data)
    driver = CuaDriver(tmp_path / "config.json")
    with pytest.raises(DriverError, match="safely unpacked"):
        await driver.install()
    assert not driver.directory.exists()
    assert not (tmp_path / "outside").exists()


@pytest.mark.asyncio
async def test_install_does_not_overwrite_unverified_or_redirected_directory(tmp_path, monkeypatch):
    release, data = package()
    requests = serve(monkeypatch, release, data)
    driver = CuaDriver(tmp_path / "config.json")
    driver.directory.mkdir(parents=True)
    user_file = driver.directory / "keep.txt"
    user_file.write_text("keep")
    with pytest.raises(DriverError, match="not been overwritten"):
        await driver.install()
    assert user_file.read_text() == "keep"
    assert not requests
    isolated = tmp_path / "other"
    isolated.mkdir()
    (isolated / "apps").symlink_to(tmp_path / "apps", target_is_directory=True)
    with pytest.raises(DriverError, match="outside"):
        await CuaDriver(isolated / "config.json").install()


def test_supported_host_selects_pinned_package(monkeypatch):
    for system, arch, target in [
        ("Darwin", "arm64", "darwin-universal"), ("Darwin", "x86_64", "darwin-universal"),
        ("Windows", "AMD64", "windows-x86_64"), ("Windows", "ARM64", "windows-arm64"),
        ("Linux", "aarch64", "linux-arm64"), ("Linux", "x86_64", "linux-x86_64"),
    ]:
        monkeypatch.setattr(cua_driver.platform, "system", lambda: system)
        monkeypatch.setattr(cua_driver.platform, "machine", lambda: arch)
        monkeypatch.setattr(cua_driver.platform, "mac_ver", lambda: ("14.0", (), ""))
        selected = cua_driver.host_release()
        assert selected is not None and selected.target == target
        assert len(selected.digest) == 64


@pytest.mark.asyncio
async def test_installer_refuses_concurrent_download(tmp_path, monkeypatch):
    from filelock import FileLock

    release, data = package()
    requests = serve(monkeypatch, release, data)
    driver = CuaDriver(tmp_path / "config.json")
    driver.root.mkdir(parents=True)
    with FileLock(str(driver.root / "install.lock")):
        with pytest.raises(DriverError, match="already being installed"):
            await driver.install()
    assert not requests


@pytest.mark.asyncio
async def test_cancelled_download_leaves_no_partial_install(tmp_path, monkeypatch):
    import asyncio

    started = asyncio.Event()

    async def download(_release: Release, destination: Path):
        destination.write_bytes(b"partial")
        started.set()
        await asyncio.Event().wait()

    release, _ = package()
    monkeypatch.setattr(cua_driver, "host_release", lambda: release)
    monkeypatch.setattr(cua_driver, "_download", download)
    driver = CuaDriver(tmp_path / "config.json")
    task = asyncio.create_task(driver.install())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not driver.directory.exists()
    assert list(driver.root.glob("install-*")) == []


@pytest.mark.skipif(cua_driver.platform.system() != "Darwin", reason="macOS app/socket launch")
def test_mcp_sanitized_environment_keeps_same_private_endpoint(tmp_path):
    import os
    import subprocess
    import sys

    from nanobot.apps.cua_driver_stdio import endpoint

    path = tmp_path / "config.json"
    address = endpoint(path)
    try:
        child = subprocess.check_output([
            sys.executable, "-c",
            "from pathlib import Path; import sys; from nanobot.apps.cua_driver_stdio import endpoint; print(endpoint(Path(sys.argv[1])))",
            str(path),
        ], env={"PATH": os.defpath}, text=True).strip()
        assert child == str(address)
        assert address.parent.stat().st_mode & 0o077 == 0
        assert endpoint(tmp_path / "other.json") != address
    finally:
        address.parent.rmdir()
        endpoint(tmp_path / "other.json").parent.rmdir()


@pytest.mark.skipif(cua_driver.platform.system() != "Darwin", reason="macOS app/socket launch")
def test_macos_launch_uses_exact_upstream_bundle_and_private_proxy(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from nanobot.apps import cua_driver_stdio
    from nanobot.config.loader import save_config
    from nanobot.config.schema import Config

    path = tmp_path / "中文 gateway" / "config.json"
    monkeypatch.setattr(CuaDriver, "installed", lambda self: True)
    monkeypatch.setattr(cua_driver, "host_release", lambda: cua_driver._RELEASES["darwin-universal"])
    driver = CuaDriver(path)
    config = Config()
    config.tools.mcp_servers["cua-driver"] = driver.configuration("observe")
    save_config(config, path)
    address = tmp_path / "driver.sock"
    monkeypatch.setattr(cua_driver_stdio, "endpoint", lambda path: address)
    monkeypatch.setattr(cua_driver_stdio, "daemon_listening", Mock(side_effect=[False, True]))
    run, execute = Mock(), Mock()
    monkeypatch.setattr(cua_driver_stdio.subprocess, "run", run)
    monkeypatch.setattr(cua_driver_stdio.os, "execve", execute)

    assert cua_driver_stdio.launch(path) == 0
    run.assert_called_once()
    command = run.call_args.args[0]
    assert command[:3] == ["/usr/bin/open", "-n", "-g"]
    assert command[command.index("-a"):] == [
        "-a", str(driver.directory / "CuaDriver.app"), "--args", "serve",
        "--socket", str(address), "--pid-file", str(address.with_suffix(".pid")),
    ]
    assert "DO_NOT_TRACK=1" in command
    execute.assert_called_once()
    assert execute.call_args.args[:2] == (driver.executable, [
        str(driver.executable), "mcp", "--embedded", "--socket", str(address),
    ])


def test_read_only_check_does_not_launch_app_or_substitute_terminal_grants(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from nanobot.apps import cua_driver_stdio

    monkeypatch.setattr(CuaDriver, "installed", lambda self: True)
    monkeypatch.setattr(cua_driver_stdio.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cua_driver_stdio, "endpoint", lambda path: tmp_path / "driver.sock")
    monkeypatch.setattr(cua_driver_stdio, "daemon_listening", lambda path: False)
    run = Mock()
    monkeypatch.setattr(cua_driver_stdio.subprocess, "run", run)
    with pytest.raises(DriverError, match="not running"):
        cua_driver_stdio.launch(tmp_path / "config.json", check=True)
    run.assert_not_called()


def test_disabled_access_cannot_be_relaunched_by_stale_mcp_connection(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from nanobot.apps import cua_driver_stdio
    from nanobot.config.loader import save_config
    from nanobot.config.schema import Config

    path = tmp_path / "config.json"
    config = Config()
    monkeypatch.setattr(CuaDriver, "installed", lambda self: True)
    monkeypatch.setattr(cua_driver_stdio.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cua_driver, "host_release", lambda: cua_driver._RELEASES["linux-x86_64"])
    execute = Mock()
    if cua_driver_stdio.os.name == "nt":
        monkeypatch.setattr(cua_driver_stdio.subprocess, "call", execute)
    else:
        monkeypatch.setattr(cua_driver_stdio.os, "execve", execute)
    # A connected managed configuration can start the driver.
    config.tools.mcp_servers["cua-driver"] = CuaDriver(path).configuration("control")
    save_config(config, path)
    cua_driver_stdio.launch(path)
    execute.assert_called_once()
    # Removing configured access is authoritative even for a stale launcher.
    config.tools.mcp_servers.clear()
    save_config(config, path)
    with pytest.raises(DriverError, match="disabled"):
        cua_driver_stdio.launch(path)
    execute.assert_called_once()


def test_waiting_macos_launcher_rechecks_access_after_acquiring_lifecycle_lock(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import Mock

    from filelock import FileLock

    from nanobot.apps import cua_driver_stdio
    from nanobot.config.loader import load_config, save_config
    from nanobot.config.schema import Config

    path = tmp_path / "config.json"
    address = tmp_path / "driver.sock"
    monkeypatch.setattr(CuaDriver, "installed", lambda self: True)
    monkeypatch.setattr(cua_driver_stdio.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cua_driver_stdio, "endpoint", lambda path: address)
    monkeypatch.setattr(cua_driver_stdio, "daemon_listening", lambda path: True)
    execute = Mock()
    monkeypatch.setattr(cua_driver_stdio.os, "execve", execute)
    monkeypatch.setattr(cua_driver_stdio.subprocess, "call", execute)
    config = Config()
    config.tools.mcp_servers["cua-driver"] = CuaDriver(path).configuration("observe")
    save_config(config, path)
    read_enabled = threading.Event()

    def read(path):
        value = load_config(path)
        read_enabled.set()
        return value

    monkeypatch.setattr(cua_driver_stdio, "load_config", read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with FileLock(str(address.with_suffix(".lock"))):
            pending = pool.submit(cua_driver_stdio.launch, path)
            assert read_enabled.wait(3)
            config.tools.mcp_servers.clear()
            save_config(config, path)
        with pytest.raises(DriverError, match="disabled"):
            pending.result(timeout=3)
    execute.assert_not_called()


@pytest.mark.asyncio
async def test_stopping_waits_for_managed_launch_and_stops_only_its_socket(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import Mock

    from filelock import FileLock

    from nanobot.apps import cua_driver_stdio

    address = tmp_path / "driver.sock"
    monkeypatch.setattr(CuaDriver, "installed", lambda self: True)
    monkeypatch.setattr(cua_driver.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cua_driver, "host_release", lambda: cua_driver._RELEASES["darwin-universal"])
    monkeypatch.setattr(cua_driver_stdio, "endpoint", lambda path: address)
    monkeypatch.setattr(cua_driver_stdio, "daemon_listening", lambda path: True)
    run = Mock()
    monkeypatch.setattr(cua_driver_stdio.subprocess, "run", run)
    driver = CuaDriver(tmp_path / "config.json")
    with FileLock(str(address.with_suffix(".lock"))):
        stopping = asyncio.create_task(driver.stop())
        await asyncio.sleep(0.02)
        run.assert_not_called()
    await asyncio.wait_for(stopping, 3)
    assert run.call_args.args[0] == [str(driver.executable), "stop", "--socket", str(address)]


@pytest.mark.asyncio
async def test_pending_permission_check_does_not_launch_or_claim_grants(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from nanobot.apps import cua_driver_stdio

    monkeypatch.setattr(CuaDriver, "installed", lambda self: True)
    monkeypatch.setattr(cua_driver.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cua_driver_stdio, "endpoint", lambda path: tmp_path / "driver.sock")
    monkeypatch.setattr(cua_driver_stdio, "daemon_listening", lambda path: False)
    spawn = AsyncMock()
    monkeypatch.setattr(cua_driver.asyncio, "create_subprocess_exec", spawn)
    assert await CuaDriver(tmp_path / "config.json").check() == {
        "connected": False, "accessibility": None, "screen_recording": None, "capture_verified": False,
    }
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_setup_opens_only_fixed_panes_or_this_gateways_bundle(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(CuaDriver, "installed", lambda self: True)
    monkeypatch.setattr(cua_driver.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cua_driver, "host_release", lambda: cua_driver._RELEASES["darwin-universal"])
    spawn = AsyncMock(return_value=AsyncMock(wait=AsyncMock(return_value=0)))
    monkeypatch.setattr(cua_driver.asyncio, "create_subprocess_exec", spawn)
    driver = CuaDriver(tmp_path / "config.json")
    await driver.open_setup("finder")
    assert spawn.call_args.args == ("/usr/bin/open", "-R", str(driver.directory / "CuaDriver.app"))
    for target, pane in [("accessibility", "Privacy_Accessibility"), ("screen_recording", "Privacy_ScreenCapture")]:
        await driver.open_setup(target)
        assert spawn.call_args.args == ("/usr/bin/open", f"x-apple.systempreferences:com.apple.preference.security?{pane}")
    with pytest.raises(DriverError, match="Choose"):
        await driver.open_setup("https://example.com")
    assert spawn.await_count == 3
    monkeypatch.setattr(cua_driver.platform, "system", lambda: "Linux")
    with pytest.raises(DriverError, match="macOS"):
        await driver.open_setup("finder")
    assert spawn.await_count == 3


@pytest.mark.asyncio
@pytest.mark.skipif(cua_driver.platform.system() != "Darwin", reason="macOS staged permission request")
async def test_permission_request_uses_exact_signed_app_without_capture_or_bypass(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from nanobot.apps import cua_driver_stdio

    monkeypatch.setattr(CuaDriver, "installed", lambda self: True)
    temporary = tmp_path / "private socket"
    temporary.mkdir(mode=0o700)
    monkeypatch.setattr(cua_driver_stdio, "endpoint", lambda path: temporary / "driver.sock")
    spawn = AsyncMock(return_value=AsyncMock(wait=AsyncMock(return_value=0)))
    monkeypatch.setattr(cua_driver.asyncio, "create_subprocess_exec", spawn)
    driver = CuaDriver(tmp_path / "中文 config.json")
    await driver.request_permissions()
    args = spawn.call_args.args
    assert args[0:3] == ("/usr/bin/open", "-n", "-g")
    assert args[args.index("-a") + 1] == str(driver.directory / "CuaDriver.app")
    assert args[args.index("--args") + 1] == "__permissions-host-request"
    assert f"TMPDIR={temporary}" in args
    assert "DO_NOT_TRACK=1" in args
    assert "--probe-direct-capture" not in args and "--no-permissions-gate" not in args
    result = Path(args[args.index("--result-file") + 1])
    assert result.parent == temporary and result.stat().st_mode & 0o077 == 0
    await driver.request_permissions()
    assert list(temporary.iterdir()) == [result]  # no unbounded result-file accumulation
    result.unlink()
    untouched = tmp_path / "keep"
    untouched.write_text("keep")
    result.symlink_to(untouched)
    with pytest.raises(OSError):
        await driver.request_permissions()
    assert untouched.read_text() == "keep"
    assert spawn.await_count == 2
