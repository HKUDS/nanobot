"""Browser control tools (Playwright). Optional: pip install nanobot-ai[browser], then run: playwright install (see https://playwright.dev/python/docs/library)."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from nanobot.agent.tools.base import Tool

# Match web_fetch so sites that allow httpx also allow the browser
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Client Hints matching Chrome 120; some sites check these before sending body (may help with ERR_EMPTY_RESPONSE)
BROWSER_SEC_CH_UA = '"Not A(Brand";v="24", "Chromium";v="120", "Google Chrome";v="120"'
BROWSER_ACCEPT_LANGUAGE = "en-US,en;q=0.9"

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    Browser = None  # type: ignore[misc, assignment]
    BrowserContext = None  # type: ignore[misc, assignment]
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


# Launch args to reduce automation detection (e.g. navigator.webdriver); may help with ERR_EMPTY_RESPONSE on some sites
_BROWSER_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def _resolve_proxy(proxy_server: str) -> str:
    """Resolve proxy URL: config value if non-empty, else HTTPS_PROXY or HTTP_PROXY from env."""
    s = (proxy_server or "").strip()
    if s:
        return s
    return os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""


def _resolve_storage_state_path(config: Any, workspace_path: Path | None) -> str:
    """Resolve storage state file path: config.storage_state_path if set, else workspace/browser/cookie.json."""
    explicit = (getattr(config, "storage_state_path", None) or "").strip()
    if explicit:
        return str(Path(explicit).expanduser())
    if workspace_path is None:
        return ""
    return str((workspace_path / "browser" / "cookie.json").resolve())


class BrowserSession:
    """Shared Playwright browser/page session. Lazy start, single page."""

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30000,
        proxy_server: str = "",
        storage_state_path: str = "",
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._proxy_server = proxy_server or ""
        self._storage_state_path = (storage_state_path or "").strip()
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
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
        launch_options: dict[str, Any] = {
            "headless": self._headless,
            "args": _BROWSER_LAUNCH_ARGS,
        }
        proxy_url = _resolve_proxy(self._proxy_server)
        if proxy_url:
            logger.info(
                "Browser session starting (headless={}, timeout_ms={}, proxy={})",
                self._headless,
                self._timeout_ms,
                proxy_url,
            )
        else:
            logger.info(
                "Browser session starting (headless={}, timeout_ms={})",
                self._headless,
                self._timeout_ms,
            )
        self._browser = await self._playwright.chromium.launch(**launch_options)
        context_options: dict[str, Any] = {
            "user_agent": BROWSER_USER_AGENT,
            "viewport": {"width": 1280, "height": 720},
            "ignore_https_errors": False,
            "extra_http_headers": {
                "Sec-CH-UA": BROWSER_SEC_CH_UA,
                "Accept-Language": BROWSER_ACCEPT_LANGUAGE,
            },
        }
        if proxy_url:
            context_options["proxy"] = {"server": proxy_url}
        if self._storage_state_path:
            path = Path(self._storage_state_path)
            if path.exists():
                context_options["storage_state"] = self._storage_state_path
                logger.debug("Browser loading storage state from {}", self._storage_state_path)
        try:
            context = await self._browser.new_context(**context_options)
        except Exception as e:
            if context_options.pop("storage_state", None):
                logger.warning("Browser storage state load failed, starting clean: {}", e)
                context = await self._browser.new_context(**context_options)
            else:
                raise
        self._context = context
        self._page = await context.new_page()
        self._page.set_default_timeout(self._timeout_ms)
        return self._page

    async def _write_storage_state(self) -> None:
        """Write storage state to path. Uses context.cookies() as source of truth for cookies (Playwright storage_state() can write empty cookies in headless)."""
        path = Path(self._storage_state_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        abs_path = str(path)
        if self._page:
            try:
                await self._page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
        await self._context.storage_state(path=abs_path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        context_cookies = await self._context.cookies()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["cookies"] = context_cookies
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        logger.info(
            "Browser storage state: context.cookies()={}, wrote {} to {}",
            len(context_cookies),
            len(context_cookies),
            path,
        )

    async def save_storage_state(self) -> tuple[bool, str]:
        """Save current context storage state to configured path. Returns (success, message)."""
        if not self._storage_state_path:
            return False, "No storage state path configured"
        if self._context is None:
            return False, "Browser not started yet. Use a browser action (e.g. browser_navigate) first, then save session."
        try:
            await self._write_storage_state()
            logger.debug("Browser storage state saved to {}", self._storage_state_path)
            return True, f"Saved to {self._storage_state_path}"
        except Exception as e:
            logger.error("Browser storage state save failed: {}", e)
            return False, f"Save failed: {type(e).__name__}: {e}"

    async def close(self) -> None:
        """Close browser and playwright; save storage state first if configured."""
        if self._browser and self._context and self._storage_state_path:
            try:
                await self._write_storage_state()
                logger.debug("Browser storage state saved on close")
            except Exception as e:
                logger.warning(
                    "Browser storage state save on close failed: {} (browser may already be closed by shutdown). "
                    "Session is auto-saved after each browser_navigate; cookie.json may already be up to date.",
                    e,
                )
        elif self._storage_state_path and not (self._browser and self._context):
            logger.debug(
                "Browser storage state not saved on close (browser was never started). "
                "Use browser_navigate (or another browser tool) at least once, then exit or call browser_save_session."
            )
        if self._browser:
            logger.debug("Browser session closing")
            await self._browser.close()
            self._browser = None
        self._context = None
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
            logger.warning("browser_navigate invalid url: {}", err)
            return f"Error: {err}"
        try:
            page = await self._browser_session.get_page()
            await page.goto(url, wait_until="load")
            logger.info("browser_navigate: {} -> OK", url)
            session = self._browser_session
            async def _auto_save_after_navigate() -> None:
                try:
                    await session.save_storage_state()
                except Exception as e:
                    logger.debug("Auto-save after navigate skipped: {}", e)
            if session._storage_state_path:
                asyncio.create_task(_auto_save_after_navigate())
            return f"Navigated to {url}"
        except Exception as e:
            logger.error("browser_navigate: {} -> {}: {}", url, type(e).__name__, e)
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
            count = len((result or "").strip().split("\n")) if result else 0
            logger.debug("browser_snapshot: {} elements", count)
            return result or "No interactive elements found."
        except Exception as e:
            logger.error("browser_snapshot: {}: {}", type(e).__name__, e)
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
            logger.info("browser_click: ref={} -> OK", ref)
            return f"Clicked ref {ref}"
        except Exception as e:
            logger.error("browser_click: ref={} -> {}: {}", ref, type(e).__name__, e)
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
            logger.debug("browser_type: ref={}, submit={}", ref, submit)
            return f"Typed into ref {ref}" + (" and pressed Enter." if submit else ".")
        except Exception as e:
            logger.error("browser_type: ref={} -> {}: {}", ref, type(e).__name__, e)
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
            k = key.strip() or "Enter"
            await page.keyboard.press(k)
            logger.debug("browser_press: key={!r}", k)
            return f"Pressed {k!r}"
        except Exception as e:
            logger.error("browser_press: key={!r} -> {}: {}", key, type(e).__name__, e)
            return f"Error: {type(e).__name__}: {e}"


class BrowserSaveSessionTool(Tool):
    """Save current browser cookies and storage to the configured path (e.g. after login)."""

    name = "browser_save_session"
    description = "Save the current browser session (cookies, localStorage) to disk so it can be restored after restart. Use after logging in or when the page is in a good state."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, session: BrowserSession) -> None:
        self._browser_session = session

    async def execute(self, **kwargs: Any) -> str:
        ok, msg = await self._browser_session.save_storage_state()
        if ok:
            return msg
        return f"Error: {msg}"


def create_browser_tools(
    config: Any, workspace_path: Path | None = None
) -> tuple[list[Tool], BrowserSession | None]:
    """Create browser tools sharing one session. Returns (tools, session); ([], None) if Playwright not installed. config: BrowserToolConfig; workspace_path used for default storage_state_path."""
    if not _PLAYWRIGHT_AVAILABLE:
        logger.debug("Browser tools skipped: Playwright not installed")
        return ([], None)
    headless = getattr(config, "headless", True)
    timeout_ms = getattr(config, "timeout_ms", 30000)
    proxy_server = getattr(config, "proxy_server", "") or ""
    storage_state_path = _resolve_storage_state_path(config, workspace_path)
    if storage_state_path:
        try:
            Path(storage_state_path).parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Browser storage directory: {} (cookie.json will be written on save or exit)",
                Path(storage_state_path).parent,
            )
        except OSError as e:
            logger.warning("Could not create browser storage directory {}: {}", Path(storage_state_path).parent, e)
    logger.info(
        "Browser tools created (headless={}, timeout_ms={}, proxy_server={}, storage_state_path={})",
        headless,
        timeout_ms,
        proxy_server or "(none/env)",
        storage_state_path or "(none)",
    )
    session = BrowserSession(
        headless=headless,
        timeout_ms=timeout_ms,
        proxy_server=proxy_server,
        storage_state_path=storage_state_path,
    )
    tools = [
        BrowserNavigateTool(session),
        BrowserSnapshotTool(session),
        BrowserClickTool(session),
        BrowserTypeTool(session),
        BrowserPressTool(session),
        BrowserSaveSessionTool(session),
    ]
    return (tools, session)


def is_browser_available() -> bool:
    """Return True if Playwright is installed and browser tools can be used."""
    return _PLAYWRIGHT_AVAILABLE
