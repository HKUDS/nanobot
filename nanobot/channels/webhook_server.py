"""Shared HTTP webhook server for channels requiring webhooks."""

import asyncio
from typing import Callable, Awaitable

from aiohttp import web
from loguru import logger


class WebhookServer:
    """
    Shared HTTP server for webhook-based channels.

    Provides a central HTTP server that multiple channels can use to
    register webhook endpoints. This is more efficient than running
    separate HTTP servers for each webhook-based channel.

    Example:
        server = WebhookServer(host="0.0.0.0", port=18790)
        await server.start()
        server.register_handler("/webhook/wechat", my_handler, methods=["GET", "POST"])
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 18790):
        """
        Initialize the webhook server.

        Args:
            host: Host to bind to (default: 0.0.0.0 for all interfaces).
            port: Port to listen on (default: 18790).
        """
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.handlers: dict[str, Callable] = {}

        # Add default health check endpoint
        self.app.router.add_get('/health', self._health_check)
        logger.debug("Webhook server initialized")

    def register_handler(
        self,
        path: str,
        handler: Callable[[web.Request], Awaitable[web.Response]],
        methods: list[str] | None = None
    ) -> None:
        """
        Register a webhook handler for a specific path.

        Args:
            path: URL path to handle (e.g., "/webhook/wechat").
            handler: Async function that handles the request.
            methods: HTTP methods to accept (default: ["POST"]).
        """
        if methods is None:
            methods = ["POST"]

        self.handlers[path] = handler

        for method in methods:
            self.app.router.add_route(method, path, handler)
            logger.debug(f"Registered {method} {path}")

    def unregister_handler(self, path: str) -> None:
        """
        Unregister a webhook handler.

        Args:
            path: URL path to unregister.
        """
        if path in self.handlers:
            del self.handlers[path]
            logger.debug(f"Unregistered {path}")

    async def start(self) -> None:
        """Start the HTTP server."""
        if self.runner is not None:
            logger.warning("Webhook server already running")
            return

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

        logger.info(f"Webhook server started on http://{self.host}:{self.port}")
        logger.info(f"Health check available at: http://{self.host}:{self.port}/health")

    async def stop(self) -> None:
        """Stop the HTTP server and clean up resources."""
        if self.runner is None:
            return

        logger.info("Stopping webhook server...")

        await self.runner.cleanup()
        self.runner = None
        self.site = None

        logger.info("Webhook server stopped")

    async def _health_check(self, request: web.Request) -> web.Response:
        """
        Health check endpoint.

        Returns a simple JSON response indicating the server is running.
        """
        return web.json_response({
            "status": "ok",
            "service": "nanobot-webhook-server",
            "endpoints": list(self.handlers.keys())
        })

    @property
    def is_running(self) -> bool:
        """Check if the server is currently running."""
        return self.runner is not None
