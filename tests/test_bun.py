import hashlib
import io
import os
import zipfile
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
