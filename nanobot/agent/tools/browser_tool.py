"""browser tool: DOM/accessibility-based web automation (model-agnostic actions).

Unlike the pixel-based ``computer_use`` tool, this drives the page by **element
ref** instead of by screen coordinates. Each action returns a fresh snapshot of
the page's interactive elements (a numbered list), and the model acts by picking
a ``[ref]`` — no pixel grounding required. This makes web *actions* reliable
across ANY tool-calling model (including non-vision models), which pixel-based
computer use cannot do (only computer-use-trained models ground pixels well).

It reuses the Playwright ``BrowserBackend`` from ``computer_use_backends``. The
heavy ``playwright`` dependency is imported lazily, so importing this module at
tool auto-discovery time stays cheap.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from loguru import logger
from pydantic import Field

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config.schema import Base
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
_ENABLE_WARNED = False


class BrowserToolConfig(Base):
    """browser (DOM) tool configuration."""

    enable: bool = False  # off by default — opt-in
    start_url: str = "about:blank"
    headless: bool = True
    width: int = 1280
    height: int = 800
    allowed_domains: list[str] = Field(default_factory=list)  # empty = all
    include_screenshot: bool = False  # also attach a screenshot (for vision models)
    max_elements: int = 200  # cap interactive elements per snapshot


def _format_elements(elements: list[dict]) -> str:
    if not elements:
        return "Interactive elements: (none found — try scrolling or read_text)"
    lines = []
    for e in elements:
        tag = e.get("tag", "")
        typ = e.get("type") or ""
        label = tag + (f"[{typ}]" if typ else "")
        line = f"[{e.get('ref')}] {label}"
        name = (e.get("name") or "").strip()
        if name:
            line += f' "{name}"'
        href = e.get("href") or ""
        if href and tag == "a":
            line += f" -> {href[:60]}"
        lines.append(line)
    return "Interactive elements (act with the [ref] number):\n" + "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema("The action to perform.", enum=_ACTIONS),
        ref=IntegerSchema(
            description="Element ref number from the latest snapshot (click/type/select).",
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
        scroll_amount=IntegerSchema(description="Scroll clicks (action=scroll).", nullable=True),
        required=["action"],
    )
)
class BrowserTool(Tool):
    """Browse and act on web pages by element ref (DOM-based, works with any model)."""

    _scopes = {"core"}

    name = "browser"
    description = (
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
    def enabled(cls, ctx: Any) -> bool:
        return bool(ctx.config.browser.enable)

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        cfg = ctx.config.browser
        global _ENABLE_WARNED
        if not _ENABLE_WARNED:
            logger.warning(
                "browser tool is ENABLED — it can navigate and act on web pages. "
                "Restrict with allowed_domains, run in a sandbox, and beware prompt "
                "injection from page content."
            )
            _ENABLE_WARNED = True
        return cls(
            start_url=cfg.start_url,
            headless=cfg.headless,
            width=cfg.width,
            height=cfg.height,
            allowed_domains=list(cfg.allowed_domains),
            include_screenshot=cfg.include_screenshot,
            max_elements=cfg.max_elements,
        )

    def __init__(
        self,
        *,
        start_url: str = "about:blank",
        headless: bool = True,
        width: int = 1280,
        height: int = 800,
        allowed_domains: list[str] | None = None,
        include_screenshot: bool = False,
        max_elements: int = 200,
        backend_impl: Any = None,
    ) -> None:
        self.start_url = start_url
        self.headless = headless
        self.width = width
        self.height = height
        self.allowed_domains = allowed_domains or []
        self.include_screenshot = include_screenshot
        self.max_elements = max_elements
        self._backend = backend_impl

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    async def _get_backend(self) -> Any:
        if self._backend is not None:
            return self._backend
        from nanobot.agent.tools.computer_use_backends.browser_playwright import BrowserBackend
        self._backend = BrowserBackend(
            width=self.width,
            height=self.height,
            headless=self.headless,
            start_url=self.start_url,
        )
        return self._backend

    def _domain_allowed(self, url: str) -> bool:
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
            if not self._domain_allowed(str(url)):
                raise ValueError(f"navigation to '{url}' is blocked by the allowed_domains policy")
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
        action = (action or "").strip()
        if action not in _ACTIONS:
            return f"Error: unknown action '{action}'. Valid actions: {', '.join(_ACTIONS)}"

        try:
            backend = await self._get_backend()
        except ImportError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error: could not initialize browser backend: {type(exc).__name__}: {exc}"

        try:
            status, direct = await self._dispatch(backend, action, kwargs)
        except ValueError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error executing browser '{action}': {type(exc).__name__}: {exc}"

        if direct is not None:
            return direct

        try:
            elements = await backend.dom_snapshot(self.max_elements)
            snapshot = _format_elements(elements)
        except Exception as exc:
            snapshot = f"(could not read page elements: {type(exc).__name__}: {exc})"
        try:
            current = await backend.current_url()
        except Exception:
            current = ""
        header = f"{status}\nCurrent page: {current}" if current else status
        text_out = f"{header}\n\n{snapshot}"

        if self.include_screenshot:
            try:
                png = await backend.screenshot()
                return build_image_content_blocks(png, "image/png", "", text_out)
            except Exception:
                return text_out
        return text_out

    async def close(self) -> None:
        if self._backend is not None:
            await self._backend.close()
