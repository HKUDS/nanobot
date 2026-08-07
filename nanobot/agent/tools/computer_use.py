"""Screenshot-based computer control."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import asyncio
import io
from typing import Any, Literal

from pydantic import Field

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.computer_use_backends.base import SessionBackendPool
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import (
    IntegerSchema,
    NumberSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config_base import Base
from nanobot.utils.helpers import build_image_content_blocks

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


class ComputerUseToolConfig(Base):
    """computer_use tool configuration."""

    enable: bool = False
    backend: Literal["desktop", "browser"] = "desktop"
    target_width: int = Field(default=1280, ge=320, le=4096)
    target_height: int = Field(default=800, ge=240, le=4096)
    allowed_domains: list[str] = Field(default_factory=list)
    start_url: str = "about:blank"
    headless: bool = True


def _fit_size(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return max(1, max_width), max(1, max_height)
    scale = min(max_width / width, max_height / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _scale_point(
    x: int,
    y: int,
    source: tuple[int, int],
    target: tuple[int, int],
) -> tuple[int, int]:
    width, height = source
    target_width, target_height = target
    real_x = round(x * width / target_width) if target_width else x
    real_y = round(y * height / target_height) if target_height else y
    return (
        max(0, min(real_x, max(0, width - 1))),
        max(0, min(real_y, max(0, height - 1))),
    )


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
            description="Number of scroll clicks (action=scroll).",
            minimum=1,
            maximum=100,
            nullable=True,
        ),
        duration=NumberSchema(
            description="Seconds to wait (action=wait).",
            minimum=0,
            maximum=_MAX_WAIT_S,
            nullable=True,
        ),
        url=StringSchema("URL to open (action=navigate, browser backend only).", nullable=True),
        required=["action"],
    )
)
class ComputerUseTool(Tool):
    """Control a computer (desktop or browser) by looking at screenshots and acting."""

    _scopes = {"core"}  # never exposed to subagents — security-sensitive

    name = "computer_use"  # pyright: ignore[reportIncompatibleMethodOverride, reportAssignmentType]
    description = (  # pyright: ignore[reportIncompatibleMethodOverride, reportAssignmentType]
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
    def enabled(cls, ctx: ToolContext) -> bool:
        return bool(ctx.config.computer_use.enable)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(ctx.config.computer_use)

    def __init__(
        self,
        config: ComputerUseToolConfig | None = None,
        *,
        backend_impl: Any = None,
    ) -> None:
        self.config = config or ComputerUseToolConfig()
        runtime = None
        if backend_impl is None and self.config.backend == "browser":
            from nanobot.agent.tools.computer_use_backends.browser_playwright import BrowserRuntime
            runtime = BrowserRuntime(headless=self.config.headless)
        self._runtime = runtime
        self._backends = SessionBackendPool(
            self._make_backend,
            backend_impl,
            finalizer=runtime.close if runtime is not None else None,
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        # Stateful single environment; must not run alongside other tools.
        return True

    def _make_backend(self) -> Any:
        if self.config.backend == "browser":
            from nanobot.agent.tools.computer_use_backends.browser_playwright import BrowserBackend
            return BrowserBackend(
                width=self.config.target_width,
                height=self.config.target_height,
                start_url=self.config.start_url,
                allowed_domains=self.config.allowed_domains,
                runtime=self._runtime,
            )
        from nanobot.agent.tools.computer_use_backends.desktop_pyautogui import DesktopBackend
        return DesktopBackend()

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
            resized = img.convert("RGB").resize((tw, th))  # pyright: ignore[reportUnknownMemberType]
            out = io.BytesIO()
            resized.save(out, format="PNG")
            return out.getvalue()

    async def _dispatch(
        self,
        backend: Any,
        action: str,
        params: dict[str, Any],
        source: tuple[int, int],
        target: tuple[int, int],
    ) -> str:
        def _xy() -> tuple[int, int]:
            x, y = params.get("x"), params.get("y")
            if x is None or y is None:
                raise ValueError(f"action '{action}' requires integer 'x' and 'y'")
            return _scale_point(int(x), int(y), source, target)

        if action == "screenshot":
            return "Took a screenshot"

        if action == "wait":
            duration = params.get("duration")
            secs = 1.0 if duration is None else float(duration)
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
            await backend.navigate(str(url))
            return f"Navigated to {url}"

        raise ValueError(f"unknown action '{action}'")

    async def execute(self, action: str | None = None, **kwargs: Any) -> Any:
        action = (action or "").strip()
        if action not in _ACTIONS:
            return f"Error: unknown action '{action}'. Valid actions: {', '.join(_ACTIONS)}"

        try:
            backend = self._backends.get()
            real_w, real_h = await backend.dimensions()
        except ImportError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error: could not initialize computer_use backend: {type(exc).__name__}: {exc}"

        source = (real_w, real_h)
        target = _fit_size(real_w, real_h, self.config.target_width, self.config.target_height)

        try:
            status = await self._dispatch(backend, action, kwargs, source, target)
            if blocked := getattr(backend, "pop_blocked_navigation", lambda: None)():
                raise ValueError(f"navigation was blocked: {blocked}")
        except ValueError as exc:
            return f"Error: {exc}"
        except NotImplementedError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error executing computer_use '{action}': {type(exc).__name__}: {exc}"

        # Return a fresh screenshot so the model sees the result of its action.
        try:
            png = await backend.screenshot()
            png = self._downscale_png(png, target)
        except ImportError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"{status}\n(Could not capture screenshot: {type(exc).__name__}: {exc})"

        label = f"{status} | screen {target[0]}x{target[1]} ({backend.environment})"
        return build_image_content_blocks(png, "image/png", "", label)

    async def close(self) -> None:
        await self._backends.close()
