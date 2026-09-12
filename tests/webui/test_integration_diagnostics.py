from __future__ import annotations

import io
import ssl
import threading
import time
from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from nanobot.config.schema import Config
from nanobot.integrations import diagnostics as d
from nanobot.integrations import diagnostics as module
from nanobot.integrations.credentials import CredentialStore
from nanobot.webui.settings_routes import WebUISettingsRouter
from webui import test_integrations_api as api_tests
from webui.test_settings_routes import _mutation_request, _router

handler = api_tests.handler

SECRET = "diagnostics-test-only-password"


@pytest.fixture
def configured(tmp_path):
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    config.personal_integrations.icloud.username = "apple@example.org"
    config.personal_integrations.icloud.credential_ref = CredentialStore(tmp_path).put(SECRET)
    return config


def test_checks_only_saved_fixed_apple_endpoints_and_never_echo_secrets(configured, monkeypatch, caplog):
    calls = []

    def imap(host, port, username, password, deadline):
        calls.append(("imap", host, port, username, password))
        return 3

    def caldav(username, password, deadline):
        calls.append(("caldav", username, password))

    monkeypatch.setattr(module, "_imap", imap)
    monkeypatch.setattr(module, "_caldav", caldav)
    result = module.check_connection(configured, module.CheckRequest(target="icloud"))
    assert result["ok"] and result["read_only"]
    assert result["checks"][0]["folder_count"] == 3
    assert calls[0] == ("imap", "imap.mail.me.com", 993, "apple@example.org", SECRET)
    assert calls[1] == ("caldav", "apple@example.org", SECRET)
    assert SECRET not in str(result) and SECRET not in caplog.text


@pytest.mark.parametrize("failure,code", [(ssl.SSLError(SECRET), "tls_failed"),
    (TimeoutError(SECRET), "timeout"), (RuntimeError(SECRET), "connection_failed"),
    (module.ProbeError("authentication_failed"), "authentication_failed")])
def test_diagnostic_errors_are_sanitized(configured, monkeypatch, failure, code):
    def fail(*args):
        raise failure
    monkeypatch.setattr(module, "_imap", fail)
    monkeypatch.setattr(module, "_caldav", fail)
    result = module.check_connection(configured, module.CheckRequest(target="icloud"))
    assert not result["ok"]
    assert result["checks"][0]["code"] == code
    assert SECRET not in str(result)


def test_missing_credentials_do_not_connect(monkeypatch):
    monkeypatch.setattr(module, "_tls", lambda *args: pytest.fail("network not allowed"))
    result = module.check_connection(Config(), module.CheckRequest(target="icloud"))
    assert result["checks"][0]["code"] == "not_configured"


@pytest.mark.parametrize("addresses", [("127.0.0.1",), ("10.0.0.1",), ("169.254.169.254",),
    ("100.64.0.1",), ("::ffff:127.0.0.1",), ("::ffff:100.64.0.1",),
    ("1.1.1.1", "192.168.1.1"), ()])
def test_probe_blocks_private_and_mixed_dns_even_when_shared_whitelist_allows(monkeypatch, addresses):
    monkeypatch.setattr(module, "resolve_url_target", lambda url: (True, "", addresses))
    monkeypatch.setattr(module.socket, "socket", lambda *args: pytest.fail("blocked before connecting"))
    with pytest.raises(module.ProbeError, match="blocked_target"):
        module._tls("imap.example.org", 993, time.monotonic() + 1)


def test_probe_pins_validated_ip_but_verifies_original_hostname(monkeypatch):
    calls = []

    class Connection:
        def settimeout(self, timeout):
            assert 0 < timeout <= 5
        def connect(self, address):
            calls.append(address)
        def close(self):
            pass

    connection = Connection()
    class TLSContext:
        def wrap_socket(self, sock, *, server_hostname):
            assert sock is connection
            calls.append(server_hostname)
            return connection

    monkeypatch.setattr(module, "resolve_url_target", lambda url: (True, "", ("1.1.1.1",)))
    monkeypatch.setattr(module.socket, "socket", lambda *args: connection)
    monkeypatch.setattr(module.ssl, "create_default_context", TLSContext)
    assert module._tls("imap.example.org", 993, time.monotonic() + 2) is connection
    assert calls == [("1.1.1.1", 993), "imap.example.org"]


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.sent = []
    def settimeout(self, timeout):
        assert timeout > 0
    def sendall(self, data):
        self.sent.append(data)
    def recv(self, limit):
        data, self.response = self.response[:limit], self.response[limit:]
        return data
    def makefile(self, *args):
        return io.BytesIO(self.response)


def test_imap_probe_only_logs_in_and_lists_without_selecting_or_fetching(monkeypatch):
    connection = FakeSocket(b'* OK ready\r\na1 OK authenticated\r\n* LIST () "/" "INBOX"\r\na2 OK listed\r\n')
    monkeypatch.setattr(module, "_bounded_tls", lambda *args: nullcontext(connection))
    assert module._imap("imap.example.org", 993, "user@example.org", SECRET, time.monotonic() + 1) == 1
    assert connection.sent == [b'a1 LOGIN "user@example.org" "' + SECRET.encode() + b'"\r\n',
                               b'a2 LIST "" "*"\r\n']


