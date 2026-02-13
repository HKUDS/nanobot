"""aiohttp-based HTTP server for the Anthropic Messages API proxy."""

import asyncio

from aiohttp import web
from loguru import logger

from nanobot.api.handlers import MessagesHandler


class ProxyServer:
    """Anthropic Messages API proxy server."""

    def __init__(self, host: str, port: int, handler: MessagesHandler):
        self.host = host
        self.port = port
        self.handler = handler
        self._runner: web.AppRunner | None = None

    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/v1/messages", self.handler.handle_messages)
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/", self._handle_root)
        return app

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_root(self, request: web.Request) -> web.Response:
        return web.json_response({
            "name": "nanobot-proxy",
            "description": "Anthropic Messages API proxy powered by nanobot",
            "endpoints": ["/v1/messages", "/health"],
        })

    async def start(self) -> None:
        """Start the HTTP server (non-blocking)."""
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info(f"Proxy server listening on http://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("Proxy server stopped")

    async def run_forever(self) -> None:
        """Start and block until cancelled."""
        await self.start()
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
