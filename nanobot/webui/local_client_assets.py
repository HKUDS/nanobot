"""Serve only the installed client's assets on each isolated host origin.

Missing files never fall through to the remote host. Remote data must not be
able to replace executable frontend code, styles, or the application's shell.
"""

from __future__ import annotations

import re
from pathlib import Path

from aiohttp import web

from nanobot.webui.build import default_webui_dist_dir

_HASHED_ASSET = re.compile(r"assets/[^/]+-[A-Za-z0-9_-]{8,}\.(?:js|css|woff2?|ttf|svg|png|webp|ico)$")
_ROOT_FILES = {"index.html", "manifest.json", "asset-manifest.json", "sw.js",
               "notification.wav", "favicon.ico", "robots.txt"}


class LocalClientAssets:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or default_webui_dist_dir()).resolve()

    @property
    def available(self) -> bool:
        return (self.directory / "index.html").is_file()

    def response(self, request: web.Request) -> web.FileResponse:
        if request.method not in {"GET", "HEAD"}:
            raise web.HTTPMethodNotAllowed(request.method, ["GET", "HEAD"])
        relative = request.path.lstrip("/") or "index.html"
        if (relative not in _ROOT_FILES and not relative.startswith(("assets/", "brand/", "fonts/"))
                or ".." in relative.split("/") or "\\" in relative):
            raise web.HTTPNotFound()
        candidate = (self.directory / relative).resolve()
        if not candidate.is_relative_to(self.directory) or not candidate.is_file():
            raise web.HTTPNotFound()
        # FileResponse may automatically choose a compressed sibling.
        for suffix in (".br", ".gz"):
            if not candidate.with_name(candidate.name + suffix).resolve().is_relative_to(self.directory):
                raise web.HTTPNotFound()
        cache = "private, max-age=31536000, immutable" if _HASHED_ASSET.fullmatch(relative) else "no-cache"
        return web.FileResponse(candidate, headers={
            "Cache-Control": cache, "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Nanobot-UI": "local",
        })
