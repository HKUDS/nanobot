from __future__ import annotations

import os
import tomllib
from pathlib import Path

from nanobot.webui.build import ensure_webui_bundle, inspect_webui_bundle

_MTIME_BASE_NS = 1_700_000_000_000_000_000
_MTIME_STEP_NS = 5_000_000_000


def _touch(path: Path, *, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.name, encoding="utf-8")
    if mtime_ns < 1_000_000_000_000_000:
        mtime_ns = _MTIME_BASE_NS + mtime_ns * _MTIME_STEP_NS
    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_inspect_webui_bundle_ignores_packaged_install_without_source(tmp_path: Path) -> None:
    source = tmp_path / "site-packages" / "webui"
    dist = tmp_path / "site-packages" / "nanobot" / "web" / "dist"
    _touch(dist / "index.html", mtime_ns=20)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.source_available is False
    assert status.stale is False
    assert status.reason == "no_source"


def test_inspect_webui_bundle_marks_missing_dist_stale(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.source_available is True
    assert status.dist_available is False
    assert status.stale is True
    assert status.reason == "missing_dist"


def test_inspect_webui_bundle_detects_source_newer_than_dist(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(source / "src" / "App.tsx", mtime_ns=30)
    _touch(dist / "index.html", mtime_ns=20)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.stale is True
    assert status.reason == "source_newer"
    assert status.newest_source == source / "src" / "App.tsx"


def test_inspect_webui_bundle_detects_channel_owned_ui_source(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    channel_ui = tmp_path / "nanobot" / "channels" / "example" / "webui" / "index.tsx"
    _touch(source / "package.json", mtime_ns=10)
    _touch(dist / "index.html", mtime_ns=20)
    _touch(channel_ui, mtime_ns=30)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.needs_build is True
    assert status.reason == "source_newer"
    assert status.newest_source == channel_ui


def test_channel_owned_ui_sources_are_included_in_distributions() -> None:
    project_root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert "nanobot/channels/*/webui/**/*" in pyproject["tool"]["hatch"]["build"]["include"]


def test_inspect_webui_bundle_accepts_fresh_dist(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(source / "src" / "App.tsx", mtime_ns=20)
    _touch(dist / "index.html", mtime_ns=30)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.stale is False
    assert status.reason == "fresh"


def test_ensure_webui_bundle_auto_builds_stale_dist(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(source / "src" / "App.tsx", mtime_ns=30)
    _touch(dist / "index.html", mtime_ns=20)
    commands: list[tuple[str, ...]] = []

    def fake_run(command, *, cwd: Path, check: bool) -> None:
        commands.append(tuple(command))
        assert cwd == source
        assert check is True
        if command == ["bun", "run", "build"]:
            _touch(dist / "index.html", mtime_ns=40)

    status = ensure_webui_bundle(
        mode="auto",
        source_dir=source,
        dist_dir=dist,
        runner="bun",
        subprocess_run=fake_run,
    )

    assert status.stale is False
    assert commands == [("bun", "install"), ("bun", "run", "build")]


def test_ensure_webui_bundle_warns_without_building(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(source / "src" / "App.tsx", mtime_ns=30)
    _touch(dist / "index.html", mtime_ns=20)
    messages: list[str] = []

    status = ensure_webui_bundle(
        mode="warn",
        source_dir=source,
        dist_dir=dist,
        output=messages.append,
    )

    assert status.stale is True
    assert messages
    assert "Run `cd" in messages[0]
