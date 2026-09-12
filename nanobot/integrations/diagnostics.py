"""Explicit, bounded, read-only probes of saved Apple/IMAPS credentials.

No subprocess, redirects, arbitrary URL, proxy, mailbox selection, or mail writes.
Validated DNS addresses are pinned to the TLS socket while hostname verification
and SNI still use the saved hostname. A stuck system resolver cannot create an
unbounded number of threads: one probe owns the slot until it actually exits.
"""
from __future__ import annotations

import base64
import http.client
import ipaddress
import queue
import socket
import ssl
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from typing import Any, Literal

from defusedxml import ElementTree
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nanobot.config.schema import Config
from nanobot.integrations.credentials import CredentialStore
from nanobot.security.network import resolve_url_target

TIMEOUT_SECONDS = 12
MAX_RESPONSE_BYTES = 128_000
_probe_slot = threading.Lock()


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["icloud", "mail"]
    account_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,47}$")

    @model_validator(mode="after")
    def account_required(self) -> CheckRequest:
        if (self.target == "mail") != (self.account_id is not None):
            raise ValueError("only a mail check requires an account ID")
        return self


class ProbeError(Exception):
    """Only fixed public codes, never raw provider diagnostics."""


_MESSAGES = {
    "ok": "Połączenie TLS i uwierzytelnienie poprawne; wykonano tylko odczyt.",
    "not_configured": "Najpierw zapisz login i hasło aplikacji.",
    "unknown_account": "Nie znaleziono zapisanego konta poczty.",
    "blocked_target": "Host nie rozwiązuje się wyłącznie na dozwolone publiczne adresy.",
    "authentication_failed": "Serwer odrzucił uwierzytelnienie. Sprawdź login i hasło aplikacji.",
    "tls_failed": "Nie udało się zweryfikować bezpiecznego połączenia TLS.",
    "timeout": "Przekroczono limit czasu sprawdzania połączenia.",
    "busy": "Inny test połączenia jeszcze trwa. Spróbuj później.",
    "connection_failed": "Nie udało się połączyć z usługą.",
    "protocol_error": "Usługa nie zwróciła oczekiwanej, ograniczonej odpowiedzi.",
    "redirect_refused": "Usługa zażądała przekierowania; test nie przekazuje dalej hasła.",
    "credential_unavailable": "Nie można odczytać prywatnie zapisanego hasła aplikacji.",
}


def _result(service: str, code: str, **details: object) -> dict[str, Any]:
    return {"service": service, "ok": code == "ok", "code": code,
            "message": _MESSAGES[code], **details}


def check_connection(config: Config, request: CheckRequest) -> dict[str, Any]:
    """Return a public report, including failures; never persist probe results."""
    result: dict[str, Any] = {
        "target": request.target, "account_id": request.account_id,
        "read_only": True, "timeout_seconds": TIMEOUT_SECONDS,
    }
    if not _probe_slot.acquire(blocking=False):
        return {**result, "ok": False, "checks": [_result(request.target, "busy")]}
    out: queue.Queue[list[dict[str, Any]]] = queue.Queue(maxsize=1)
    deadline = time.monotonic() + TIMEOUT_SECONDS

    def run() -> None:
        try:
            out.put(_checks(config, request, deadline))
        except Exception:
            out.put([_result(request.target, "connection_failed")])
        finally:
            _probe_slot.release()

    try:
        threading.Thread(target=run, name="integration-read-only-check", daemon=True).start()
    except Exception:
        _probe_slot.release()
        return {**result, "ok": False, "checks": [_result(request.target, "connection_failed")]}
    try:
        checks = out.get(timeout=TIMEOUT_SECONDS)
    except queue.Empty:
        checks = [_result(request.target, "timeout")]
    return {**result, "ok": all(check["ok"] for check in checks), "checks": checks}


