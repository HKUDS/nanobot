"""Playwright backend shared by browser and computer_use."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import urlparse, urlunparse

from loguru import logger

from nanobot.agent.tools.computer_use_backends.base import ComputerBackend
from nanobot.security.network import validate_url_target

_MISSING = (
    "Browser computer-use backend needs 'playwright'. Install with: "
    "pip install 'nanobot-ai[computer-use]' && playwright install chromium"
)

_SCROLL_PIXELS = 100  # one "scroll click" ~= this many pixels

# Tags visible interactive elements with data-nanobot-ref and returns a compact
# list. Refs are reassigned per call. Used by DOM/accessibility mode.
_SNAPSHOT_JS = r"""
(max) => {
  const SEL = 'a,button,input,textarea,select,[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=switch],[onclick],[contenteditable=""],[contenteditable=true]';
  const out = [];
  let ref = 0;
  for (const el of document.querySelectorAll(SEL)) {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (r.width <= 0 || r.height <= 0) continue;
    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') continue;
    ref++;
    el.setAttribute('data-nanobot-ref', String(ref));
    let name = (el.getAttribute('aria-label') || el.innerText || el.value ||
                el.getAttribute('placeholder') || el.getAttribute('name') ||
                el.getAttribute('title') || '');
    name = name.replace(/\s+/g, ' ').trim().slice(0, 120);
    out.push({
      ref: ref,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      type: el.getAttribute('type') || '',
      name: name,
      href: el.getAttribute('href') || ''
    });
    if (out.length >= max) break;
  }
  return out;
}
"""

# CUA/xdotool-ish modifier names -> Playwright modifiers.
_MODIFIERS = {
    "ctrl": "Control", "control": "Control",
    "alt": "Alt", "option": "Alt",
    "shift": "Shift",
    "cmd": "Meta", "meta": "Meta", "super": "Meta", "win": "Meta",
}
# Common single-key names -> Playwright key names.
_KEYS = {
    "return": "Enter", "enter": "Enter", "tab": "Tab", "esc": "Escape",
    "escape": "Escape", "backspace": "Backspace", "delete": "Delete",
    "space": "Space", "up": "ArrowUp", "down": "ArrowDown",
    "left": "ArrowLeft", "right": "ArrowRight",
    "page_down": "PageDown", "pagedown": "PageDown",
    "page_up": "PageUp", "pageup": "PageUp", "home": "Home", "end": "End",
}


def _validate_browser_url(
    url: str,
    allowed_domains: Sequence[str] = (),
    *,
    navigation: bool = True,
) -> tuple[bool, str]:
    if url == "about:blank":
        return True, ""

    parsed = urlparse(url)
    if not navigation and parsed.scheme in {"blob", "data"}:
        return True, ""

    target = url
    if parsed.scheme in {"ws", "wss"}:
        target = urlunparse(parsed._replace(scheme="https" if parsed.scheme == "wss" else "http"))

    if navigation and allowed_domains:
        host = (parsed.hostname or "").rstrip(".").lower()
        allowed = any(
            normalized and (host == normalized or host.endswith(f".{normalized}"))
            for domain in allowed_domains
            if (normalized := domain.strip().lstrip(".").rstrip(".").lower())
        )
        if not allowed:
            return False, f"host {host or '<missing>'} is not in allowed_domains"

    return validate_url_target(target)


def _playwright_key(combo: str) -> str:
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    out: list[str] = []
    for part in parts:
        low = part.lower()
        if low in _MODIFIERS:
            out.append(_MODIFIERS[low])
        elif low in _KEYS:
            out.append(_KEYS[low])
        elif len(part) == 1:
            out.append(part)
        else:
            out.append(part.capitalize())
    return "+".join(out)


class BrowserRuntime:
    """One lazily started browser process shared by isolated session contexts."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None

    async def get(self) -> Any:
        if self._browser is not None:
            return self._browser
        async with self._lock:
            if self._browser is not None:
                return self._browser
            try:
                playwright = importlib.import_module("playwright.async_api")
                async_playwright = cast(Any, playwright).async_playwright
            except ImportError as exc:
                raise ImportError(_MISSING) from exc
            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=self._headless
                )
            except BaseException:
                await self.close()
                raise
        return self._browser

    async def close(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = self._playwright = None
        errors: list[BaseException] = []
        closers = (
            browser.close if browser is not None else None,
            playwright.stop if playwright is not None else None,
        )
        for close in closers:
            if close is None:
                continue
            try:
                await close()
            except BaseException as exc:
                errors.append(exc)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("failed to close browser runtime", errors)


class BrowserBackend(ComputerBackend):
    environment = "browser"

    def __init__(
        self,
        *,
        width: int = 1280,
        height: int = 800,
        headless: bool = True,
        start_url: str = "about:blank",
        allowed_domains: Sequence[str] = (),
        runtime: BrowserRuntime | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._start_url = start_url
        self._allowed_domains = tuple(allowed_domains)
        self._runtime = runtime or BrowserRuntime(headless=headless)
        self._owns_runtime = runtime is None
        self._context: Any = None
        self._page: Any = None
        self._last_pos = (0, 0)
        self._blocked_navigation: str | None = None

    async def _require_url(self, url: str, label: str) -> None:
        ok, error = await asyncio.to_thread(
            _validate_browser_url,
            url,
            self._allowed_domains,
        )
        if not ok:
            raise ValueError(f"{label} is blocked: {error}")

    async def _route_request(self, route: Any) -> None:
        request = route.request
        navigation = bool(request.is_navigation_request())
        ok, error = await asyncio.to_thread(
            _validate_browser_url,
            request.url,
            self._allowed_domains,
            navigation=navigation,
        )
        if ok:
            await route.continue_()
            return
        if navigation:
            self._blocked_navigation = error
        logger.warning("Blocked browser request to {}: {}", request.url, error)
        await route.abort("blockedbyclient")

    async def _route_web_socket(self, web_socket: Any) -> None:
        ok, error = await asyncio.to_thread(
            _validate_browser_url,
            web_socket.url,
            self._allowed_domains,
            navigation=False,
        )
        if not ok:
            logger.warning("Blocked browser WebSocket to {}: {}", web_socket.url, error)
            await web_socket.close(code=1008, reason="Blocked by nanobot network policy")
            return
        await web_socket.connect_to_server()

    def pop_blocked_navigation(self) -> str | None:
        error = self._blocked_navigation
        self._blocked_navigation = None
        return error

    async def _ensure(self) -> Any:
        if self._page is not None:
            return self._page
        await self._require_url(self._start_url, "start_url")
        try:
            browser = await self._runtime.get()
            self._context = await browser.new_context(
                viewport={"width": self._width, "height": self._height},
                device_scale_factor=1,
                service_workers="block",
            )
            await self._context.route("**/*", self._route_request)
            await self._context.route_web_socket("**/*", self._route_web_socket)
            self._page = await self._context.new_page()
            if self._start_url != "about:blank":
                await self._page.goto(self._start_url)
            return self._page
        except BaseException:
            await self.close()
            raise

    async def dimensions(self) -> tuple[int, int]:
        await self._ensure()
        vp = self._page.viewport_size or {"width": self._width, "height": self._height}
        return vp["width"], vp["height"]

    async def screenshot(self) -> bytes:
        page = await self._ensure()
        return await page.screenshot()

    async def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        page = await self._ensure()
        await page.mouse.click(x, y, button=button, click_count=count)
        self._last_pos = (x, y)

    async def move(self, x: int, y: int) -> None:
        page = await self._ensure()
        await page.mouse.move(x, y)
        self._last_pos = (x, y)

    async def drag(self, x: int, y: int) -> None:
        page = await self._ensure()
        sx, sy = self._last_pos
        await page.mouse.move(sx, sy)
        await page.mouse.down()
        await page.mouse.move(x, y)
        await page.mouse.up()
        self._last_pos = (x, y)

    async def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        page = await self._ensure()
        await page.mouse.move(x, y)
        pixels = max(1, amount) * _SCROLL_PIXELS
        dx = pixels if direction == "right" else -pixels if direction == "left" else 0
        dy = pixels if direction == "down" else -pixels if direction == "up" else 0
        await page.mouse.wheel(dx, dy)

    async def type_text(self, text: str) -> None:
        page = await self._ensure()
        await page.keyboard.type(text)

    async def key(self, combo: str) -> None:
        page = await self._ensure()
        key = _playwright_key(combo)
        if key:
            await page.keyboard.press(key)

    async def navigate(self, url: str) -> None:
        await self._require_url(url, "navigation")
        page = await self._ensure()
        await page.goto(url)
        self._last_pos = (0, 0)

    # --- DOM / accessibility mode (act by element ref, not pixels) ---

    async def dom_snapshot(self, max_elements: int = 200) -> list[dict[str, Any]]:
        """Tag visible interactive elements with ``data-nanobot-ref`` and return them.

        Each entry: ``{ref, tag, role, type, name, href}``. Refs are reassigned on
        every snapshot, so callers should act on the latest snapshot.
        """
        page = await self._ensure()
        return cast(list[dict[str, Any]], await page.evaluate(_SNAPSHOT_JS, max_elements))

    def _ref_selector(self, ref: int) -> str:
        return f'[data-nanobot-ref="{int(ref)}"]'

    async def click_ref(self, ref: int) -> None:
        page = await self._ensure()
        await page.click(self._ref_selector(ref), timeout=5000)

    async def fill_ref(self, ref: int, text: str, submit: bool = False) -> None:
        page = await self._ensure()
        sel = self._ref_selector(ref)
        await page.fill(sel, text, timeout=5000)
        if submit:
            await page.press(sel, "Enter")

    async def select_ref(self, ref: int, value: str) -> None:
        page = await self._ensure()
        sel = self._ref_selector(ref)
        try:
            await page.select_option(sel, value, timeout=3000)
        except Exception:
            # Models usually pass the visible label, not the option value.
            await page.select_option(sel, label=value, timeout=3000)

    async def scroll_page(self, direction: str, amount: int) -> None:
        page = await self._ensure()
        pixels = max(1, amount) * _SCROLL_PIXELS
        dx = pixels if direction == "right" else -pixels if direction == "left" else 0
        dy = pixels if direction == "down" else -pixels if direction == "up" else 0
        await page.evaluate("([x, y]) => window.scrollBy(x, y)", [dx, dy])

    async def go_back(self) -> None:
        page = await self._ensure()
        await page.go_back()

    async def read_text(self, max_chars: int = 4000) -> str:
        page = await self._ensure()
        txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
        return (txt or "")[:max_chars]

    async def current_url(self) -> str:
        page = await self._ensure()
        return page.url

    async def close(self) -> None:
        context = self._context
        self._context = self._page = None
        error: BaseException | None = None
        if context is not None:
            try:
                await context.close()
            except BaseException as exc:
                error = exc
        if self._owns_runtime:
            try:
                await self._runtime.close()
            except BaseException as exc:
                if error is not None:
                    raise BaseExceptionGroup("failed to close browser backend", [error, exc])
                raise
        if error is not None:
            raise error
