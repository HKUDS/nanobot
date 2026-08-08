"""DOM-based browser automation by element reference."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import Field

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.computer_use_backends.base import SessionBackendPool
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config_base import Base
from nanobot.utils.helpers import build_image_content_blocks

_ACTIONS = [
    "navigate",
    "snapshot",
    "click",
    "type",
    "select",
    "scroll",
    "key",
    "back",
    "read_text",
]


class BrowserToolConfig(Base):
    """browser (DOM) tool configuration."""

    enable: bool = False
    start_url: str = "about:blank"
    headless: bool = True
    width: int = Field(default=1280, ge=320, le=4096)
    height: int = Field(default=800, ge=240, le=4096)
    allowed_domains: list[str] = Field(default_factory=list)
    include_screenshot: bool = False
    max_elements: int = Field(default=200, ge=1, le=1000)
    max_sessions: int = Field(default=8, ge=1, le=64)


def _format_elements(elements: list[dict[str, Any]]) -> str:
    if not elements:
        return "Interactive elements: (none found — try scrolling or read_text)"
    lines: list[str] = []
    for e in elements:
        tag = str(e.get("tag") or "")
        typ = str(e.get("type") or "")
        label = tag + (f"[{typ}]" if typ else "")
        line = f"[{e.get('ref')}] {label}"
        name = str(e.get("name") or "").strip()
        if name:
            line += f' "{name}"'
        href = str(e.get("href") or "")
        if href and tag == "a":
            line += f" -> {href[:60]}"
        lines.append(line)
    return "Interactive elements (act with the [ref] number):\n" + "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema("The action to perform.", enum=_ACTIONS),
        ref=IntegerSchema(
            description="Element ref number from the latest snapshot (click/type/select).",
            minimum=1,
            nullable=True,
        ),
        text=StringSchema(
            "Text to type (action=type) or key/combo like 'Enter'/'ctrl+a' (action=key).",
            nullable=True,
        ),
        url=StringSchema("URL to open (action=navigate).", nullable=True),
        value=StringSchema("Option value/label to choose (action=select).", nullable=True),
        submit=BooleanSchema(description="Press Enter after typing (action=type).", nullable=True),
        scroll_direction=StringSchema(
            "Scroll direction (action=scroll).", enum=["up", "down", "left", "right"], nullable=True
        ),
        scroll_amount=IntegerSchema(
            description="Scroll clicks (action=scroll).",
            minimum=1,
            maximum=100,
            nullable=True,
        ),
        required=["action"],
    )
)
class BrowserTool(Tool):
    """Browse and act on web pages by element ref (DOM-based, works with any model)."""

    _scopes = {"core"}

    name = "browser"  # pyright: ignore[reportIncompatibleMethodOverride, reportAssignmentType]
    description = (  # pyright: ignore[reportIncompatibleMethodOverride, reportAssignmentType]
        "Control a web browser by acting on page elements by their [ref] number. "
        "Each call returns the current page URL plus a fresh numbered list of the page's "
        "interactive elements; pick a [ref] to click/type/select — no pixel coordinates "
        "needed. A page may already be open: call 'snapshot' FIRST to see it. Only use "
        "'navigate' for a specific URL you were explicitly given — never guess a URL. "
        "Move between pages by clicking links/buttons via their [ref]. Use 'read_text' to "
        "read page text. Re-read the element list after each action; refs are reassigned."
    )

    config_key = "browser"

    @classmethod
    def config_cls(cls) -> type[BrowserToolConfig]:
        return BrowserToolConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return bool(ctx.config.browser.enable)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(ctx.config.browser)

    def __init__(
        self,
        config: BrowserToolConfig | None = None,
        *,
        backend_impl: Any = None,
    ) -> None:
        self.config = config or BrowserToolConfig()
        runtime = None
        if backend_impl is None:
            from nanobot.agent.tools.computer_use_backends.browser_playwright import BrowserRuntime
            runtime = BrowserRuntime(headless=self.config.headless)
        self._runtime = runtime
        self._execution_lock = asyncio.Lock()
        self._backends = SessionBackendPool(
            self._make_backend,
            backend_impl,
            max_backends=self.config.max_sessions,
            finalizer=runtime.close if runtime is not None else None,
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    def _make_backend(self) -> Any:
        from nanobot.agent.tools.computer_use_backends.browser_playwright import BrowserBackend
        return BrowserBackend(
            width=self.config.width,
            height=self.config.height,
            start_url=self.config.start_url,
            allowed_domains=self.config.allowed_domains,
            runtime=self._runtime,
        )

    @staticmethod
    def _req_ref(params: dict[str, Any], action: str) -> Any:
        ref = params.get("ref")
        if ref is None:
            raise ValueError(f"action '{action}' requires an element 'ref' from the snapshot")
        return ref

    async def _dispatch(self, backend: Any, action: str, p: dict[str, Any]) -> tuple[str, str | None]:
        """Return (status, direct_text). If direct_text is set, it is returned as-is
        (no snapshot appended)."""
        if action == "navigate":
            url = p.get("url")
            if not url:
                raise ValueError("action 'navigate' requires 'url'")
            await backend.navigate(str(url))
            return f"Navigated to {url}", None

        if action == "snapshot":
            return "Snapshot of the current page", None

        if action == "click":
            ref = self._req_ref(p, action)
            await backend.click_ref(ref)
            return f"Clicked element [{ref}]", None

        if action == "type":
            ref = self._req_ref(p, action)
            text = p.get("text")
            if text is None:
                raise ValueError("action 'type' requires 'text'")
            submit = bool(p.get("submit"))
            await backend.fill_ref(ref, str(text), submit=submit)
            return f"Typed into [{ref}]" + (" and pressed Enter" if submit else ""), None

        if action == "select":
            ref = self._req_ref(p, action)
            value = p.get("value")
            if value is None:
                raise ValueError("action 'select' requires 'value'")
            await backend.select_ref(ref, str(value))
            return f"Selected '{value}' in [{ref}]", None

        if action == "scroll":
            direction = str(p.get("scroll_direction") or "down").lower()
            if direction not in ("up", "down", "left", "right"):
                raise ValueError("'scroll_direction' must be up/down/left/right")
            await backend.scroll_page(direction, int(p.get("scroll_amount") or 3))
            return f"Scrolled {direction}", None

        if action == "key":
            combo = p.get("text")
            if not combo:
                raise ValueError("action 'key' requires 'text' (e.g. 'Enter')")
            await backend.key(str(combo))
            return f"Pressed {combo}", None

        if action == "back":
            await backend.go_back()
            return "Navigated back", None

        if action == "read_text":
            txt = await backend.read_text()
            return "", f"Page text:\n{txt}"

        raise ValueError(f"unknown action '{action}'")

    async def execute(self, action: str | None = None, **kwargs: Any) -> Any:
        async with self._execution_lock:
            return await self._execute(action, **kwargs)

    async def _execute(self, action: str | None = None, **kwargs: Any) -> Any:
        action = (action or "").strip()
        if action not in _ACTIONS:
            return f"Error: unknown action '{action}'. Valid actions: {', '.join(_ACTIONS)}"

        try:
            backend = await self._backends.get()
        except ImportError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error: could not initialize browser backend: {type(exc).__name__}: {exc}"

        try:
            status, direct = await self._dispatch(backend, action, kwargs)
            if blocked := getattr(backend, "pop_blocked_navigation", lambda: None)():
                raise ValueError(f"navigation was blocked: {blocked}")
        except ValueError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error executing browser '{action}': {type(exc).__name__}: {exc}"

        if direct is not None:
            return direct

        try:
            elements = await backend.dom_snapshot(self.config.max_elements)
            snapshot = _format_elements(elements)
        except Exception as exc:
            snapshot = f"(could not read page elements: {type(exc).__name__}: {exc})"
        try:
            current = await backend.current_url()
        except Exception:
            current = ""
        header = f"{status}\nCurrent page: {current}" if current else status
        text_out = f"{header}\n\n{snapshot}"

        if self.config.include_screenshot:
            try:
                png = await backend.screenshot()
                return build_image_content_blocks(png, "image/png", "", text_out)
            except Exception:
                return text_out
        return text_out

    async def close(self) -> None:
        await self._backends.close()
