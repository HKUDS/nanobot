"""Small HTTP ingress served on the nanobot gateway port."""

from __future__ import annotations

import asyncio
import email.utils
import http
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from nanobot.webhooks import WebhookRouter

_MAX_HEADER_BYTES = 65_536
_READ_CHUNK_BYTES = 4096
_DEFAULT_READ_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class HTTPRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    remote: str | None


class HTTPRequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class GatewayHTTPIngress:
    """Serve health and webhook HTTP routes without depending on WebUI."""

    def __init__(
        self,
        *,
        webhook_router: WebhookRouter | None = None,
        log: Any | None = None,
        read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S,
    ) -> None:
        self.webhook_router = webhook_router
        self._log = log
        self._read_timeout_s = read_timeout_s

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request = await self._read_request(reader, writer)
            if request is None:
                return
            status, payload, as_json = await self._dispatch(request)
            if as_json:
                await _write_json(writer, status, payload)
            else:
                await _write_text(writer, status, str(payload))
        except HTTPRequestError as exc:
            await _write_json(writer, exc.status, {"ok": False, "error": exc.message})
        except Exception as exc:
            if self._log is not None:
                self._log.exception("gateway HTTP request failed: {}", exc)
            await _write_json(writer, 500, {"ok": False, "error": "Internal Server Error"})
        finally:
            writer.close()
            wait_closed = getattr(writer, "wait_closed", None)
            if callable(wait_closed):
                try:
                    await wait_closed()
                except OSError:
                    pass

    async def _read_request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> HTTPRequest | None:
        remote = _remote_address(writer)
        header_block, body_prefix = await _read_header_block(
            reader,
            read_timeout_s=self._read_timeout_s,
        )
        if not header_block:
            return None
        request_line, headers = _parse_headers(header_block)
        method, target, _version = _parse_request_line(request_line)
        path = _target_path(target)
        body_limit = self._body_limit_for_path(path)
        body = await _read_body(
            reader,
            headers,
            body_prefix,
            body_limit=body_limit,
            read_timeout_s=self._read_timeout_s,
        )
        return HTTPRequest(
            method=method,
            path=path,
            headers=headers,
            body=body,
            remote=remote,
        )

    def _body_limit_for_path(self, path: str) -> int:
        if self.webhook_router is None:
            return 1_048_576
        return self.webhook_router.body_limit_for_path(path)

    async def _dispatch(self, request: HTTPRequest) -> tuple[int, dict[str, Any] | str, bool]:
        if request.method.upper() == "GET" and request.path == "/health":
            return 200, {"status": "ok"}, True

        if self.webhook_router is not None:
            response = await self.webhook_router.handle(
                method=request.method,
                path=request.path,
                headers=request.headers,
                body=request.body,
                remote=request.remote,
            )
            if response is not None:
                return response.status, response.body, True

        return 404, "Not Found", False


async def run_gateway_http_ingress(
    *,
    host: str,
    port: int,
    webhook_router: WebhookRouter | None = None,
    log: Any | None = None,
    read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S,
) -> None:
    """Run the gateway HTTP ingress until cancelled."""

    ingress = GatewayHTTPIngress(
        webhook_router=webhook_router,
        log=log,
        read_timeout_s=read_timeout_s,
    )
    server = await asyncio.start_server(ingress.handle_connection, host, port)
    if log is not None:
        log.info("Gateway HTTP ingress listening on http://{}:{}", host, port)
    async with server:
        await server.serve_forever()


