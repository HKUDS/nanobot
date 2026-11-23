from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from nanobot.apps.cli import service as cli_service
from nanobot.config import home, loader
from nanobot.webui import cli_apps_api


class _FakeManager:
    def __init__(
        self,
        *,
        fresh: bool,
        apps: list[dict[str, Any]] | None = None,
        all_sources_fresh: bool | None = None,
    ) -> None:
        self.fresh = fresh
        self.all_sources_fresh = fresh if all_sources_fresh is None else all_sources_fresh
        self.apps = apps or []
        self.payload_calls: list[bool] = []
        self.fresh_checks: list[bool] = []

    def payload(self, *, cache_only: bool = False) -> dict[str, Any]:
        self.payload_calls.append(cache_only)
        return {
            "apps": list(self.apps),
            "installed_count": 0,
            "catalog_updated_at": "2026-04-18" if self.apps else None,
        }

    def catalog_cache_fresh(self, *, include_optional: bool = False) -> bool:
        self.fresh_checks.append(include_optional)
        return self.all_sources_fresh if include_optional else self.fresh

    def installed_payload(self) -> dict[str, Any]:
        return {
            "apps": [
                {
                    "name": "gimp",
                    "display_name": "GIMP",
                    "category": "image",
                    "description": "Image editing",
                    "requires": "Python",
                    "source": "local",
                    "entry_point": "cli-anything-gimp",
                    "install_supported": True,
                    "installed": True,
                    "available": True,
                    "status": "installed",
                    "logo_url": None,
                    "brand_color": None,
                    "skill_installed": True,
                }
            ],
            "installed_count": 1,
            "catalog_updated_at": None,
        }


def test_cli_apps_payload_uses_cache_and_marks_refresh_pending(monkeypatch) -> None:
    manager = _FakeManager(fresh=False)
    refreshes = []
    monkeypatch.setattr(cli_apps_api, "_manager", lambda: manager)
    monkeypatch.setattr(
        cli_apps_api,
        "_start_catalog_refresh",
        lambda _manager: refreshes.append(True) or True,
    )

    payload = asyncio.run(cli_apps_api.cli_apps_payload())

    assert manager.payload_calls == [True]
    assert manager.fresh_checks == [True]
    assert refreshes == [True]
    assert payload["catalog_refresh_pending"] is True
    assert payload["apps"][0]["name"] == "gimp"


def test_cli_apps_payload_skips_refresh_when_cache_is_fresh(monkeypatch) -> None:
    manager = _FakeManager(
        fresh=True,
        apps=[
            {
                "name": "gimp",
                "display_name": "GIMP",
                "category": "image",
                "description": "Image editing",
                "requires": "Python",
                "source": "harness",
                "entry_point": "cli-anything-gimp",
                "install_supported": True,
                "installed": False,
                "available": False,
                "status": "not_installed",
                "logo_url": None,
                "brand_color": None,
                "skill_installed": False,
            }
        ],
    )
    refreshes = []
    monkeypatch.setattr(cli_apps_api, "_manager", lambda: manager)
    monkeypatch.setattr(
        cli_apps_api,
        "_start_catalog_refresh",
        lambda _manager: refreshes.append(True) or True,
    )

    payload = asyncio.run(cli_apps_api.cli_apps_payload())

    assert manager.payload_calls == [True]
    assert manager.fresh_checks == [True]
    assert refreshes == []
    assert payload["catalog_refresh_pending"] is False
    assert payload["apps"][0]["source"] == "harness"


def test_cli_apps_payload_refreshes_when_optional_cache_is_stale(monkeypatch) -> None:
    manager = _FakeManager(
        fresh=True,
        all_sources_fresh=False,
        apps=[
            {
                "name": "gimp",
                "display_name": "GIMP",
                "category": "image",
                "description": "Image editing",
                "requires": "Python",
                "source": "harness",
                "entry_point": "cli-anything-gimp",
                "install_supported": True,
                "installed": False,
                "available": False,
                "status": "not_installed",
                "logo_url": None,
                "brand_color": None,
                "skill_installed": False,
            }
        ],
    )
    refreshes = []
    monkeypatch.setattr(cli_apps_api, "_manager", lambda: manager)
    monkeypatch.setattr(
        cli_apps_api,
        "_start_catalog_refresh",
        lambda _manager: refreshes.append(True) or True,
    )

    payload = asyncio.run(cli_apps_api.cli_apps_payload())

    assert manager.payload_calls == [True]
    assert manager.fresh_checks == [True]
    assert refreshes == [True]
    assert payload["catalog_refresh_pending"] is True
    assert payload["apps"][0]["source"] == "harness"


