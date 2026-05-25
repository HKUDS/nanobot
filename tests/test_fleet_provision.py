"""Tests for fleet.provision — gh + ssh-keygen wrappers (subprocess mocked)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nanobot.fleet import provision


def _fake_completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                        stdout=stdout, stderr=stderr)


def test_check_gh_auth_succeeds_when_authenticated(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                         lambda *a, **kw: _fake_completed(stdout="ok"))
    provision.check_gh_auth()  # no exception


def test_check_gh_auth_raises_when_unauthenticated(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                         lambda *a, **kw: _fake_completed(returncode=1, stderr="not logged in"))
    with pytest.raises(provision.ProvisionError) as ei:
        provision.check_gh_auth()
    assert "not logged in" in str(ei.value)


def test_check_gh_auth_raises_when_missing(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError()
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(provision.ProvisionError):
        provision.check_gh_auth()


def test_create_repo_private(monkeypatch):
    seen = []
    def fake_run(args, **kw):
        seen.append(args)
        return _fake_completed(stdout="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = provision.create_repo("phelps-sg", "agent-peewee",
                                description="x", private=True)
    assert out.full_name == "phelps-sg/agent-peewee"
    assert out.ssh_url == "git@github.com:phelps-sg/agent-peewee.git"
    assert "--private" in seen[0]
    assert "--description" in seen[0]


def test_create_repo_public(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run",
                         lambda args, **kw: seen.append(args) or _fake_completed())
    provision.create_repo("phelps-sg", "agent-iroh", private=False)
    assert "--public" in seen[0]


def test_add_deploy_key_parses_response(monkeypatch):
    payload = json.dumps({"id": 12345, "title": "nanobot:peewee"})
    monkeypatch.setattr(subprocess, "run",
                         lambda args, **kw: _fake_completed(stdout=payload))
    out = provision.add_deploy_key("phelps-sg/agent-peewee", "ssh-ed25519 AAA...",
                                    title="nanobot:peewee", read_only=False)
    assert out.id == 12345
    assert out.title == "nanobot:peewee"


def test_add_deploy_key_handles_bad_response(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                         lambda args, **kw: _fake_completed(stdout="not json"))
    with pytest.raises(provision.ProvisionError):
        provision.add_deploy_key("x/y", "key", title="t")


def test_generate_keypair_uses_ssh_keygen(tmp_path, monkeypatch):
    key_dir = tmp_path / "k"

    def fake_run(args, **kw):
        # Simulate ssh-keygen creating the key files.
        priv = Path(args[-1])
        pub = priv.with_suffix(".pub")
        priv.write_text("PRIVATE\n")
        pub.write_text("ssh-ed25519 AAAfakekey peewee@nanobot\n")
        return _fake_completed()
    monkeypatch.setattr(subprocess, "run", fake_run)

    kp = provision.generate_keypair(key_dir, comment="peewee@nanobot")
    assert kp.private_key_path.exists()
    assert kp.public_key.startswith("ssh-ed25519")


def test_generate_keypair_refuses_overwrite(tmp_path, monkeypatch):
    key_dir = tmp_path / "k"
    key_dir.mkdir()
    (key_dir / "id").write_text("existing")
    monkeypatch.setattr(subprocess, "run",
                         lambda args, **kw: _fake_completed())
    with pytest.raises(provision.ProvisionError):
        provision.generate_keypair(key_dir, comment="x")


def test_archive_repo_calls_gh(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run",
                         lambda args, **kw: seen.append(args) or _fake_completed())
    provision.archive_repo("phelps-sg/agent-peewee")
    assert seen[0][:3] == ["gh", "repo", "archive"]
    assert "--yes" in seen[0]


def test_list_deploy_keys_parses(monkeypatch):
    payload = json.dumps([{"id": 1, "title": "a"}, {"id": 2, "title": "b"}])
    monkeypatch.setattr(subprocess, "run",
                         lambda args, **kw: _fake_completed(stdout=payload))
    keys = provision.list_deploy_keys("phelps-sg/agent-peewee")
    assert [k["id"] for k in keys] == [1, 2]


def test_remove_deploy_key_calls_gh(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run",
                         lambda args, **kw: seen.append(args) or _fake_completed())
    provision.remove_deploy_key("phelps-sg/agent-peewee", 12345)
    assert "DELETE" in seen[0]
    assert "/keys/12345" in seen[0][2]


def test_run_raises_on_nonzero(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                         lambda args, **kw: _fake_completed(returncode=2, stderr="boom"))
    with pytest.raises(provision.ProvisionError) as ei:
        provision._run(["gh", "thing"])
    assert "boom" in str(ei.value)
