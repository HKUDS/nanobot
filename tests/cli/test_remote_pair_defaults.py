"""Server pairing suggests a real login account, never blindly trusts SUDO_USER."""

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nanobot.cli import remote


@pytest.mark.parametrize(
    ("uid", "sudo_user", "expected"),
    [(1001, "other", "ubuntu"), (0, "ubuntu", "ubuntu"),
     (0, "missing", None), (0, "nanobot", None), (0, "root", None)],
)
def test_pair_suggests_existing_login_account(monkeypatch, uid, sudo_user, expected):
    pwd = pytest.importorskip("pwd")
    monkeypatch.setattr(remote, "_cloud_ssh_user", lambda: None)
    users = [SimpleNamespace(pw_name=name, pw_uid=user_uid, pw_shell=shell) for name, user_uid, shell in
             [("root", 0, "/bin/bash"), ("ubuntu", 1001, "/bin/bash"),
              ("other", 1002, "/bin/bash"), ("nanobot", 1003, "/usr/sbin/nologin")]]
    monkeypatch.setattr(remote.os, "getuid", lambda: uid)
    monkeypatch.setattr(pwd, "getpwuid", lambda _: users[1] if uid else users[0])
    monkeypatch.setattr(pwd, "getpwall", lambda: users)
    monkeypatch.setenv("SUDO_USER", sudo_user)
    assert remote._default_ssh_user() == expected


@pytest.mark.parametrize("configured, expected", [
    ("ubuntu", "ubuntu"), ("lighthouse", "lighthouse"), ("root", None),
    ("nanobot", None), ("missing", None), ("ubuntu\nlighthouse", None), (None, None),
])
def test_root_cloud_console_uses_only_an_existing_regular_cloud_account(monkeypatch, configured, expected):
    pwd = pytest.importorskip("pwd")
    monkeypatch.setattr(remote.os, "getuid", lambda: 0)
    monkeypatch.setattr(pwd, "getpwuid", lambda _: SimpleNamespace(pw_uid=0, pw_name="root"))
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.setattr(remote, "_ssh_login_users", lambda: ["lighthouse", "ubuntu"])
    monkeypatch.setattr(remote, "_cloud_ssh_user", lambda: configured)
    assert remote._default_ssh_user() == expected


@pytest.mark.parametrize("uid,sudo_user,users,expected", [
    (1001, "", ["deploy", "ubuntu"], "deploy"),
    (0, "deploy", ["deploy", "ubuntu"], "deploy"),
    (0, "", ["deploy"], "deploy"), (0, "", [], None),
])
def test_known_login_and_single_account_do_not_need_cloud_lookup(monkeypatch, uid, sudo_user, users, expected):
    pwd = pytest.importorskip("pwd")
    monkeypatch.setattr(remote.os, "getuid", lambda: uid)
    monkeypatch.setattr(pwd, "getpwuid", lambda _: SimpleNamespace(pw_uid=uid, pw_name="deploy" if uid else "root"))
    monkeypatch.setenv("SUDO_USER", sudo_user)
    monkeypatch.setattr(remote, "_ssh_login_users", lambda: users)
    lookup = Mock(side_effect=AssertionError("unnecessary cloud lookup"))
    monkeypatch.setattr(remote, "_cloud_ssh_user", lookup)
    assert remote._default_ssh_user() == expected
    lookup.assert_not_called()


def test_cloud_lookup_reads_only_the_configured_username_with_a_timeout(monkeypatch):
    monkeypatch.setattr(remote.shutil, "which", lambda _: "/usr/bin/cloud-init")
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="ubuntu\n"))
    monkeypatch.setattr(remote.subprocess, "run", run)
    assert remote._cloud_ssh_user() == "ubuntu"
    run.assert_called_once_with(["/usr/bin/cloud-init", "query", "system_info.default_user.name"],
                                capture_output=True, text=True, timeout=2, check=False)


@pytest.mark.parametrize("failure", [OSError(), UnicodeError(), subprocess.TimeoutExpired("cloud-init", 2)])
def test_unavailable_cloud_data_keeps_the_account_picker(monkeypatch, failure):
    monkeypatch.setattr(remote.shutil, "which", lambda _: "/usr/bin/cloud-init")
    monkeypatch.setattr(remote.subprocess, "run", Mock(side_effect=failure))
    assert remote._cloud_ssh_user() is None


def test_failed_cloud_query_does_not_use_error_output_as_an_account(monkeypatch):
    monkeypatch.setattr(remote.shutil, "which", lambda _: "/usr/bin/cloud-init")
    monkeypatch.setattr(remote.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=1, stdout="ubuntu")))
    assert remote._cloud_ssh_user() is None


def test_missing_cloud_init_does_not_run_an_external_command(monkeypatch):
    monkeypatch.setattr(remote.shutil, "which", lambda _: None)
    run = Mock()
    monkeypatch.setattr(remote.subprocess, "run", run)
    assert remote._cloud_ssh_user() is None
    run.assert_not_called()


@pytest.mark.parametrize(("connection", "expected"), [
    ("1.1.1.1 50000 8.8.8.8 22", "8.8.8.8"),
    ("1.1.1.1 50000 10.0.0.8 22", ""),
    ("1.1.1.1 50000 127.0.0.1 22", ""),
    ("1.1.1.1 50000 not-an-ip 22", ""), ("", ""),
])
def test_only_global_ssh_server_address_can_be_suggested(monkeypatch, connection, expected):
    monkeypatch.setenv("SSH_CONNECTION", connection)
    monkeypatch.setattr(remote, "_tencent_public_host", lambda: "")
    assert remote._default_host() == expected