def test_cli_apps_payload_reports_not_pending_when_refresh_is_throttled(monkeypatch) -> None:
    manager = _FakeManager(fresh=False)
    monkeypatch.setattr(cli_apps_api, "_manager", lambda: manager)
    monkeypatch.setattr(cli_apps_api, "_start_catalog_refresh", lambda _manager: False)

    payload = asyncio.run(cli_apps_api.cli_apps_payload())

    assert manager.payload_calls == [True]
    assert manager.fresh_checks == [True]
    assert payload["catalog_refresh_pending"] is False
    assert payload["apps"][0]["name"] == "gimp"


@pytest.fixture
def _local_cli_apps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    instance = tmp_path / "home" / ".nanobot"
    workspace = tmp_path / "workspace"
    bin_dir = tmp_path / "bin"
    for path in (instance, workspace, bin_dir):
        path.mkdir(parents=True)
    config_path = instance / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(workspace)}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(instance.parent))
    monkeypatch.setenv("USERPROFILE", str(instance.parent))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    monkeypatch.setattr(home, "_home_path", instance)
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    executable = bin_dir / ("fixture-slow-cli.cmd" if os.name == "nt" else "fixture-slow-cli")
    executable.write_text("fixture executable; never executed\n", encoding="utf-8")
    executable.chmod(0o755)
    manager = cli_service.CliAppManager(workspace=workspace)
    for source in ("harness", "public", "extensions"):
        rows = [
            {"name": "gimp", "display_name": "GIMP", "entry_point": "fixture-slow-cli",
             "package_manager": "bundled", "category": "image"},
            {"name": "other", "entry_point": "fixture-other-cli", "package_manager": "bundled"},
        ] if source == "harness" else []
        manager._cache_path(source).write_text(json.dumps({
            "_cached_at": 0 if source == "extensions" else time.time(),
            "data": {"meta": {"updated": "2026-10-17"}, "clis": rows},
        }), encoding="utf-8")
    manager._save_installed({
        "gimp": {"entry_point": "fixture-slow-cli", "source": "harness", "strategy": "bundled"},
    })
    skill = workspace / "skills" / "cli-app-gimp" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# GIMP\n", encoding="utf-8")

    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("local CLI Apps reads must not use the network")

    monkeypatch.setattr(cli_service.httpx, "get", no_network)
    monkeypatch.setattr(cli_service.httpx, "AsyncClient", no_network)
    return config_path


class _HeldProbe:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.watchdog_fired = threading.Event()
        self.calls: list[tuple[str, int]] = []
        real_which = cli_service.shutil.which

        def which(command: str) -> str | None:
            self.calls.append((command, threading.get_ident()))
            if command == "fixture-slow-cli":
                loop.call_soon_threadsafe(self.entered.set)
                self.release.wait()
            return real_which(command)

        def watchdog_release() -> None:
            self.watchdog_fired.set()
            self.release.set()

        monkeypatch.setattr(cli_service.shutil, "which", which)
        self.watchdog = threading.Timer(5, watchdog_release)
        self.watchdog.start()

    def close(self) -> None:
        self.release.set()
        self.watchdog.cancel()
        self.watchdog.join()


