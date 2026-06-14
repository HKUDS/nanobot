"""Browser backend using Playwright (DOM-aware, deterministic, sandbox-friendly).

Drives a headless Chromium page via pixel coordinates + screenshots, mirroring
the desktop backend's surface so the same model/tool loop works against the web.
The viewport uses ``deviceScaleFactor=1`` so screenshot pixels == mouse
coordinates (no HiDPI scaling to undo). The browser/page persist across actions
within one tool instance so navigation and state carry between turns.
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.computer_use_backends.base import ComputerBackend

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


class BrowserBackend(ComputerBackend):
    environment = "browser"

    def __init__(
        self,
        *,
        width: int = 1280,
        height: int = 800,
        headless: bool = True,
        start_url: str = "about:blank",
    ) -> None:
        self._width = width
        self._height = height
        self._headless = headless
        self._start_url = start_url
        self._pw: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._last_pos = (0, 0)

    async def _ensure(self) -> Any:
        if self._page is not None:
            return self._page
        try:
            from playwright.async_api import async_playwright  # noqa: PLC0415
        except Exception as exc:
            raise ImportError(_MISSING) from exc
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)
        context = await self._browser.new_context(
            viewport={"width": self._width, "height": self._height},
            device_scale_factor=1,
        )
        self._page = await context.new_page()
        if self._start_url and self._start_url != "about:blank":
            await self._page.goto(self._start_url)
        return self._page

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
        page = await self._ensure()
        await page.goto(url)
        self._last_pos = (0, 0)

    # --- DOM / accessibility mode (act by element ref, not pixels) ---

    async def dom_snapshot(self, max_elements: int = 200) -> list[dict]:
        """Tag visible interactive elements with ``data-nanobot-ref`` and return them.

        Each entry: ``{ref, tag, role, type, name, href}``. Refs are reassigned on
        every snapshot, so callers should act on the latest snapshot.
        """
        page = await self._ensure()
        return await page.evaluate(_SNAPSHOT_JS, max_elements)

    def _ref_selector(self, ref) -> str:
        return f'[data-nanobot-ref="{int(ref)}"]'

    async def click_ref(self, ref) -> None:
        page = await self._ensure()
        await page.click(self._ref_selector(ref), timeout=5000)

    async def fill_ref(self, ref, text: str, submit: bool = False) -> None:
        page = await self._ensure()
        sel = self._ref_selector(ref)
        await page.fill(sel, text, timeout=5000)
        if submit:
            await page.press(sel, "Enter")

    async def select_ref(self, ref, value: str) -> None:
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
        try:
            if self._browser is not None:
                await self._browser.close()
        finally:
            if self._pw is not None:
                await self._pw.stop()
            self._browser = None
            self._page = None
            self._pw = None
