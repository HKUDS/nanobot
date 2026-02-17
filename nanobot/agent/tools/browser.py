"""Browser control tools (Playwright).

Optional extra: pip install nanobot-ai[browser] && playwright install chromium

Two modes:
- Local: launches headless Chromium (default).
- Remote CDP: attaches to an existing browser via cdp_url (e.g. Windows Edge on WSL2).
  When auto_start=True (default), the browser is launched on-demand if CDP is unreachable.
"""

import asyncio
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from loguru import logger

from nanobot.agent.tools.base import Tool

# Windows browser executables to try (WSL2 /mnt/c paths), in priority order
_BROWSER_PATHS = [
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files/Vivaldi/Application/vivaldi.exe",
    "/mnt/c/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe",
]
_POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"

# Chromium launch flags (suppress automation detection banner)
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

# WSL2 with homebrew: Chromium needs libasound.so.2 from linuxbrew if not in LD_LIBRARY_PATH
_LINUXBREW_LIB = "/home/linuxbrew/.linuxbrew/lib"


def _ensure_chromium_libs() -> None:
    """Add linuxbrew lib path to LD_LIBRARY_PATH if Chromium would otherwise fail in WSL2."""
    if not Path(_LINUXBREW_LIB).is_dir():
        return
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if _LINUXBREW_LIB not in current:
        os.environ["LD_LIBRARY_PATH"] = f"{_LINUXBREW_LIB}:{current}" if current else _LINUXBREW_LIB

# Truncate browser_content output to keep token usage reasonable
_CONTENT_MAX_CHARS = 6000

# Mimic a regular browser to avoid bot-detection on common sites
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_EXTRA_HEADERS = {
    "Sec-CH-UA": '"Not A(Brand";v="24", "Chromium";v="120", "Google Chrome";v="120"',
    "Accept-Language": "en-US,en;q=0.9",
}

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    Browser = None  # type: ignore[misc, assignment]
    BrowserContext = None  # type: ignore[misc, assignment]
    Page = None  # type: ignore[misc, assignment]


