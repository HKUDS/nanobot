import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.cli.remote import remote_command


@pytest.fixture
def connection(tmp_path, monkeypatch):
    identity, hosts = tmp_path / 'key with spaces', tmp_path / 'known hosts'
    identity.write_text('fixture, never read by the launcher')
    hosts.write_text('verified fixture')
    monkeypatch.setattr(shutil, 'which', lambda _: '/usr/bin/ssh')
    return dict(host='10.44.0.1', network='10.44.0.0/24', user='owner', identity=identity, known_hosts=hosts)


def test_remote_uses_shared_session_and_quotes_shell_arguments(connection):
    command = remote_command(**connection, executable='/opt/nanobot gateway/bin/nanobot',
                             config='/home/owner/config $(touch BAD).json')
    assert shlex.split(command[-1]) == ['/opt/nanobot gateway/bin/nanobot', 'agent', '--session',
                                       'websocket:shared-main', '--theme', 'auto', '--config',
                                       '/home/owner/config $(touch BAD).json']
    assert command[-2] == '10.44.0.1'
    assert 'StrictHostKeyChecking=yes' in command
    assert 'ForwardAgent=no' in command and 'ClearAllForwardings=yes' in command
    assert 'PasswordAuthentication=no' in command
    assert not any('BOOTSTRAP' in value for value in command)


@pytest.mark.parametrize('changes', [
    {'host': '192.168.0.1'}, {'host': '127.0.0.1', 'network': '127.0.0.0/8'},
    {'network': '0.0.0.0/0'}, {'user': 'x;touch BAD'}, {'stream': 'other'},
    {'config': '~/config.json'}, {'executable': 'nanobot\nmalicious'},
])
def test_remote_rejects_ambiguous_route_or_arguments(connection, changes):
    with pytest.raises(ValueError):
        remote_command(**{**connection, **changes})


def test_real_ssh_parses_verified_hosts_and_identity_paths(connection):
    if not Path('/usr/bin/ssh').is_file():
        pytest.skip('OpenSSH is not installed')
    argv = remote_command(**connection)
    # -G parses the actual OpenSSH configuration without opening a connection.
    result = subprocess.run([argv[0], '-G', *argv[1:]], text=True, capture_output=True, check=True)
    assert 'stricthostkeychecking true' in result.stdout or 'stricthostkeychecking yes' in result.stdout
    assert f'identityfile {connection["identity"]}' in result.stdout
    assert f'userknownhostsfile {connection["known_hosts"]}' in result.stdout


def test_cli_dry_run_does_not_connect(connection, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('dry run connected')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    args = ['remote', '--dry-run']
    for key, value in connection.items():
        args.extend(['--' + key.replace('_', '-'), str(value)])
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.stdout
    assert 'websocket:shared-main' in result.stdout
