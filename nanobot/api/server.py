"""aiohttp-based Anthropic Messages API proxy server."""

from aiohttp import web
from loguru import logger

from nanobot.api.handlers import MessagesHandler


class ProxyServer:
    """Lightweight proxy server exposing Anthropic Messages API endpoints."""

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
            "service": "nanobot-proxy",
            "endpoints": ["/v1/messages", "/health"],
        })

    async def start(self) -> None:
        """Start the proxy server (non-blocking)."""
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Proxy server started on {}:{}", self.host, self.port)

    async def stop(self) -> None:
        """Stop the proxy server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