def _validate_url(url: str) -> tuple[bool, str]:
    """Return (True, '') if url is a valid http/https URL, else (False, reason)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
    return (True, "") if p.netloc else (False, "Missing domain")


def _find_browser_exe() -> str | None:
    """Return the first available Windows browser executable, or None."""
    return next((p for p in _BROWSER_PATHS if Path(p).exists()), None)


def _get_win_username() -> str:
    """Return the Windows username via PowerShell, falling back to $USER env var."""
    if not Path(_POWERSHELL).exists():
        return os.environ.get("USER", "user")
    try:
        result = subprocess.run(
            [_POWERSHELL, "-NoProfile", "-Command", "$env:USERNAME"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or os.environ.get("USER", "user")
    except (OSError, subprocess.TimeoutExpired):
        return os.environ.get("USER", "user")


def _resolve_proxy(proxy_server: str) -> str:
    """Return the effective proxy URL: explicit config, then HTTPS_PROXY/HTTP_PROXY env."""
    return proxy_server.strip() or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""


def _storage_state_path(config: Any, workspace: Path | None) -> str:
    """Return the resolved storage state file path for local mode."""
    explicit = (getattr(config, "storage_state_path", None) or "").strip()
    if explicit:
        return str(Path(explicit).expanduser())
    if workspace is None:
        return ""
    return str(workspace / "browser" / "cookie.json")


class BrowserSession:
    """Shared Playwright browser/page session for browser tools.

    Two modes:
    - cdp_url unset: launches headless Chromium locally; cookies saved to storage_state_path.
    - cdp_url set: attaches to an existing browser via CDP (e.g. Windows Edge on WSL2).
      In remote mode, storage_state and proxy settings are ignored.
      When auto_start=True (default), the browser is launched on-demand if CDP is unreachable.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30000,
        proxy_server: str = "",
        storage_state_path: str = "",
        cdp_url: str = "",
        auto_start: bool = True,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._proxy_server = proxy_server.strip()
        self._storage_state_path = storage_state_path.strip()
        self._cdp_url = cdp_url.strip()
        self._auto_start = auto_start
        self._remote = bool(self._cdp_url)
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _is_cdp_reachable(self) -> bool:
        """Check if the CDP endpoint responds (synchronous; run via executor to avoid blocking)."""
        try:
            urlopen(self._cdp_url.rstrip("/") + "/json/version", timeout=2)
            return True
        except Exception:
            return False

    async def _cdp_reachable_async(self) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._is_cdp_reachable)

    async def _ensure_browser_running(self) -> None:
        """Launch Windows browser on-demand when CDP is not yet reachable."""
        if await self._cdp_reachable_async():
            return

        exe = _find_browser_exe()
        if not exe:
            raise RuntimeError(
                f"CDP not reachable at {self._cdp_url} and no Windows browser found. "
                "Install Edge or Chrome, or start it manually with --remote-debugging-port=9223."
            )

        try:
            port = int(self._cdp_url.split(":")[-1].split("/")[0])
        except (ValueError, IndexError):
            port = 9223
        profile_dir = f"C:\\Users\\{_get_win_username()}\\AppData\\Local\\Nanobot\\edge-profile"
        launch_args = [
            exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
            "--no-first-run", "--remote-allow-origins=*",
        ]
        if self._headless:
            launch_args += ["--headless", "--hide-scrollbars", "--mute-audio"]
        logger.info("Browser: starting {} on port {} (headless={})...", Path(exe).stem, port, self._headless)

        def _spawn() -> None:
            try:
                subprocess.Popen(launch_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            except Exception as e:
                logger.error("Browser: failed to spawn {}: {}", Path(exe).stem, e)

        threading.Thread(target=_spawn, daemon=True).start()

        # Poll until CDP responds. First-run profile init can take 30+ seconds on Windows.
        for attempt in range(90):
            await asyncio.sleep(1.0)
            if await self._cdp_reachable_async():
                logger.info("Browser: CDP ready at {} ({}s)", self._cdp_url, attempt + 1)
                return
            if (attempt + 1) % 10 == 0:
                logger.info("Browser: waiting for CDP ({}/90s)...", attempt + 1)

        raise RuntimeError(
            f"Timeout (90s) waiting for browser CDP at {self._cdp_url}. "
            "Check that Edge/Chrome started successfully on Windows."
        )

    async def get_page(self) -> Page:
        """Return the current page, starting or attaching to the browser if needed."""
        if self._page is not None:
            return self._page
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install nanobot-ai[browser] && playwright install"
            )
        if not self._remote:
            # Must be set before async_playwright().start() so the Node.js driver inherits it
            _ensure_chromium_libs()
        self._playwright = await async_playwright().start()

        if self._remote:
            if self._auto_start:
                await self._ensure_browser_running()
            logger.info("Browser: attaching to CDP at {}", self._cdp_url)
            self._browser = await self._playwright.chromium.connect_over_cdp(self._cdp_url)
            self._context = (
                self._browser.contexts[0] if self._browser.contexts
                else await self._browser.new_context()
            )
            # Always open a fresh page — existing pages may be mid-navigation on cold start
            self._page = await self._context.new_page()
        else:
            proxy = _resolve_proxy(self._proxy_server)
            logger.info("Browser: launching (headless={}, proxy={})", self._headless, proxy or "none")
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=self._headless, args=_LAUNCH_ARGS,
                )
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    raise RuntimeError(
                        "Chromium browser not found. Run: playwright install chromium"
                    ) from e
                raise
            ctx_opts: dict[str, Any] = {
                "user_agent": _USER_AGENT,
                "viewport": {"width": 1280, "height": 720},
                "extra_http_headers": _EXTRA_HEADERS,
            }
            if proxy:
                ctx_opts["proxy"] = {"server": proxy}
            if self._storage_state_path and Path(self._storage_state_path).exists():
                ctx_opts["storage_state"] = self._storage_state_path
                logger.debug("Browser: loading storage state from {}", self._storage_state_path)
            try:
                self._context = await self._browser.new_context(**ctx_opts)
            except Exception as e:
                if ctx_opts.pop("storage_state", None):
                    logger.warning("Browser: storage state load failed, starting clean: {}", e)
                    self._context = await self._browser.new_context(**ctx_opts)
                else:
                    raise
            self._page = await self._context.new_page()

        self._page.set_default_timeout(self._timeout_ms)
        return self._page

    async def reconfigure(self, cdp_url: str | None = None, headless: bool | None = None) -> None:
        """Close the current session and update settings for the next get_page() call.

        Used by browser_navigate when the agent requests a different browser or headless mode.
        """
        if self._page is not None:
            await self.close()
        if cdp_url is not None:
            self._cdp_url = cdp_url.strip()
            self._remote = bool(self._cdp_url)
        if headless is not None:
            self._headless = headless

    async def save_storage_state(self) -> tuple[bool, str]:
        """Save cookies and storage to disk (local mode only)."""
        if self._remote:
            return False, "Storage state is not supported in remote CDP mode."
        if not self._storage_state_path:
            return False, "No storage state path configured."
        if self._context is None:
            return False, "Browser not started yet."
        try:
            path = Path(self._storage_state_path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(path))
            path.chmod(0o600)
            logger.info("Browser: storage state saved to {}", path)
            return True, f"Saved to {path}"
        except Exception as e:
            return False, f"Save failed: {e}"

    async def close(self) -> None:
        """Disconnect from remote CDP or close local Chromium (saving storage state first)."""
        if not self._remote and self._context:
            ok, msg = await self.save_storage_state()
            if not ok and msg.startswith("Save failed"):
                logger.warning("Browser: save on close: {}", msg)

        if self._browser:
            await self._browser.close()
            self._browser = None
        self._context = None
        self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# ── Tools ────────────────────────────────────────────────────────────────────


