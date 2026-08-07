"""PyAutoGUI desktop backend with HiDPI coordinate correction."""

from __future__ import annotations

import asyncio
import io
from typing import Any

from nanobot.agent.tools.computer_use_backends.base import ComputerBackend

_MISSING = (
    "Desktop computer-use backend needs 'pyautogui' and 'pillow'. "
    "Install with: pip install 'nanobot-ai[computer-use]'"
)

# xdotool/CUA-style key names -> PyAutoGUI key names.
_KEY_ALIASES = {
    "return": "enter",
    "ctrl": "ctrl",
    "control": "ctrl",
    "cmd": "command",
    "super": "win",
    "win": "win",
    "page_down": "pagedown",
    "page_up": "pageup",
    "pagedown": "pagedown",
    "pageup": "pageup",
    "esc": "esc",
    "escape": "esc",
}


class DesktopBackend(ComputerBackend):
    environment = "desktop"

    def __init__(self) -> None:
        self._pg: Any = None
        self._ratio_x = 1.0
        self._ratio_y = 1.0
        self._dims: tuple[int, int] | None = None

    def _ensure(self) -> Any:
        if self._pg is not None:
            return self._pg
        try:
            import pyautogui  # noqa: PLC0415
        except Exception as exc:  # ImportError, or platform display errors
            raise ImportError(_MISSING) from exc
        self._pg = pyautogui
        return pyautogui

    def _grab_png_and_size(self) -> tuple[bytes, int, int]:
        pg = self._ensure()
        img = pg.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        width, height = img.size
        # Refresh logical<->physical ratio from the actual grab.
        try:
            logical_w, logical_h = pg.size()
            self._ratio_x = (logical_w / width) if width else 1.0
            self._ratio_y = (logical_h / height) if height else 1.0
        except Exception:
            self._ratio_x = self._ratio_y = 1.0
        self._dims = (width, height)
        return buf.getvalue(), width, height

    def _to_logical(self, x: int, y: int) -> tuple[int, int]:
        return round(x * self._ratio_x), round(y * self._ratio_y)

    async def dimensions(self) -> tuple[int, int]:
        if self._dims is not None:
            return self._dims
        _, w, h = await asyncio.to_thread(self._grab_png_and_size)
        return w, h

    async def screenshot(self) -> bytes:
        png, _, _ = await asyncio.to_thread(self._grab_png_and_size)
        return png

    async def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        pg = self._ensure()
        lx, ly = self._to_logical(x, y)
        await asyncio.to_thread(pg.click, lx, ly, clicks=count, button=button)

    async def move(self, x: int, y: int) -> None:
        pg = self._ensure()
        lx, ly = self._to_logical(x, y)
        await asyncio.to_thread(pg.moveTo, lx, ly)

    async def drag(self, x: int, y: int) -> None:
        pg = self._ensure()
        lx, ly = self._to_logical(x, y)
        await asyncio.to_thread(
            pg.dragTo,
            lx,
            ly,
            duration=0.3,
            tween=pg.easeInOutQuad,
            button="left",
        )

    async def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        pg = self._ensure()
        lx, ly = self._to_logical(x, y)
        clicks = max(1, amount)
        await asyncio.to_thread(pg.moveTo, lx, ly)
        if direction in ("up", "down"):
            await asyncio.to_thread(pg.scroll, clicks if direction == "up" else -clicks)
        else:
            await asyncio.to_thread(pg.hscroll, clicks if direction == "right" else -clicks)

    async def type_text(self, text: str) -> None:
        pg = self._ensure()
        await asyncio.to_thread(pg.typewrite, text, 0.01)

    async def key(self, combo: str) -> None:
        pg = self._ensure()
        keys = [
            _KEY_ALIASES.get(part.strip().lower(), part.strip().lower())
            for part in combo.split("+")
            if part.strip()
        ]
        if not keys:
            return
        if len(keys) == 1:
            await asyncio.to_thread(pg.press, keys[0])
        else:
            await asyncio.to_thread(pg.hotkey, *keys)
