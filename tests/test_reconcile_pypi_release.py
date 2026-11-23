import hashlib
import json
from urllib.error import HTTPError

import pytest

from nanobot.releases import PLATFORMS
from scripts import reconcile_pypi_release as reconcile


@pytest.fixture
def staged(tmp_path):
    names = {f"nanobot_ai-1.2.3-py3-none-{platform}.whl" for platform in PLATFORMS.values()}
    names.add("nanobot_ai-1.2.3.tar.gz")
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    return tmp_path


def index_entry(path):
    content = path.read_bytes()
    return {"filename": path.name, "size": len(content), "yanked": False,
            "digests": {"sha256": hashlib.sha256(content).hexdigest()}}


def serve(monkeypatch, entries):
    payload = json.dumps({"info": {"name": "nanobot-ai", "version": "1.2.3"}, "urls": entries}).encode()
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return payload[:size]

    monkeypatch.setattr(reconcile, "urlopen", lambda url, timeout: Response())


def test_new_release_uploads_all_files(staged, monkeypatch):
    def missing(url, timeout):
        raise HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(reconcile, "urlopen", missing)
    assert reconcile.remove_uploaded_files(staged, version="1.2.3", destination="pypi") == 6
    assert len(list(staged.iterdir())) == 6


def test_index_failure_never_becomes_a_new_release(staged, monkeypatch):
    def unavailable(url, timeout):
        raise HTTPError(url, 503, "Unavailable", {}, None)
    monkeypatch.setattr(reconcile, "urlopen", unavailable)
    with pytest.raises(HTTPError):
        reconcile.remove_uploaded_files(staged, version="1.2.3", destination="pypi")
    assert len(list(staged.iterdir())) == 6


def test_retry_uploads_only_missing_files(staged, monkeypatch):
    already_uploaded = sorted(staged.iterdir())[:2]
    serve(monkeypatch, [index_entry(path) for path in already_uploaded])
    assert reconcile.remove_uploaded_files(staged, version="1.2.3", destination="testpypi") == 4
    assert all(not path.exists() for path in already_uploaded)
    assert len(list(staged.iterdir())) == 4


def test_complete_release_requires_no_upload(staged, monkeypatch):
    serve(monkeypatch, [index_entry(path) for path in staged.iterdir()])
    assert reconcile.remove_uploaded_files(staged, version="1.2.3", destination="pypi") == 0
    assert not list(staged.iterdir())


@pytest.mark.parametrize("change", ["digest", "unexpected", "yanked", "duplicate"])
def test_refuses_inconsistent_index_without_removing_files(staged, monkeypatch, change):
    paths = sorted(staged.iterdir())
    entries = [index_entry(path) for path in paths[:2]]
    if change == "digest":
        entries[1]["digests"]["sha256"] = "0" * 64
    elif change == "unexpected":
        entries[1]["filename"] = "other.whl"
    elif change == "yanked":
        entries[1]["yanked"] = True
    else:
        entries[1] = entries[0]
    serve(monkeypatch, entries)
    with pytest.raises(ValueError):
        reconcile.remove_uploaded_files(staged, version="1.2.3", destination="pypi")
    assert len(list(staged.iterdir())) == 6