class BrowserNavigateTool(Tool):
    """Navigate the browser to a URL.

    Optionally override the browser engine and headless mode per-call without changing config.
    The override persists for all subsequent browser calls within the same session.
    """

    def __init__(self, session: BrowserSession, default_cdp_url: str = "") -> None:
        self._session = session
        self._default_cdp_url = default_cdp_url

    @property
    def name(self) -> str:
        return "browser_navigate"

    @property
    def description(self) -> str:
        return (
            "Navigate the browser to a URL. Prefer web_fetch for simple read-only pages. "
            "Use browser='chromium' for anonymous browsing or browser='edge' to use the "
            "Windows Edge profile (with saved logins). Set headless=false to watch the browser. "
            "After navigating, call browser_snapshot or browser_content to read the page."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to open (http or https only)",
                },
                "browser": {
                    "type": "string",
                    "enum": ["default", "chromium", "edge"],
                    "description": (
                        "Browser to use: default (keep current config), "
                        "chromium (local WSL2 Chromium, anonymous), "
                        "edge (Windows Edge via CDP, uses saved logins/cookies)"
                    ),
                },
                "headless": {
                    "type": "boolean",
                    "description": (
                        "Run without visible UI (true) or show the browser window (false). "
                        "Overrides config. Use false to watch the agent browse live."
                    ),
                },
            },
            "required": ["url"],
        }

    async def execute(self, url: str, browser: str = "default", headless: bool | None = None, **kwargs: Any) -> str:
        ok, err = _validate_url(url)
        if not ok:
            return f"Error: {err}"

        # Reconfigure session if the agent is requesting a different browser or headless mode
        if browser != "default" or headless is not None:
            new_cdp = {"chromium": "", "edge": self._default_cdp_url or "http://localhost:9223"}.get(browser)
            await self._session.reconfigure(cdp_url=new_cdp, headless=headless)

        try:
            page = await self._session.get_page()
            await page.goto(url, wait_until="load")
            logger.info("browser_navigate: {}", url)
            if not self._session._remote and self._session._storage_state_path:
                asyncio.create_task(self._session.save_storage_state())
            return f"Navigated to {url}"
        except Exception as e:
            logger.error("browser_navigate {}: {}: {}", url, type(e).__name__, e)
            return f"Error: {type(e).__name__}: {e}"


