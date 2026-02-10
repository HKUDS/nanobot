"""Minimal HTTP server for webhook endpoints."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from nanobot.channels.manager import ChannelManager


_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error",
}


class GatewayHttpServer:
    """Serve webhook routes required by channel integrations."""

    def __init__(self, host: str, port: int, channels: ChannelManager):
        self.host = host
        self.port = port
        self.channels = channels
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        logger.info("Gateway HTTP server listening on {}:{}", self.host, self.port)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        logger.info("Gateway HTTP server stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return

            try:
                method, target, _ = request_line.decode("utf-8").strip().split(" ", 2)
            except ValueError:
                await self._write_response(writer, 400, {"status": "error", "message": "invalid request"})
                return

            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b""):
                    break
                decoded = line.decode("utf-8", errors="ignore").strip()
                if ":" not in decoded:
                    continue
                name, value = decoded.split(":", 1)
                headers[name.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0") or "0")
            body = await reader.readexactly(content_length) if content_length > 0 else b""
            path = target.split("?", 1)[0]

            if method == "GET" and path in ("/health", "/nanobot/health"):
                await self._write_response(writer, 200, {"status": "ok"})
                return

            if method != "POST":
                await self._write_response(writer, 405, {"status": "error", "message": "method not allowed"})
                return

            status, payload = await self._dispatch_webhook(path, body, headers)
            await self._write_response(writer, status, payload)
        except asyncio.IncompleteReadError:
            logger.debug("Client disconnected before request body completed")
        except Exception as e:  # noqa: BLE001
            logger.exception("Unhandled gateway HTTP error: {}", e)
            await self._write_response(writer, 500, {"status": "error", "message": "internal error"})
        finally:
            writer.close()
            await writer.wait_closed()

    async def _dispatch_webhook(
        self,
        path: str,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, Any]]:
        line_channel = self.channels.get_channel("line")
        if line_channel and path == getattr(line_channel, "webhook_path", ""):
            try:
                payload = await line_channel.handle_webhook(body, headers)
                # LINE webhook endpoint should always return 200 to platform.
                return 200, payload
            except Exception as e:  # noqa: BLE001
                logger.exception("LINE webhook handler failed: {}", e)
                return 200, {"status": "error", "message": "line handler failed"}

        return 404, {"status": "error", "message": f"route not found: {path}"}

    async def _write_response(self, writer: asyncio.StreamWriter, status: int, body: dict[str, Any]) -> None:
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        status_text = _STATUS_TEXT.get(status, "OK")
        headers = [
            f"HTTP/1.1 {status} {status_text}\r\n",
            "Content-Type: application/json; charset=utf-8\r\n",
            f"Content-Length: {len(body_bytes)}\r\n",
            "Connection: close\r\n",
            "\r\n",
        ]
        writer.writelines([h.encode("utf-8") for h in headers])
        writer.write(body_bytes)
        await writer.drain()
