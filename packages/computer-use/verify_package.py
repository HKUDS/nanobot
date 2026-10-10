"""Exercise the real installer lifecycle without requesting desktop access."""
import asyncio
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from package_materials import verified_bundle

from nanobot.apps import computer_use_native
from nanobot.apps.computer_use_native import NativeConnection, admin
from nanobot.apps.cua_driver import CuaDriver, DriverError
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


async def verify(manifest: Path, runtime: bool):
    verified_bundle(manifest.parent, platform.machine().lower())
    # Exercise the default distribution path, without per-gateway staging.
    computer_use_native.BUNDLE_DIR = manifest.parent.resolve()
    with tempfile.TemporaryDirectory(prefix="nb-package-", dir="/tmp") as directory:
        config_path = Path(directory) / "config.json"
        save_config(Config(), config_path)
        driver = CuaDriver(config_path)
        assert driver.native and not driver.installed()
        await driver.install()
        assert driver.installed()
        assert not (driver.root / "native-package.json").exists()
        assert not load_config(config_path).tools.mcp_servers
        subprocess.run([str(driver.executable), "--version"], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(driver.bundle)], check=True)
        resources = driver.bundle / "Contents/Resources"
        assert (resources / "Cua-MIT-LICENSE.md").read_bytes() == (driver.directory / "LICENSE").read_bytes()
        assert (resources / "MPL-SOURCES.tar.gz").stat().st_size > 0
        config = load_config(config_path)
        config.tools.mcp_servers["cua-driver"] = driver.configuration("observe")
        save_config(config, config_path)
        if runtime:
            from nanobot.apps.cua_driver_stdio import ensure_daemon

            try:
                address = await asyncio.to_thread(ensure_daemon, driver)
                status = await driver.check()
                assert status["connected"] and not status["capture_verified"]
                tools = await admin(address, "list")
                names = {tool["name"] for tool in tools["tools"]}
                assert names == {"list_windows", "get_window_state", "get_accessibility_tree", "zoom"}
                channel = NativeConnection(address)
                try:
                    await channel.request("call", name="click", arguments={"pid": 1, "window_id": 1})
                except RuntimeError as exc:
                    assert "not allowed" in str(exc)
                else:
                    raise AssertionError("Observation mode must refuse input before dispatch")
                finally:
                    await channel.close()
                await driver.stop()
                assert address.with_suffix(".paused").exists()
                try:
                    await asyncio.to_thread(ensure_daemon, driver)
                except DriverError as exc:
                    assert "Sharing was stopped" in str(exc)
                else:
                    raise AssertionError("A stopped runtime must not automatically restart")
                print(json.dumps({"native_status": status, "observation_tools": sorted(names),
                    "input_denied": True, "stop_latched": True, "screenshots": 0}))
            finally:
                await driver.stop()
        try:
            await driver.uninstall()
        except DriverError:
            pass
        else:
            raise AssertionError("Uninstall must refuse an enabled connection")
        config.tools.mcp_servers.clear()
        save_config(config, config_path)
        unrelated = driver.root / "other-app.txt"
        unrelated.write_text("preserve")
        await driver.uninstall()
        assert not driver.directory.exists() and unrelated.read_text() == "preserve"
        await driver.install()
        assert driver.installed()
        await driver.uninstall()
        assert not driver.directory.exists()
        print(json.dumps({"default_bundled_install": True, "signature": True, "notices": True,
            "enabled_uninstall_refused": True, "uninstall": True, "reinstall": True,
            "other_files_preserved": True, "runtime_started": runtime, "desktop_captured": False}))


if __name__ == "__main__":
    asyncio.run(verify(Path(sys.argv[1]), "--runtime" in sys.argv[2:]))