@pytest.mark.parametrize("installed_only", [False, True], ids=["full", "installed"])
def test_cli_apps_payload_keeps_loop_responsive(
    _local_cli_apps: Path,
    monkeypatch: pytest.MonkeyPatch,
    installed_only: bool,
) -> None:
    observed: dict[str, list[int]] = {name: [] for name in ("config", "manager", "cache", "freshness")}
    real_load = cli_apps_api.load_config
    real_init = cli_service.CliAppManager.__init__
    real_read = cli_service._read_json
    real_freshness = cli_service.CliAppManager.catalog_cache_fresh

    def load(config_path: Path | None = None) -> Any:
        observed["config"].append(threading.get_ident())
        return real_load(config_path)

    def initialize(manager: cli_service.CliAppManager, **kwargs: Any) -> None:
        observed["manager"].append(threading.get_ident())
        real_init(manager, **kwargs)

    def read(path: Path) -> Any:
        observed["cache"].append(threading.get_ident())
        return real_read(path)

    def freshness(manager: cli_service.CliAppManager, *, include_optional: bool = False) -> bool:
        observed["freshness"].append(threading.get_ident())
        return real_freshness(manager, include_optional=include_optional)

    refresh_threads: list[int] = []
    monkeypatch.setattr(cli_apps_api, "load_config", load)
    monkeypatch.setattr(cli_service.CliAppManager, "__init__", initialize)
    monkeypatch.setattr(cli_service, "_read_json", read)
    monkeypatch.setattr(cli_service.CliAppManager, "catalog_cache_fresh", freshness)
    monkeypatch.setattr(
        cli_apps_api, "_start_catalog_refresh",
        lambda manager: refresh_threads.append(threading.get_ident()) or True,
    )

    async def check() -> None:
        loop_thread = threading.get_ident()
        probe = _HeldProbe(monkeypatch)

        async def unrelated() -> None:
            await probe.entered.wait()
            await asyncio.sleep(0)
            assert not probe.watchdog_fired.is_set(), "watchdog released an event-loop-blocking probe"
            assert not probe.release.is_set(), "unrelated coroutine must advance before release"

        observer = asyncio.create_task(unrelated())
        request = asyncio.create_task(cli_apps_api.cli_apps_payload(
            installed_only=installed_only, config_path=_local_cli_apps,
        ))
        try:
            await asyncio.wait_for(asyncio.shield(observer), 10)
            assert not request.done()
            probe.release.set()
            payload = await asyncio.wait_for(asyncio.shield(request), 10)
            apps = {app["name"]: app for app in payload["apps"]}
            assert set(apps) == ({"gimp"} if installed_only else {"gimp", "other"})
            assert payload["installed_count"] == 1
            assert apps["gimp"]["display_name"] == "GIMP"
            assert apps["gimp"]["status"] == "installed"
            assert apps["gimp"]["available"] is True
            assert apps["gimp"]["skill_installed"] is True
            if installed_only:
                assert "catalog_refresh_pending" not in payload
                assert [command for command, _ in probe.calls] == ["fixture-slow-cli"]
                assert observed["freshness"] == []
                assert refresh_threads == []
            else:
                assert payload["catalog_refresh_pending"] is True
                assert observed["freshness"]
                assert refresh_threads == [loop_thread]
            assert all(observed[name] for name in ("config", "manager", "cache"))
            assert all(thread != loop_thread for threads in observed.values() for thread in threads), observed
            assert all(thread != loop_thread for _, thread in probe.calls)
        finally:
            probe.close()
            await asyncio.wait_for(asyncio.gather(request, observer, return_exceptions=True), 10)

    asyncio.run(check())


def test_cli_apps_payload_cancellation_discards_late_refresh(
    _local_cli_apps: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refreshes: list[cli_service.CliAppManager] = []
    monkeypatch.setattr(
        cli_apps_api, "_start_catalog_refresh", lambda manager: refreshes.append(manager) or True,
    )

    async def check() -> None:
        loop = asyncio.get_running_loop()
        worker_started = threading.Event()
        worker_finished = asyncio.Event()
        real_to_thread = asyncio.to_thread

        async def tracked_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
            def run() -> Any:
                worker_started.set()
                try:
                    return func(*args, **kwargs)
                finally:
                    loop.call_soon_threadsafe(worker_finished.set)

            return await real_to_thread(run)

        monkeypatch.setattr(cli_apps_api.asyncio, "to_thread", tracked_to_thread)
        probe = _HeldProbe(monkeypatch)
        request = asyncio.create_task(cli_apps_api.cli_apps_payload(config_path=_local_cli_apps))
        try:
            await asyncio.wait_for(probe.entered.wait(), 10)
            assert not probe.watchdog_fired.is_set(), "cancellation must run while the probe is held"
            assert not probe.release.is_set()
            assert worker_started.is_set()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert not worker_finished.is_set(), "cancelling the waiter must not finish the worker"
            assert refreshes == []
            probe.release.set()
            await asyncio.wait_for(worker_finished.wait(), 10)
            await asyncio.sleep(0)
            assert refreshes == [], "a cancelled local read must not start a late catalog refresh"
        finally:
            probe.close()
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
            if worker_started.is_set():
                await asyncio.wait_for(worker_finished.wait(), 10)

    asyncio.run(check())
