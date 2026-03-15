"""HTTP webhook event trigger service."""

import asyncio
import json
from typing import Awaitable, Callable

from loguru import logger

from nanobot.config.schema import EventEndpointConfig, EventsConfig


class EventService:
    """Minimal HTTP server that fires agent tasks on POST /event/{name}."""

    def __init__(self, config: EventsConfig, host: str, port: int) -> None:
        self.config = config
        self.host = host
        self.port = port
        self.on_event: Callable[[str, EventEndpointConfig, str], Awaitable[str | None]] | None = None
        self._server: asyncio.Server | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the HTTP server and block until stopped."""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self.host,
            port=self.port,
        )
        logger.info("EventService listening on {}:{}", self.host, self.port)
        async with self._server:
            await self._server.serve_forever()

    def stop(self) -> None:
        """Stop the HTTP server."""
        self._running = False
        if self._server:
            self._server.close()
            self._server = None

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await self._process_request(reader, writer)
        except Exception as exc:
            logger.warning("EventService: unhandled error: {}", exc)
            try:
                self._send_response(writer, 500, {"error": "internal server error"})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _process_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # Read request line + headers (up to 8 KB to avoid unbounded reads)
        raw_header = b""
        while True:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=10)
            if not chunk:
                break
            raw_header += chunk
            if b"\r\n\r\n" in raw_header or b"\n\n" in raw_header:
                break
            if len(raw_header) > 8192:
                self._send_response(writer, 400, {"error": "headers too large"})
                return

        text = raw_header.decode("utf-8", errors="replace")
        header_part, _, body_part = text.partition("\r\n\r\n")
        if not _:
            header_part, _, body_part = text.partition("\n\n")

        lines = header_part.splitlines()
        if not lines:
            self._send_response(writer, 400, {"error": "empty request"})
            return

        # Parse request line
        parts = lines[0].split()
        if len(parts) < 2:
            self._send_response(writer, 400, {"error": "bad request line"})
            return
        method, path = parts[0], parts[1]

        # Parse headers into dict
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()

        # Read remaining body bytes (Content-Length based)
        body = body_part.encode("utf-8", errors="replace")
        content_length = int(headers.get("content-length", "0") or "0")
        remaining = content_length - len(body)
        if remaining > 0:
            extra = await asyncio.wait_for(reader.read(remaining), timeout=10)
            body += extra

        # Route: only POST /event/{name}
        if method != "POST":
            self._send_response(writer, 405, {"error": "method not allowed"})
            return

        if not path.startswith("/event/"):
            self._send_response(writer, 404, {"error": "not found"})
            return

        event_name = path[len("/event/"):].strip("/")
        if not event_name:
            self._send_response(writer, 400, {"error": "missing event name"})
            return

        # Auth check
        if self.config.secret:
            auth = headers.get("authorization", "")
            expected = f"Bearer {self.config.secret}"
            if auth != expected:
                self._send_response(writer, 401, {"error": "unauthorized"})
                return

        # Endpoint lookup
        endpoint = self.config.endpoints.get(event_name)
        if endpoint is None:
            self._send_response(writer, 404, {"error": f"unknown event '{event_name}'"})
            return

        # Fire callback
        payload = body.decode("utf-8", errors="replace").strip()
        logger.info("EventService: firing event '{}' (payload: {} bytes)", event_name, len(payload))
        if self.on_event:
            asyncio.create_task(self._fire(event_name, endpoint, payload))

        self._send_response(writer, 200, {"status": "ok", "event": event_name})

    async def _fire(self, name: str, endpoint: EventEndpointConfig, payload: str) -> None:
        try:
            if self.on_event:
                await self.on_event(name, endpoint, payload)
        except Exception as exc:
            logger.error("EventService: event '{}' handler error: {}", name, exc)

    # ------------------------------------------------------------------
    # HTTP response helper
    # ------------------------------------------------------------------

    @staticmethod
    def _send_response(writer: asyncio.StreamWriter, status: int, body: dict) -> None:
        status_text = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            405: "Method Not Allowed",
            500: "Internal Server Error",
        }.get(status, "Unknown")
        payload = json.dumps(body).encode("utf-8")
        response = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("utf-8") + payload
        writer.write(response)
