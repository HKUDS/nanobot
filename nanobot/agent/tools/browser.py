"""Browser control tools (Playwright). Optional: pip install nanobot-ai[browser], then run: playwright install (see https://playwright.dev/python/docs/library)."""

from typing import Any
from urllib.parse import urlparse

from nanobot.agent.tools.base import Tool

try:
    from playwright.async_api import async_playwright, Browser, Page
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    Browser = None  # type: ignore[misc, assignment]
    Page = None  # type: ignore[misc, assignment]


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


class BrowserSession:
    """Shared Playwright browser/page session. Lazy start, single page."""

    def __init__(self, headless: bool = True, timeout_ms: int = 30000) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def get_page(self) -> Page:
        """Return the current page, launching browser if needed."""
        if self._page is not None:
            return self._page
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed. Install with: pip install nanobot-ai[browser], then run: playwright install (see https://playwright.dev/python/docs/library)"
            )
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        context = await self._browser.new_context()
        self._page = await context.new_page()
        self._page.set_default_timeout(self._timeout_ms)
        return self._page

    async def close(self) -> None:
        """Close browser and playwright."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


class BrowserNavigateTool(Tool):
    """Navigate the browser to a URL."""

    name = "browser_navigate"
    description = "Navigate the browser to a URL. Use for JS-heavy or login-required pages; use web_fetch for simple read-only fetch."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to open (http or https only)"},
        },
        "required": ["url"],
    }

    def __init__(self, session: BrowserSession) -> None:
        self._browser_session = session

    async def execute(self, url: str, **kwargs: Any) -> str:
        ok, err = _validate_url(url)
        if not ok:
            return f"Error: {err}"
        try:
            page = await self._browser_session.get_page()
            await page.goto(url, wait_until="domcontentloaded")
            return f"Navigated to {url}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


class BrowserSnapshotTool(Tool):
    """Get a list of interactive elements on the current page with numeric refs for click/type."""

    name = "browser_snapshot"
    description = "Get interactive elements (buttons, links, inputs) on the current page. Returns ref numbers to use with browser_click and browser_type. Take a new snapshot after navigation."
    parameters = {
        "type": "object",
        "properties": {
            "max_elements": {"type": "integer", "description": "Max interactive elements to list (default 50)", "minimum": 1, "maximum": 200},
        },
        "required": [],
    }

    def __init__(self, session: BrowserSession) -> None:
        self._browser_session = session

    async def execute(self, max_elements: int = 50, **kwargs: Any) -> str:
        try:
            page = await self._browser_session.get_page()
            n = min(max(max_elements, 1), 200)
            result = await page.evaluate(
                """
                (maxEls) => {
                    const sel = 'button, a[href], input:not([type=hidden]), textarea, select, [role=button], [role=link], [role=textbox], [role=searchbox], [contenteditable="true"]';
                    const els = Array.from(document.querySelectorAll(sel)).slice(0, maxEls);
                    els.forEach((el, i) => { el.setAttribute('data-nanobot-ref', String(i + 1)); });
                    return els.map((el, i) => {
                        const ref = i + 1;
                        const role = el.getAttribute('role') || el.tagName.toLowerCase();
                        const name = el.getAttribute('aria-label') || el.getAttribute('placeholder') || (el.tagName === 'A' ? (el.textContent || '').trim().slice(0, 50) : '') || null;
                        const type = (el.getAttribute('type') || '').toLowerCase();
                        let label = role;
                        if (type && role === 'input') label = type + ' (input)';
                        if (name) label += " '" + name.replace(/'/g, "\\'").slice(0, 40) + "'";
                        return ref + '. ' + label;
                    }).join('\\n');
                }
                """,
                n,
            )
            return result or "No interactive elements found."
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


class BrowserClickTool(Tool):
    """Click an element by its ref from the last browser_snapshot."""

    name = "browser_click"
    description = "Click an element by ref number from browser_snapshot (e.g. ref 1 for the first listed element)."
    parameters = {
        "type": "object",
        "properties": {
            "ref": {"type": "integer", "description": "Element ref number from browser_snapshot", "minimum": 1},
        },
        "required": ["ref"],
    }

    def __init__(self, session: BrowserSession) -> None:
        self._browser_session = session

    async def execute(self, ref: int, **kwargs: Any) -> str:
        try:
            page = await self._browser_session.get_page()
            locator = page.locator(f'[data-nanobot-ref="{ref}"]').first
            await locator.click()
            return f"Clicked ref {ref}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


class BrowserTypeTool(Tool):
    """Type text into an element by ref. Optionally submit the form (press Enter)."""

    name = "browser_type"
    description = "Type text into an input/textarea by ref from browser_snapshot. Use browser_click to submit if needed, or set submit true to press Enter after typing."
    parameters = {
        "type": "object",
        "properties": {
            "ref": {"type": "integer", "description": "Element ref from browser_snapshot (input/textarea)", "minimum": 1},
            "text": {"type": "string", "description": "Text to type"},
            "submit": {"type": "boolean", "description": "Press Enter after typing (default false)", "default": False},
        },
        "required": ["ref", "text"],
    }

    def __init__(self, session: BrowserSession) -> None:
        self._browser_session = session

    async def execute(self, ref: int, text: str, submit: bool = False, **kwargs: Any) -> str:
        try:
            page = await self._browser_session.get_page()
            locator = page.locator(f'[data-nanobot-ref="{ref}"]').first
            await locator.fill("")
            await locator.press_sequentially(text)
            if submit:
                await locator.press("Enter")
            return f"Typed into ref {ref}" + (" and pressed Enter." if submit else ".")
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


class BrowserPressTool(Tool):
    """Press a key (e.g. Enter, Tab, Escape)."""

    name = "browser_press"
    description = "Press a key in the browser (e.g. Enter, Tab, Escape, ArrowDown)."
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key to press (Enter, Tab, Escape, ArrowDown, etc.)"},
        },
        "required": ["key"],
    }

    def __init__(self, session: BrowserSession) -> None:
        self._browser_session = session

    async def execute(self, key: str, **kwargs: Any) -> str:
        try:
            page = await self._browser_session.get_page()
            await page.keyboard.press(key.strip() or "Enter")
            return f"Pressed {key!r}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


def create_browser_tools(config: Any) -> list[Tool]:
    """Create browser tools sharing one session. Returns [] if Playwright is not installed. config: BrowserToolConfig with headless, timeout_ms."""
    if not _PLAYWRIGHT_AVAILABLE:
        return []
    headless = getattr(config, "headless", True)
    timeout_ms = getattr(config, "timeout_ms", 30000)
    session = BrowserSession(headless=headless, timeout_ms=timeout_ms)
    return [
        BrowserNavigateTool(session),
        BrowserSnapshotTool(session),
        BrowserClickTool(session),
        BrowserTypeTool(session),
        BrowserPressTool(session),
    ]


def is_browser_available() -> bool:
    """Return True if Playwright is installed and browser tools can be used."""
    return _PLAYWRIGHT_AVAILABLE
