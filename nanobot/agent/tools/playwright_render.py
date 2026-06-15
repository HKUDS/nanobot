"""Playwright render tool — HTML/CSS → PNG or PDF via headless Chromium.

Supports:
  - Local HTML file path  (file:///...)
  - Inline HTML string
  - Optional CSS selector to screenshot a specific element (e.g. '#stage')
  - Output: PNG (default) or PDF

Usage by Frank:
  playwright_render(
      html="/path/to/template.html",
      selector="#stage",
      output="/tmp/sebo_post_01.png",
  )
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.path_utils import resolve_workspace_path
from nanobot.agent.tools.context import ToolContext
from nanobot.config.paths import get_media_dir


@tool_parameters({
    "type": "object",
    "properties": {
        "html": {
            "type": "string",
            "description": (
                "Absolute path to a local HTML file, OR inline HTML string. "
                "If it starts with '<' it is treated as inline HTML."
            ),
        },
        "output": {
            "type": "string",
            "description": (
                "Absolute output path. Extension determines format: "
                ".png → screenshot, .pdf → PDF. "
                "Defaults to a timestamped PNG in the nanobot media directory."
            ),
        },
        "selector": {
            "type": "string",
            "description": (
                "Optional CSS selector. When provided, only that element is captured "
                "(e.g. '#stage' for a fixed-size 1080×1350 post stage). "
                "Omit to capture the full page."
            ),
        },
        "width": {
            "type": "integer",
            "description": "Viewport width in px (default: 1920).",
        },
        "height": {
            "type": "integer",
            "description": "Viewport height in px (default: 1080).",
        },
        "wait_for": {
            "type": "string",
            "description": (
                "Optional CSS selector or JS expression to wait for before capture. "
                "Useful when fonts or images load asynchronously."
            ),
        },
    },
    "required": ["html"],
})
class PlaywrightRenderTool(Tool):
    """Render an HTML template to PNG or PDF using headless Chromium."""

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    @classmethod
    def create(cls, ctx: Any) -> "PlaywrightRenderTool":
        workspace = getattr(ctx, "workspace", None)
        allowed_dir = getattr(ctx, "allowed_dir", None)
        return cls(workspace=workspace, allowed_dir=allowed_dir)

    def __init__(
        self,
        *,
        workspace: str | Path | None = None,
        allowed_dir: str | Path | None = None,
    ) -> None:
        self._workspace = Path(workspace).expanduser() if workspace else None
        self._allowed_dir = Path(allowed_dir).expanduser() if allowed_dir else None

    @property
    def name(self) -> str:
        return "playwright_render"

    @property
    def description(self) -> str:
        return (
            "Render an HTML template to a PNG image or PDF using headless Chromium. "
            "Pass a local HTML file path or inline HTML. "
            "Use selector='#stage' to capture a specific fixed-size element (e.g. a 1080×1350 post stage). "
            "Returns the output file path."
        )

    def _default_output(self, fmt: str) -> Path:
        import datetime
        media = get_media_dir()
        renders_dir = media / "renders" / datetime.date.today().isoformat()
        renders_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%H%M%S_%f")[:11]
        return renders_dir / f"render_{ts}.{fmt}"

    async def execute(
        self,
        html: str,
        output: str | None = None,
        selector: str | None = None,
        width: int = 1920,
        height: int = 1080,
        wait_for: str | None = None,
        **_kwargs: Any,
    ) -> str:
        from playwright.async_api import async_playwright

        # --- determine output path and format ---
        if output:
            out_path = Path(output).expanduser()
        else:
            out_path = self._default_output("png")

        fmt = out_path.suffix.lstrip(".").lower()
        if fmt not in ("png", "pdf"):
            return f"Error: unsupported output format '{fmt}'. Use .png or .pdf"

        out_path.parent.mkdir(parents=True, exist_ok=True)

        # --- resolve HTML source ---
        is_inline = html.strip().startswith("<")
        if is_inline:
            # write to temp file so Playwright can load it with file:// (font/asset loading)
            tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
            tmp.write(html)
            tmp.close()
            url = f"file://{tmp.name}"
            tmp_path = tmp.name
        else:
            html_path = Path(html).expanduser()
            if not html_path.is_file():
                return f"Error: HTML file not found: {html}"
            url = f"file://{html_path.resolve()}"
            tmp_path = None

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": width, "height": height})

                await page.goto(url, wait_until="networkidle")

                if wait_for:
                    # try as selector first, then as JS expression
                    try:
                        await page.wait_for_selector(wait_for, timeout=5000)
                    except Exception:
                        try:
                            await page.evaluate(wait_for)
                        except Exception:
                            pass

                if fmt == "pdf":
                    await page.pdf(path=str(out_path), print_background=True)
                else:
                    if selector:
                        element = await page.query_selector(selector)
                        if element is None:
                            await browser.close()
                            return f"Error: selector '{selector}' not found in page"
                        await element.screenshot(path=str(out_path))
                    else:
                        await page.screenshot(path=str(out_path), full_page=True)

                await browser.close()

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return str(out_path)
