"""Name discovery is passive; OpenSSH, not our index, interprets connection options."""

import asyncio
import json
import subprocess

import pytest

from nanobot.webui.remote_instances import RemoteInstances
from nanobot.webui.remote_ssh import RemoteError, RemoteProfile, ssh_arguments
from nanobot.webui.ssh_config import discover_hosts


@pytest.fixture
def ssh_home(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    folder = tmp_path / ".ssh"
    folder.mkdir()
    return folder


def test_discover_host_names_quotes_equals_multiple_aliases_and_patterns(ssh_home):
    config = ssh_home / "config"
    config.write_text('''# Host ignored
Host=one two "three" # comment
  HostName not-returned.example
  IdentityFile private-key-not-returned
Host * !excluded jump? [ab]bad -unsafe one
Host TWO
Host ipv6:alias
''')
    result = discover_hosts(str(config))
    assert [host["host"] for host in result["hosts"]] == ["one", "two", "three", "ipv6:alias"]
    assert {host["ssh_config"] for host in result["hosts"]} == {str(config)}
    assert "private-key-not-returned" not in json.dumps(result)
    assert "not-returned.example" not in json.dumps(result)


def test_recursive_includes_are_sorted_relative_to_ssh_root_and_deduplicated(ssh_home):
    (ssh_home / "hosts").mkdir()
    (ssh_home / "config").write_text('Include "hosts/*.conf"\nHost final\n')
    (ssh_home / "hosts" / "b.conf").write_text("Host second\nInclude config\n")
    (ssh_home / "hosts" / "a.conf").write_text("Host first\nInclude hosts/b.conf\n")
    result = discover_hosts(str(ssh_home / "config"))
    assert [host["host"] for host in result["hosts"]] == ["first", "second", "final"]
    assert len(result["files"]) == 3
    assert not result["incomplete"]


def test_default_config_is_found_without_pinning_a_custom_file(ssh_home):
    (ssh_home / "config").write_text("Host default-test\n  Port 2222\n")
    result = discover_hosts()
    host = next(host for host in result["hosts"] if host["host"] == "default-test")
    assert host["ssh_config"] == ""
    assert host["source"] == str(ssh_home / "config")


def test_discovery_never_runs_ssh_match_exec_or_proxy_commands(ssh_home, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Discovery must not execute anything")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    config = ssh_home / "config"
    config.write_text('Host safe\n Match exec "touch dangerous"\nProxyCommand command-not-returned\n')
    assert [host["host"] for host in discover_hosts(str(config))["hosts"]] == ["safe"]


def test_unresolvable_includes_and_invalid_lines_do_not_hide_other_hosts(ssh_home):
    config = ssh_home / "config"
    config.write_text('Host ok\nInclude ${UNSET}/config %h.conf\nHost "unterminated\nHost good\n')
    result = discover_hosts(str(config))
    assert [host["host"] for host in result["hosts"]] == ["ok", "good"]
    assert result["incomplete"]


@pytest.mark.parametrize("contents", [b"\xff", b"x" * 262145], ids=["invalid-utf8", "oversized"])
def test_unreadable_or_oversized_custom_config_is_an_explicit_error(ssh_home, contents):
    path = ssh_home / "config"
    path.write_bytes(contents)
    with pytest.raises(RemoteError, match="ssh_config_unreadable"):
        discover_hosts(str(path))


def test_missing_explicit_config_is_not_silently_treated_as_empty(ssh_home):
    with pytest.raises(RemoteError, match="local_file_not_found"):
        discover_hosts(str(ssh_home / "missing"))


def test_host_limit_is_bounded_and_reported(ssh_home):
    config = ssh_home / "config"
    config.write_text("\n".join(f"Host host-{n}" for n in range(250)))
    result = discover_hosts(str(config))
    assert len(result["hosts"]) == 200
    assert result["incomplete"]


def test_include_read_budget_is_bounded_and_reported(ssh_home):
    config = ssh_home / "config"
    config.write_text("Include large-*\nHost final\n")
    for index in range(6):
        (ssh_home / f"large-{index}").write_text(f"Host host-{index}\n#" + "x" * 250000)
    result = discover_hosts(str(config))
    assert result["incomplete"]
    assert len(result["files"]) == 5  # Root plus four complete included files.
    assert result["hosts"][-1]["host"] == "final"


@pytest.mark.parametrize("path", ["\nsecret", "\x00bad", "x" * 2049])
def test_invalid_paths_rejected_before_reading(path):
    with pytest.raises(RemoteError, match="invalid_profile"):
        discover_hosts(path)


@pytest.mark.parametrize(("override", "expected"), [(None, "2222"), (2200, "2200")])
def test_system_ssh_inherits_config_port_user_and_identity(ssh_home, override, expected):
    config = ssh_home / "config"
    config.write_text("Host example-test\n HostName 192.0.2.10\n User tester\n Port 2222\n IdentityFile /tmp/test-key\n RemoteCommand tmux attach\n RequestTTY force\n")
    profile = RemoteProfile(name="Test", host="example-test", ssh_config=str(config), port=override)
    # This controlled fixture has no Match exec; -G makes no network connections.
    result = subprocess.run([*ssh_arguments(profile), "-G", profile.host],
                            capture_output=True, text=True, check=True)
    settings = dict(line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
    assert settings["port"] == expected
    assert settings["user"] == "tester"
    assert settings["identityfile"] == "/tmp/test-key"
    assert settings.get("remotecommand", "none") == "none"
    assert settings["requesttty"] == "false"


async def test_manager_discovery_does_not_save_profiles_or_connect(ssh_home):
    config = ssh_home / "config"
    config.write_text("Host one\n")
    manager = RemoteInstances(ssh_home / "webui")
    result = await manager.action("discover", {"ssh_config": str(config)})
    assert result["hosts"][0]["host"] == "one"
    assert not manager.path.exists()
    assert not manager.connections