class BrowserSnapshotTool(Tool):
    """List interactive elements on the current page with numbered refs."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    @property
    def name(self) -> str:
        return "browser_snapshot"

    @property
    def description(self) -> str:
        return (
            "List interactive elements (buttons, links, inputs) on the current page with "
            "numbered refs. Use refs with browser_click and browser_type."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_elements": {
                    "type": "integer",
                    "description": "Max elements to list (default 50, max 200)",
                    "minimum": 1,
                    "maximum": 200,
                },
            },
            "required": [],
        }

    async def execute(self, max_elements: int = 50, **kwargs: Any) -> str:
        try:
            page = await self._session.get_page()
            result = await page.evaluate(
                """(maxEls) => {
                    const sel = 'button, a[href], input:not([type=hidden]), textarea, select, '
                        + '[role=button], [role=link], [role=textbox], [role=searchbox], [contenteditable="true"]';
                    const els = Array.from(document.querySelectorAll(sel)).slice(0, maxEls);
                    els.forEach((el, i) => el.setAttribute('data-nanobot-ref', String(i + 1)));
                    return els.map((el, i) => {
                        const ref = i + 1;
                        const role = el.getAttribute('role') || el.tagName.toLowerCase();
                        const name = el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                            (el.tagName === 'A' ? (el.textContent || '').trim().slice(0, 50) : '') || null;
                        const type = (el.getAttribute('type') || '').toLowerCase();
                        let label = (type && role === 'input') ? type + ' (input)' : role;
                        if (name) label += " '" + name.replace(/'/g, "\\'").slice(0, 40) + "'";
                        return ref + '. ' + label;
                    }).join('\\n');
                }""",
                min(max(max_elements, 1), 200),
            )
            return result or "No interactive elements found."
        except Exception as e:
            logger.error("browser_snapshot: {}: {}", type(e).__name__, e)
            return f"Error: {type(e).__name__}: {e}"


class BrowserContentTool(Tool):
    """Read the visible text content of the current page."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    @property
    def name(self) -> str:
        return "browser_content"

    @property
    def description(self) -> str:
        return (
            "Read the visible text content of the current page (headings, paragraphs, tables, "
            "error messages). Use after browser_navigate or browser_click to understand the page."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector to scope content (default: body). E.g. 'main', '#content'",
                },
            },
            "required": [],
        }

    async def execute(self, selector: str = "body", **kwargs: Any) -> str:
        try:
            page = await self._session.get_page()
            sel = selector.strip() or "body"
            text = re.sub(r"\n{3,}", "\n\n", (await page.inner_text(sel)).strip())
            if len(text) > _CONTENT_MAX_CHARS:
                text = text[:_CONTENT_MAX_CHARS] + f"\n\n[...truncated — {len(text)} chars total]"
            return text or "(no text content)"
        except Exception as e:
            logger.error("browser_content: {}: {}", type(e).__name__, e)
            return f"Error: {type(e).__name__}: {e}"