async def _read_header_block(
    reader: asyncio.StreamReader,
    *,
    read_timeout_s: float,
) -> tuple[bytes, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        try:
            chunk = await asyncio.wait_for(
                reader.read(_READ_CHUNK_BYTES),
                timeout=read_timeout_s,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPRequestError(408, "Request timed out") from exc
        if not chunk:
            break
        data += chunk
        if len(data) > _MAX_HEADER_BYTES:
            raise HTTPRequestError(431, "Request headers too large")
    if not data:
        return b"", b""
    try:
        header_block, body_prefix = data.split(b"\r\n\r\n", 1)
    except ValueError as exc:
        raise HTTPRequestError(400, "Malformed HTTP request") from exc
    return header_block, body_prefix


def _parse_headers(header_block: bytes) -> tuple[str, dict[str, str]]:
    try:
        text = header_block.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise HTTPRequestError(400, "Malformed HTTP headers") from exc
    lines = text.split("\r\n")
    if not lines or not lines[0].strip():
        raise HTTPRequestError(400, "Missing request line")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise HTTPRequestError(400, "Malformed HTTP header")
        key, value = line.split(":", 1)
        normalized = key.strip().lower()
        if not normalized:
            raise HTTPRequestError(400, "Malformed HTTP header")
        value = value.strip()
        if normalized in headers:
            headers[normalized] = f"{headers[normalized]}, {value}"
        else:
            headers[normalized] = value
    return lines[0], headers


def _parse_request_line(line: str) -> tuple[str, str, str]:
    parts = line.split()
    if len(parts) != 3:
        raise HTTPRequestError(400, "Malformed request line")
    method, target, version = parts
    if not version.startswith("HTTP/"):
        raise HTTPRequestError(400, "Malformed HTTP version")
    return method.upper(), target, version


def _target_path(target: str) -> str:
    parsed = urlsplit(target)
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


async def _read_body(
    reader: asyncio.StreamReader,
    headers: dict[str, str],
    body_prefix: bytes,
    *,
    body_limit: int,
    read_timeout_s: float,
) -> bytes:
    transfer_encoding = headers.get("transfer-encoding", "").lower()
    if transfer_encoding and transfer_encoding != "identity":
        raise HTTPRequestError(501, "Transfer-Encoding is not supported")

    content_length_raw = headers.get("content-length")
    if content_length_raw is None:
        return b""
    try:
        content_length = int(content_length_raw)
    except ValueError as exc:
        raise HTTPRequestError(400, "Invalid Content-Length") from exc
    if content_length < 0:
        raise HTTPRequestError(400, "Invalid Content-Length")
    if content_length > body_limit:
        raise HTTPRequestError(413, "Request body too large")
    if len(body_prefix) >= content_length:
        return body_prefix[:content_length]
    try:
        rest = await asyncio.wait_for(
            reader.readexactly(content_length - len(body_prefix)),
            timeout=read_timeout_s,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPRequestError(408, "Request timed out") from exc
    except asyncio.IncompleteReadError as exc:
        raise HTTPRequestError(400, "Incomplete request body") from exc
    return body_prefix + rest


def _remote_address(writer: asyncio.StreamWriter) -> str | None:
    get_extra_info = getattr(writer, "get_extra_info", None)
    if not callable(get_extra_info):
        return None
    peer = get_extra_info("peername")
    if isinstance(peer, tuple) and peer:
        return str(peer[0])
    return str(peer) if peer else None


async def _write_json(
    writer: asyncio.StreamWriter,
    status: int,
    payload: dict[str, Any],
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    reason = http.HTTPStatus(status).phrase
    headers = [
        f"HTTP/1.0 {status} {reason}",
        f"Date: {email.utils.formatdate(usegmt=True)}",
        "Connection: close",
        "Content-Type: application/json; charset=utf-8",
        f"Content-Length: {len(body)}",
        "",
        "",
    ]
    writer.write("\r\n".join(headers).encode("ascii") + body)
    await writer.drain()


async def _write_text(
    writer: asyncio.StreamWriter,
    status: int,
    payload: str,
) -> None:
    body = payload.encode("utf-8")
    reason = http.HTTPStatus(status).phrase
    headers = [
        f"HTTP/1.0 {status} {reason}",
        f"Date: {email.utils.formatdate(usegmt=True)}",
        "Connection: close",
        "Content-Type: text/plain; charset=utf-8",
        f"Content-Length: {len(body)}",
        "",
        "",
    ]
    writer.write("\r\n".join(headers).encode("ascii") + body)
    await writer.drain()