def _checks(config: Config, request: CheckRequest, deadline: float) -> list[dict[str, Any]]:
    settings = config.personal_integrations
    if request.target == "icloud":
        username, reference = settings.icloud.username, settings.icloud.credential_ref
        host, port = "imap.mail.me.com", 993
    else:
        account = next((a for a in settings.mail_accounts if a.id == request.account_id), None)
        if account is None:
            return [_result("imap", "unknown_account")]
        username, reference = account.username, account.credential_ref
        host, port = account.host, account.port
    if not username or not reference:
        return [_result(request.target, "not_configured")]
    try:
        password = CredentialStore(config.workspace_path).get(reference)
    except Exception:
        return [_result(request.target, "credential_unavailable")]
    results: list[dict[str, Any]] = []
    for service in (["imap", "caldav"] if request.target == "icloud" else ["imap"]):
        try:
            if service == "imap":
                count = _imap(host, port, username, password, deadline)
                results.append(_result(service, "ok", folder_count=count))
            else:
                _caldav(username, password, deadline)
                results.append(_result(service, "ok"))
        except ProbeError as exc:
            code = exc.args[0] if exc.args and exc.args[0] in _MESSAGES else "protocol_error"
            results.append(_result(service, code))
        except ssl.SSLError:
            results.append(_result(service, "tls_failed"))
        except (TimeoutError, socket.timeout):
            results.append(_result(service, "timeout"))
        except Exception:
            results.append(_result(service, "connection_failed"))
    return results


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _tls(host: str, port: int, deadline: float) -> ssl.SSLSocket:
    _remaining(deadline)
    ok, _, addresses = resolve_url_target(f"https://{host}:{port}/")
    # Diagnostics deliberately remain public-only even when a tool SSRF whitelist
    # allows private endpoints elsewhere. Block mapped IPv4 and mixed DNS answers.
    def public(ip: str) -> bool:
        address = ipaddress.ip_address(ip)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_global

    if not ok or not addresses or not all(public(ip) for ip in addresses):
        raise ProbeError("blocked_target")
    context = ssl.create_default_context()
    ip = addresses[0]
    connection = socket.socket(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM)
    try:
        connection.settimeout(min(5.0, _remaining(deadline)))
        connection.connect((ip, port))
        connection.settimeout(_remaining(deadline))
        return context.wrap_socket(connection, server_hostname=host)
    except Exception:
        connection.close()
        raise


@contextmanager
def _bounded_tls(host: str, port: int, deadline: float) -> Generator[ssl.SSLSocket, None, None]:
    with _tls(host, port, deadline) as connection:
        def interrupt() -> None:
            # http.client can perform repeated low-level reads; a total deadline
            # must also stop slow/trickling headers or chunked responses.
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)

        timer = threading.Timer(_remaining(deadline), interrupt)
        timer.daemon = True
        timer.start()
        try:
            yield connection
        finally:
            timer.cancel()


def _imap(host: str, port: int, username: str, password: str, deadline: float) -> int:
    def quoted(value: str) -> bytes:
        if any(ord(char) < 32 for char in value):
            raise ProbeError("credential_unavailable")
        return ('"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"').encode("utf-8")

    with _bounded_tls(host, port, deadline) as connection:
        pending = bytearray()
        total = 0

        def line() -> bytes:
            nonlocal total
            while b"\r\n" not in pending:
                connection.settimeout(_remaining(deadline))
                chunk = connection.recv(4096)
                total += len(chunk)
                if not chunk or total > MAX_RESPONSE_BYTES:
                    raise ProbeError("protocol_error")
                pending.extend(chunk)
            data, _, rest = pending.partition(b"\r\n")
            pending[:] = rest
            return bytes(data)

        if not line().upper().startswith(b"* OK"):
            raise ProbeError("protocol_error")
        connection.sendall(b"a1 LOGIN " + quoted(username) + b" " + quoted(password) + b"\r\n")
        folders = 0
        for tag in (b"a1", b"a2"):
            while True:
                response = line()
                if response.startswith(tag + b" "):
                    if not response.upper().startswith(tag.upper() + b" OK"):
                        raise ProbeError("authentication_failed" if tag == b"a1" else "protocol_error")
                    break
                if response.upper().startswith(b"* LIST "):
                    folders += 1
            if tag == b"a1":
                connection.settimeout(_remaining(deadline))
                connection.sendall(b'a2 LIST "" "*"\r\n')
        return folders


def _caldav(username: str, password: str, deadline: float) -> None:
    body = b'<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
    authorization = base64.b64encode(f"{username}:{password}".encode("utf-8"))
    with _bounded_tls("caldav.icloud.com", 443, deadline) as connection:
        connection.sendall(
            b"PROPFIND / HTTP/1.1\r\nHost: caldav.icloud.com\r\nDepth: 0\r\n"
            b"Content-Type: application/xml; charset=utf-8\r\nConnection: close\r\n"
            b"Authorization: Basic " + authorization + b"\r\nContent-Length: "
            + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)
        response = http.client.HTTPResponse(connection)
        try:
            response.begin()
            if response.status in (401, 403):
                raise ProbeError("authentication_failed")
            if 300 <= response.status < 400:
                raise ProbeError("redirect_refused")
            if response.status != 207:
                raise ProbeError("protocol_error")
            connection.settimeout(_remaining(deadline))
            content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                raise ProbeError("protocol_error")
            root = ElementTree.fromstring(content)
            principal = root.find(".//{DAV:}current-user-principal/{DAV:}href")
            if principal is None or not principal.text:
                raise ProbeError("authentication_failed")
        finally:
            response.close()
