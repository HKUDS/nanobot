"""computer_use tool: control a desktop or browser via screenshots + mouse/keyboard.

Model-agnostic by design. The tool returns each screenshot as ``image_url``
content blocks; the runner delivers those to the model as a follow-up user
message, so any vision + tool-calling model works (Claude, GPT, Gemini, ... via
any gateway such as OpenRouter) without provider-specific plumbing.

Backends (selected via config) are pluggable:
- ``desktop`` — PyAutoGUI, controls the local GUI (Codex-style).
- ``browser`` — Playwright, controls a headless web page (also supports navigate).

Both heavy deps are optional and imported lazily, so importing this module at
tool auto-discovery time is cheap and never requires pyautogui/playwright.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any
from urllib.parse import urlparse

from loguru import logger
from pydantic import Field

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import (
    IntegerSchema,
    NumberSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config.schema import Base
from nanobot.utils.helpers import build_image_content_blocks
from nanobot.utils.screen_scale import ScreenScaler, fit_target_size

_ACTIONS = [
    "screenshot",
    "left_click",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "mouse_move",
    "left_click_drag",
    "scroll",
    "type",
    "key",
    "wait",
    "navigate",
]

_CLICK_BUTTONS = {
    "left_click": "left",
    "double_click": "left",
    "triple_click": "left",
    "right_click": "right",
    "middle_click": "middle",
}
_CLICK_COUNTS = {"double_click": 2, "triple_click": 3}

_MAX_WAIT_S = 10.0
_ENABLE_WARNED = False  # log the security warning at most once per process


class ComputerUseToolConfig(Base):
    """computer_use tool configuration."""

    enable: bool = False  # off by default — security-sensitive, opt-in
    backend: str = "desktop"  # "desktop" | "browser"
    target_width: int = 1280  # screenshot is downscaled to fit this box (model space)
    target_height: int = 800
    require_approval: bool = True  # gate destructive actions (enforced by the agent layer)
    allowed_domains: list[str] = Field(default_factory=list)  # browser allowlist; empty = all
    start_url: str = "about:blank"  # browser initial page
    headless: bool = True  # browser headless mode


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema("The action to perform.", enum=_ACTIONS),
        x=IntegerSchema(
            description="X coordinate in the pixel space of the screenshot you were last shown.",
            nullable=True,
        ),
        y=IntegerSchema(
            description="Y coordinate in the pixel space of the screenshot you were last shown.",
            nullable=True,
        ),
        text=StringSchema(
            "Text to type (action=type), or a key/combo like 'ctrl+s' or 'Enter' (action=key).",
            nullable=True,
        ),
        scroll_direction=StringSchema(
            "Scroll direction (action=scroll).", enum=["up", "down", "left", "right"], nullable=True
        ),
        scroll_amount=IntegerSchema(
            description="Number of scroll clicks (action=scroll).", nullable=True
        ),
        duration=NumberSchema(description="Seconds to wait (action=wait).", nullable=True),
        url=StringSchema("URL to open (action=navigate, browser backend only).", nullable=True),
        required=["action"],
    )
)
class ComputerUseTool(Tool):
    """Control a computer (desktop or browser) by looking at screenshots and acting."""

    _scopes = {"core"}  # never exposed to subagents — security-sensitive

    name = "computer_use"
    description = (
        "Control a computer via screenshots and mouse/keyboard. Each call performs ONE "
        "action and returns a fresh screenshot of the resulting screen. Coordinates (x, y) "
        "are in the pixel space of the screenshot you were last shown (top-left is 0,0). "
        "The 'browser' backend additionally supports the 'navigate' action. Always start "
        "with a 'screenshot' to see the screen, then act based on what you observe; after "
        "each action re-check the new screenshot before the next step."
    )

    config_key = "computer_use"

    @classmethod
    def config_cls(cls) -> type[ComputerUseToolConfig]:
        return ComputerUseToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return bool(ctx.config.computer_use.enable)

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        cfg = ctx.config.computer_use
        global _ENABLE_WARNED
        if not _ENABLE_WARNED:
            logger.warning(
                "computer_use tool is ENABLED (backend={}). It can control the real "
                "{} and affect state outside the workspace. Run nanobot in a sandbox/VM, "
                "restrict to trusted models/inputs, and beware prompt injection from "
                "on-screen/web content.",
                cfg.backend,
                "browser" if cfg.backend == "browser" else "desktop",
            )
            _ENABLE_WARNED = True
        return cls(
            backend=cfg.backend,
            target_width=cfg.target_width,
            target_height=cfg.target_height,
            require_approval=cfg.require_approval,
            allowed_domains=list(cfg.allowed_domains),
            start_url=cfg.start_url,
            headless=cfg.headless,
        )

    def __init__(
        self,
        *,
        backend: str = "desktop",
        target_width: int = 1280,
        target_height: int = 800,
        require_approval: bool = True,
        allowed_domains: list[str] | None = None,
        start_url: str = "about:blank",
        headless: bool = True,
        backend_impl: Any = None,
    ) -> None:
        self.backend_name = backend
        self.target_width = target_width
        self.target_height = target_height
        self.require_approval = require_approval
        self.allowed_domains = allowed_domains or []
        self.start_url = start_url
        self.headless = headless
        self._backend = backend_impl  # injectable for tests

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        # Stateful single environment; must not run alongside other tools.
        return True

    async def _get_backend(self) -> Any:
        if self._backend is not None:
            return self._backend
        if self.backend_name == "browser":
            from nanobot.agent.tools.computer_use_backends.browser_playwright import BrowserBackend
            self._backend = BrowserBackend(
                width=self.target_width,
                height=self.target_height,
                headless=self.headless,
                start_url=self.start_url,
            )
        else:
            from nanobot.agent.tools.computer_use_backends.desktop_pyautogui import DesktopBackend
            self._backend = DesktopBackend()
        return self._backend

    @staticmethod
    def _downscale_png(png: bytes, target: tuple[int, int]) -> bytes:
        try:
            from PIL import Image  # noqa: PLC0415
        except Exception as exc:
            raise ImportError(
                "Pillow is required for computer_use. Install: pip install 'nanobot-ai[computer-use]'"
            ) from exc
        tw, th = target
        with Image.open(io.BytesIO(png)) as img:
            if (img.width, img.height) == (tw, th):
                return png
            resized = img.convert("RGB").resize((tw, th))
            out = io.BytesIO()
            resized.save(out, format="PNG")
            return out.getvalue()

    def _domain_allowed(self, url: str) -> bool:
        """Check a navigation URL against the browser allowed_domains policy.

        Empty allowlist = allow all. A domain entry matches the exact host or any
        subdomain of it (``example.com`` allows ``app.example.com``).
        """
        if not self.allowed_domains:
            return True
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        for dom in self.allowed_domains:
            d = dom.lower().lstrip(".")
            if d and (host == d or host.endswith("." + d)):
                return True
        return False

    async def _dispatch(self, backend: Any, scaler: ScreenScaler, action: str, params: dict[str, Any]) -> str:
        def _xy() -> tuple[int, int]:
            x, y = params.get("x"), params.get("y")
            # Some models emit a combined [x, y] array in the x field (this is
            # Anthropic's native ``coordinate`` convention). Accept that too so
            # the tool is not tied to one provider's calling style.
            if isinstance(x, (list, tuple)) and len(x) == 2 and y is None:
                x, y = x[0], x[1]
            if x is None or y is None:
                raise ValueError(f"action '{action}' requires integer 'x' and 'y'")
            return scaler.to_real(int(x), int(y))

        if action == "screenshot":
            return "Took a screenshot"

        if action == "wait":
            secs = float(params.get("duration") or 1.0)
            secs = max(0.0, min(secs, _MAX_WAIT_S))
            await asyncio.sleep(secs)
            return f"Waited {secs:g}s"

        if action in _CLICK_BUTTONS:
            rx, ry = _xy()
            await backend.click(rx, ry, _CLICK_BUTTONS[action], _CLICK_COUNTS.get(action, 1))
            return f"{action} at ({rx}, {ry})"

        if action == "mouse_move":
            rx, ry = _xy()
            await backend.move(rx, ry)
            return f"Moved to ({rx}, {ry})"

        if action == "left_click_drag":
            rx, ry = _xy()
            await backend.drag(rx, ry)
            return f"Dragged to ({rx}, {ry})"

        if action == "scroll":
            rx, ry = _xy()
            direction = str(params.get("scroll_direction") or "down").lower()
            if direction not in ("up", "down", "left", "right"):
                raise ValueError("'scroll_direction' must be up/down/left/right")
            amount = int(params.get("scroll_amount") or 3)
            await backend.scroll(rx, ry, direction, amount)
            return f"Scrolled {direction} by {amount} at ({rx}, {ry})"

        if action == "type":
            text = params.get("text")
            if not text:
                raise ValueError("action 'type' requires 'text'")
            await backend.type_text(str(text))
            return f"Typed {len(str(text))} characters"

        if action == "key":
            combo = params.get("text")
            if not combo:
                raise ValueError("action 'key' requires 'text' (e.g. 'ctrl+s')")
            await backend.key(str(combo))
            return f"Pressed {combo}"

        if action == "navigate":
            url = params.get("url")
            if not url:
                raise ValueError("action 'navigate' requires 'url'")
            if not self._domain_allowed(str(url)):
                raise ValueError(
                    f"navigation to '{url}' is blocked by the allowed_domains policy"
                )
            await backend.navigate(str(url))
            return f"Navigated to {url}"

        raise ValueError(f"unknown action '{action}'")

    async def execute(self, action: str | None = None, **kwargs: Any) -> Any:
        action = (action or "").strip()
        if action not in _ACTIONS:
            return f"Error: unknown action '{action}'. Valid actions: {', '.join(_ACTIONS)}"

        try:
            backend = await self._get_backend()
            real_w, real_h = await backend.dimensions()
        except ImportError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error: could not initialize computer_use backend: {type(exc).__name__}: {exc}"

        scaler = ScreenScaler.for_screen(real_w, real_h, self.target_width, self.target_height)

        try:
            status = await self._dispatch(backend, scaler, action, kwargs)
        except ValueError as exc:
            return f"Error: {exc}"
        except NotImplementedError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error executing computer_use '{action}': {type(exc).__name__}: {exc}"

        # Return a fresh screenshot so the model sees the result of its action.
        try:
            png = await backend.screenshot()
            target = fit_target_size(real_w, real_h, self.target_width, self.target_height)
            png = self._downscale_png(png, target)
        except ImportError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"{status}\n(Could not capture screenshot: {type(exc).__name__}: {exc})"

        label = f"{status} | screen {target[0]}x{target[1]} ({backend.environment})"
        return build_image_content_blocks(png, "image/png", "", label)

    async def close(self) -> None:
        if self._backend is not None:
            await self._backend.close()