class BrowserClickTool(Tool):
    """Click an element by ref from the last browser_snapshot."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    @property
    def name(self) -> str:
        return "browser_click"

    @property
    def description(self) -> str:
        return "Click an element by ref number from browser_snapshot."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ref": {"type": "integer", "description": "Ref number from browser_snapshot", "minimum": 1},
            },
            "required": ["ref"],
        }

    async def execute(self, ref: int, **kwargs: Any) -> str:
        try:
            page = await self._session.get_page()
            await page.locator(f'[data-nanobot-ref="{ref}"]').first.click()
            return f"Clicked ref {ref}"
        except Exception as e:
            logger.error("browser_click ref={}: {}: {}", ref, type(e).__name__, e)
            return f"Error: {type(e).__name__}: {e}"


class BrowserTypeTool(Tool):
    """Type text into an input by ref. Optionally submit with Enter."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    @property
    def name(self) -> str:
        return "browser_type"

    @property
    def description(self) -> str:
        return (
            "Type text into an input/textarea by ref from browser_snapshot. "
            "Set submit=true to press Enter after typing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ref": {"type": "integer", "description": "Ref number from browser_snapshot", "minimum": 1},
                "text": {"type": "string", "description": "Text to type"},
                "submit": {"type": "boolean", "description": "Press Enter after typing (default false)"},
            },
            "required": ["ref", "text"],
        }

    async def execute(self, ref: int, text: str, submit: bool = False, **kwargs: Any) -> str:
        try:
            page = await self._session.get_page()
            el = page.locator(f'[data-nanobot-ref="{ref}"]').first
            await el.fill("")
            await el.press_sequentially(text)
            if submit:
                await el.press("Enter")
            return f"Typed into ref {ref}" + (" and pressed Enter." if submit else ".")
        except Exception as e:
            logger.error("browser_type ref={}: {}: {}", ref, type(e).__name__, e)
            return f"Error: {type(e).__name__}: {e}"


class BrowserPressTool(Tool):
    """Press a keyboard key (Enter, Tab, Escape, ArrowDown, etc.)."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    @property
    def name(self) -> str:
        return "browser_press"

    @property
    def description(self) -> str:
        return "Press a key in the browser (Enter, Tab, Escape, ArrowDown, etc.)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name (Enter, Tab, Escape, ArrowDown, etc.)"},
            },
            "required": ["key"],
        }

    async def execute(self, key: str, **kwargs: Any) -> str:
        try:
            page = await self._session.get_page()
            k = key.strip() or "Enter"
            await page.keyboard.press(k)
            return f"Pressed {k!r}"
        except Exception as e:
            logger.error("browser_press key={!r}: {}: {}", key, type(e).__name__, e)
            return f"Error: {type(e).__name__}: {e}"


class BrowserSaveSessionTool(Tool):
    """Save browser session cookies to disk (local mode only)."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    @property
    def name(self) -> str:
        return "browser_save_session"

    @property
    def description(self) -> str:
        return (
            "Save the current browser session (cookies, storage) to disk so it persists across restarts. "
            "Call after logging in. Not needed in remote CDP mode."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        ok, msg = await self._session.save_storage_state()
        return msg if ok else f"Error: {msg}"


def create_browser_tools(
    config: Any, workspace: Path | None = None
) -> tuple[list[Tool], "BrowserSession | None"]:
    """Create browser tools that share one BrowserSession.

    Returns (tools, session). Returns ([], None) if Playwright is not installed.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        logger.debug("Browser tools skipped: Playwright not installed")
        return [], None

    cdp_url = (getattr(config, "cdp_url", "") or "").strip()
    storage_path = "" if cdp_url else _storage_state_path(config, workspace)

    if cdp_url:
        logger.info("Browser: remote CDP mode ({}, auto_start={})", cdp_url, getattr(config, "auto_start", True))
    else:
        logger.info("Browser: local mode (headless={}, storage={})",
                    getattr(config, "headless", True), storage_path or "none")
        if storage_path:
            Path(storage_path).parent.mkdir(parents=True, exist_ok=True)

    session = BrowserSession(
        headless=getattr(config, "headless", True),
        timeout_ms=getattr(config, "timeout_ms", 30000),
        proxy_server=getattr(config, "proxy_server", "") or "",
        storage_state_path=storage_path,
        cdp_url=cdp_url,
        auto_start=getattr(config, "auto_start", True),
    )
    tools: list[Tool] = [
        BrowserNavigateTool(session, default_cdp_url=cdp_url),
        BrowserSnapshotTool(session),
        BrowserContentTool(session),
        BrowserClickTool(session),
        BrowserTypeTool(session),
        BrowserPressTool(session),
        BrowserSaveSessionTool(session),
    ]
    return tools, session


def is_browser_available() -> bool:
    """Return True if Playwright is installed."""
    return _PLAYWRIGHT_AVAILABLE
