"""Pairing knows whose public IP it needs, without querying arbitrary metadata."""

import http.client
from pathlib import Path
from unittest.mock import Mock

import pytest

from nanobot.cli import remote


@pytest.fixture
def metadata(monkeypatch):
    monkeypatch.setattr(remote.sys, "platform", "linux")
    monkeypatch.setattr(Path, "read_text", lambda _: "Tencent Cloud\n")
    response = Mock(status=200)
    response.read.return_value = b"43.156.243.141\n"
    connection = Mock()
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    monkeypatch.setattr(remote.http.client, "HTTPConnection", factory)
    return factory, connection, response


def test_tencent_uses_only_fixed_public_address_field(metadata, monkeypatch):
    factory, connection, response = metadata
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8888")
    assert remote._tencent_public_host() == "43.156.243.141"
    factory.assert_called_once_with("169.254.0.23", timeout=1)
    connection.request.assert_called_once_with("GET", "/latest/meta-data/public-ipv4",
                                              headers={"Host": "metadata.tencentyun.com"})
    response.read.assert_called_once_with(64)
    connection.close.assert_called_once()


@pytest.mark.parametrize("vendor", ["Amazon EC2", "Google", "QEMU", "", "Tencent Cloud impostor"])
def test_other_machines_do_not_probe_metadata(metadata, monkeypatch, vendor):
    factory, _, _ = metadata
    monkeypatch.setattr(Path, "read_text", lambda _: vendor)
    assert remote._tencent_public_host() == ""
    factory.assert_not_called()


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_non_linux_never_probes(metadata, monkeypatch, platform):
    factory, _, _ = metadata
    monkeypatch.setattr(remote.sys, "platform", platform)
    assert remote._tencent_public_host() == ""
    factory.assert_not_called()


@pytest.mark.parametrize("error", [PermissionError(), FileNotFoundError(), UnicodeError()])
def test_unreadable_machine_identity_falls_back(metadata, monkeypatch, error):
    factory, _, _ = metadata
    monkeypatch.setattr(Path, "read_text", Mock(side_effect=error))
    assert remote._tencent_public_host() == ""
    factory.assert_not_called()


@pytest.mark.parametrize("value", [b"10.0.0.8", b"127.0.0.1", b"169.254.0.23", b"100.64.0.1",
    b"0.0.0.0", b"224.0.0.1", b"255.255.255.255", b"::1", b"2606:4700::1111",
    b"8.8.8.8\n1.1.1.1", b"host.example", b"", b"\xff", b"x" * 64,
    b"8.8.8.8" + b" " * 57, b"{\"credentials\":\"never-used\"}"])
def test_only_one_bounded_global_ipv4_is_accepted(metadata, value):
    _, connection, response = metadata
    response.read.return_value = value
    assert remote._tencent_public_host() == ""
    connection.close.assert_called_once()


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 500])
def test_redirects_and_errors_are_not_followed(metadata, status):
    _, connection, response = metadata
    response.status = status
    assert remote._tencent_public_host() == ""
    response.read.assert_not_called()
    assert connection.request.call_count == 1
    connection.close.assert_called_once()


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionRefusedError(), http.client.HTTPException()])
def test_failed_lookup_falls_back_and_closes_connection(metadata, error):
    _, connection, _ = metadata
    connection.getresponse.side_effect = error
    assert remote._tencent_public_host() == ""
    connection.close.assert_called_once()


@pytest.mark.parametrize("ssh_connection", ["", "proxy 50000 10.0.0.8 22", "invalid",
                                           "proxy 50000 224.0.0.1 22"])
def test_cloud_console_without_public_ssh_address_uses_instance_metadata(metadata, monkeypatch, ssh_connection):
    monkeypatch.setenv("SSH_CONNECTION", ssh_connection)
    assert remote._default_host() == "43.156.243.141"


def test_public_ssh_address_takes_precedence(metadata, monkeypatch):
    factory, _, _ = metadata
    monkeypatch.setenv("SSH_CONNECTION", "1.1.1.1 50000 8.8.8.8 22")
    assert remote._default_host() == "8.8.8.8"
    factory.assert_not_called()
