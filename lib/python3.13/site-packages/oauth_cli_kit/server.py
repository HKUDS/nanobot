"""Local OAuth callback server."""

from __future__ import annotations

import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

from oauth_cli_kit.constants import SUCCESS_HTML


class _OAuthHandler(BaseHTTPRequestHandler):
    """Local callback HTTP handler."""

    server_version = "OAuthCliKit/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        try:
            url = urllib.parse.urlparse(self.path)
            if url.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            qs = urllib.parse.parse_qs(url.query)
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]

            if state != self.server.expected_state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch")
                return

            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code")
                return

            self.server.code = code
            try:
                if getattr(self.server, "on_code", None):
                    self.server.on_code(code)
            except Exception:
                pass
            body = SUCCESS_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            try:
                self.wfile.flush()
            except Exception:
                pass
            self.close_connection = True
        except Exception:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal error")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Suppress default logs to avoid noisy output.
        return


class _OAuthServer(HTTPServer):
    """OAuth callback server with state."""

    def __init__(
        self,
        server_address: tuple[str, int],
        expected_state: str,
        on_code: Callable[[str], None] | None = None,
    ):
        super().__init__(server_address, _OAuthHandler)
        self.expected_state = expected_state
        self.code: str | None = None
        self.on_code = on_code


def _start_local_server(
    state: str,
    on_code: Callable[[str], None] | None = None,
) -> tuple[_OAuthServer | None, str | None]:
    """Start a local OAuth callback server on the first available localhost address."""
    try:
        addrinfos = socket.getaddrinfo("localhost", 1455, type=socket.SOCK_STREAM)
    except OSError as exc:
        return None, f"Failed to resolve localhost: {exc}"

    last_error: OSError | None = None
    for family, _socktype, _proto, _canonname, sockaddr in addrinfos:
        try:
            # Support IPv4/IPv6 to avoid missing callbacks when localhost resolves to ::1.
            class _AddrOAuthServer(_OAuthServer):
                address_family = family

            server = _AddrOAuthServer(sockaddr, state, on_code=on_code)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            return server, None
        except OSError as exc:
            last_error = exc
            continue

    if last_error:
        return None, f"Local callback server failed to start: {last_error}"
    return None, "Local callback server failed to start: unknown error"