def test_imap_probe_rejects_bad_auth_and_bounded_response(monkeypatch):
    connection = FakeSocket(b'* OK ready\r\na1 NO ' + SECRET.encode() + b'\r\n')
    monkeypatch.setattr(module, "_bounded_tls", lambda *args: nullcontext(connection))
    with pytest.raises(module.ProbeError, match="authentication_failed"):
        module._imap("imap.example.org", 993, "user", SECRET, time.monotonic() + 1)
    connection.response = b"x" * (module.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(module.ProbeError, match="protocol_error"):
        module._imap("imap.example.org", 993, "user", SECRET, time.monotonic() + 1)


def test_caldav_probe_fixed_propfind_and_no_redirect_following(monkeypatch):
    body = b'<d:multistatus xmlns:d="DAV:"><d:current-user-principal><d:href>/private-id/</d:href></d:current-user-principal></d:multistatus>'
    connection = FakeSocket(b"HTTP/1.1 207 Multi-Status\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    targets = []
    def tls(*args):
        targets.append(args[:2])
        return nullcontext(connection)
    monkeypatch.setattr(module, "_bounded_tls", tls)
    module._caldav("user", SECRET, time.monotonic() + 1)
    assert targets == [("caldav.icloud.com", 443)]
    assert connection.sent[0].startswith(b"PROPFIND / HTTP/1.1\r\n")
    assert b"Depth: 0\r\n" in connection.sent[0]
    connection.response = b"HTTP/1.1 301 Redirect\r\nLocation: https://evil.example.org/\r\n\r\n"
    with pytest.raises(module.ProbeError, match="redirect_refused"):
        module._caldav("user", SECRET, time.monotonic() + 1)
    assert targets == [("caldav.icloud.com", 443)] * 2


def test_total_timeout_returns_promptly_without_spawning_unbounded_workers(configured, monkeypatch):
    started = threading.Event()
    finish = threading.Event()
    lock = threading.Lock()
    monkeypatch.setattr(module, "_probe_slot", lock)
    monkeypatch.setattr(module, "TIMEOUT_SECONDS", 0.02)

    def stuck(*args):
        started.set()
        finish.wait(timeout=2)
        return []

    monkeypatch.setattr(module, "_checks", stuck)
    try:
        result = module.check_connection(configured, module.CheckRequest(target="icloud"))
        assert started.is_set()
        assert result["checks"][0]["code"] == "timeout"
        result = module.check_connection(configured, module.CheckRequest(target="icloud"))
        assert result["checks"][0]["code"] == "busy"
    finally:
        finish.set()
        assert lock.acquire(timeout=1)
        lock.release()


@pytest.mark.parametrize("payload", [
    {"target": "icloud", "password": "secret"}, {"target": "icloud", "account_id": "x"},
    {"target": "mail"}, {"target": "url"}, {"target": "mail", "account_id": "../x"},
])
def test_check_request_no_arbitrary_targets_or_credentials(payload):
    with pytest.raises(ValidationError):
        d.CheckRequest.model_validate(payload)


def test_missing_configuration_does_not_connect(monkeypatch):
    monkeypatch.setattr(d, "_tls", Mock(side_effect=AssertionError("no network")))
    result = d.check_connection(Config(), d.CheckRequest(target="icloud"))
    assert result["checks"][0]["code"] == "not_configured"
    assert result["read_only"]


@pytest.mark.parametrize("addresses", [("127.0.0.1",), ("1.1.1.1", "10.0.0.1"), ("::ffff:127.0.0.1",)])
def test_private_mixed_and_mapped_dns_never_open_socket(monkeypatch, addresses):
    monkeypatch.setattr(d, "resolve_url_target", lambda _: (True, "", addresses))
    socket = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(d.socket, "socket", socket)
    with pytest.raises(d.ProbeError, match="blocked_target"):
        d._tls("example.org", 993, time.monotonic() + 5)
    socket.assert_not_called()


def test_probe_busy_does_not_launch_second_worker(monkeypatch):
    slot = threading.Lock()
    slot.acquire()
    monkeypatch.setattr(d, "_probe_slot", slot)
    result = d.check_connection(Config(), d.CheckRequest(target="icloud"))
    assert result["checks"][0]["code"] == "busy"


def test_error_redacted_and_slot_released(monkeypatch):
    slot = threading.Lock()
    monkeypatch.setattr(d, "_probe_slot", slot)
    monkeypatch.setattr(d, "_checks", Mock(side_effect=RuntimeError("private password")))
    result = d.check_connection(Config(), d.CheckRequest(target="icloud"))
    assert "private password" not in str(result)
    assert result["checks"][0]["code"] == "connection_failed"
    assert slot.acquire(timeout=1)


def test_handler_check_no_persistence(handler, monkeypatch):
    before = handler.settings.config.path.read_bytes()
    monkeypatch.setattr("nanobot.webui.integrations_api.check_connection", lambda *a: {"ok": True, "read_only": True})
    assert handler.handle("check", {"target": "icloud"}).payload["read_only"]
    assert handler.handle("check", {"target": "mail", "host": "127.0.0.1"}).status == 400
    assert handler.settings.config.path.read_bytes() == before


def test_check_is_ws_only():
    assert WebUISettingsRouter.is_mutation_path("/api/settings/integrations/check")


@pytest.mark.asyncio
async def test_read_only_check_still_requires_authentication(tmp_path):
    router = _router(authorized=False, config_path=tmp_path / "config.json")
    request = _mutation_request("/api/settings/integrations/check", {"target": "icloud"})
    result = await router.dispatch(None, request, "/api/settings/integrations/check")
    assert result.status_code == 401
