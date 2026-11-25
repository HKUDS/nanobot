import hashlib
import io
import os
import subprocess
import sys
import zipfile
from contextlib import ExitStack
from pathlib import Path

import pytest

from nanobot import bun


def test_ensure_bun_reuses_matching_system_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(bun.shutil, "which", lambda _: "/bin/bun")
    monkeypatch.setattr(bun, "_matches_version", lambda _: True)
    assert bun.ensure_bun(cache_dir=tmp_path / "unused") == "/bin/bun"
    assert not (tmp_path / "unused").exists()


@pytest.fixture
def download(monkeypatch):
    target = "windows-x64-baseline" if os.name == "nt" else "linux-x64-baseline"
    name = "bun.exe" if os.name == "nt" else "bun"
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(f"bun-{target}/{name}", b"runtime")
        archive.writestr("../../unwanted", b"do not extract")
    raw = data.getvalue()
    calls = []

    def open_url(url, *, timeout):
        calls.append(url)
        return io.BytesIO(raw)

    monkeypatch.setattr(bun.shutil, "which", lambda _: None)
    monkeypatch.setattr(bun, "_target", lambda: target)
    monkeypatch.setitem(bun._ARCHIVES, target, hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(bun.urllib.request, "urlopen", open_url)
    monkeypatch.setattr(bun, "_matches_version", lambda path: Path(path).read_bytes() == b"runtime")
    return target, calls


def test_bun_download_checks_hash_extracts_only_runtime_and_caches(download, tmp_path):
    _, calls = download
    executable = bun.ensure_bun(cache_dir=tmp_path)
    assert Path(executable).read_bytes() == b"runtime"
    assert not list(tmp_path.rglob("unwanted"))
    assert bun.ensure_bun(cache_dir=tmp_path) == executable
    assert len(calls) == 1
    assert calls[0].startswith("https://github.com/oven-sh/bun/releases/download/bun-v")


@pytest.mark.skipif(os.name != "nt", reason="Windows denies renaming files held by a reader")
def test_bun_download_survives_reader_holding_version_checked_file(download, monkeypatch, tmp_path):
    with ExitStack() as readers:
        def check_version(path):
            reader = readers.enter_context(Path(path).open("rb"))
            return reader.read() == b"runtime"

        monkeypatch.setattr(bun, "_matches_version", check_version)
        executable = bun.ensure_bun(cache_dir=tmp_path)
        assert Path(executable).read_bytes() == b"runtime"


def test_bun_rejects_corrupt_download(download, monkeypatch, tmp_path):
    target, _ = download
    monkeypatch.setitem(bun._ARCHIVES, target, "0" * 64)
    with pytest.raises(bun.BunUnavailableError, match="checksum"):
        bun.ensure_bun(cache_dir=tmp_path)
    assert not list(tmp_path.rglob("bun.exe"))
    assert not list(tmp_path.rglob("bun"))


def test_bun_rejects_unrunnable_download(download, monkeypatch, tmp_path):
    monkeypatch.setattr(bun, "_matches_version", lambda _: False)
    with pytest.raises(bun.BunUnavailableError, match="cannot run"):
        bun.ensure_bun(cache_dir=tmp_path)
    assert not list(tmp_path.rglob(".install-*"))
    target, _ = download
    name = "bun.exe" if os.name == "nt" else "bun"
    assert not (tmp_path / bun.BUN_VERSION / target / name).exists()


def test_private_bun_path_does_not_modify_parent_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "original")
    runtime = tmp_path / "bun"
    runtime.write_bytes(b"runtime")
    with bun.bun_environment(str(runtime)) as env:
        alias_dir = Path(env["PATH"].split(os.pathsep)[0])
        node = alias_dir / ("node.exe" if os.name == "nt" else "node")
        assert node.read_bytes() == b"runtime"
        assert env["PATH"].endswith(os.pathsep + "original")
    assert not alias_dir.exists()
    assert os.environ["PATH"] == "original"


@pytest.mark.skipif(os.name != "nt", reason="Windows denies deletion of an open executable")
@pytest.mark.parametrize("exit_code", [0, 17])
def test_locked_node_cleanup_preserves_command_result(monkeypatch, tmp_path, caplog, exit_code):
    runtime = tmp_path / "bun.exe"
    runtime.write_bytes(b"runtime")
    monkeypatch.setattr(bun.tempfile, "tempdir", str(tmp_path))
    with ExitStack() as handles:
        handles.callback(bun.logger.remove, bun.logger.add(caplog.handler, level="WARNING", format="{message}"))
        if exit_code:
            error = handles.enter_context(pytest.raises(subprocess.CalledProcessError))
        with bun.bun_environment(str(runtime)) as env:
            alias_dir = Path(env["PATH"].split(os.pathsep)[0])
            handles.enter_context((alias_dir / "node.exe").open("rb"))
            subprocess.run([sys.executable, "-c", f"raise SystemExit({exit_code})"], check=True, env=env)
    if exit_code:
        assert error.value.returncode == exit_code
    assert str(alias_dir) in caplog.text


@pytest.mark.skipif(os.name != "nt", reason="Windows denies deletion of an open executable")
def test_node_alias_is_removed_when_windows_releases_lock_during_retry(monkeypatch, tmp_path):
    runtime = tmp_path / "bun.exe"
    runtime.write_bytes(b"runtime")
    with ExitStack() as handles:
        with bun.bun_environment(str(runtime)) as env:
            alias_dir = Path(env["PATH"].split(os.pathsep)[0])
            lock = handles.enter_context((alias_dir / "node.exe").open("rb"))
            monkeypatch.setattr(bun.time, "sleep", lambda _: lock.close())
    assert not alias_dir.exists()
