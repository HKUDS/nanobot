"""Tests for the computer_use tool, its config wiring, and coordinate scaling.

Backend actuation is exercised through an injected fake backend, so these tests
need neither pyautogui nor playwright (only Pillow, for screenshot downscaling).
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.computer_use import ComputerUseTool, ComputerUseToolConfig
from nanobot.agent.tools.computer_use_backends.base import ComputerBackend
from nanobot.utils.screen_scale import ScreenScaler, fit_target_size


class _FakeBackend(ComputerBackend):
    """Records actuation calls and serves a solid-colour PNG of a fixed size."""

    environment = "desktop"

    def __init__(self, width: int = 2560, height: int = 1600):
        self.calls: list[tuple] = []
        self._w, self._h = width, height

    async def dimensions(self) -> tuple[int, int]:
        return (self._w, self._h)

    async def screenshot(self) -> bytes:
        from PIL import Image
        img = Image.new("RGB", (self._w, self._h), (10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    async def click(self, x, y, button="left", count=1):
        self.calls.append(("click", x, y, button, count))

    async def move(self, x, y):
        self.calls.append(("move", x, y))

    async def drag(self, x, y):
        self.calls.append(("drag", x, y))

    async def scroll(self, x, y, direction, amount):
        self.calls.append(("scroll", x, y, direction, amount))

    async def type_text(self, text):
        self.calls.append(("type", text))

    async def key(self, combo):
        self.calls.append(("key", combo))
    # navigate() inherited -> raises NotImplementedError (desktop has no navigate)


def _split(result):
    assert isinstance(result, list), f"expected content blocks, got {result!r}"
    images = [b for b in result if isinstance(b, dict) and b.get("type") == "image_url"]
    texts = [b for b in result if isinstance(b, dict) and b.get("type") == "text"]
    return images, texts


def _tool(**kw):
    fb = _FakeBackend(width=kw.pop("w", 2560), height=kw.pop("h", 1600))
    tool = ComputerUseTool(backend_impl=fb, target_width=1280, target_height=800, **kw)
    return tool, fb


# --------------------------- coordinate scaling (pure) ---------------------------

class TestScreenScale:
    def test_fit_never_upscales(self):
        assert fit_target_size(800, 600, 1280, 800) == (800, 600)

    def test_fit_preserves_aspect(self):
        # 2560x1600 (16:10) into 1280x800 box -> exactly halved.
        assert fit_target_size(2560, 1600, 1280, 800) == (1280, 800)

    def test_fit_landscape_into_box(self):
        # 3000x1000 into 1280x800 -> width-bound: scale 1280/3000.
        w, h = fit_target_size(3000, 1000, 1280, 800)
        assert w == 1280 and h == round(1000 * 1280 / 3000)

    def test_to_real_scales_up(self):
        sc = ScreenScaler.for_screen(2560, 1600, 1280, 800)
        assert sc.to_real(100, 50) == (200, 100)

    def test_to_real_clamps_in_bounds(self):
        sc = ScreenScaler.for_screen(1000, 1000, 1000, 1000)
        assert sc.to_real(5000, 5000) == (999, 999)
        assert sc.to_real(-10, -10) == (0, 0)


# --------------------------- config + metadata ---------------------------

class TestConfigAndMetadata:
    def test_defaults_off(self):
        cfg = ComputerUseToolConfig()
        assert cfg.enable is False
        assert cfg.backend == "desktop"
        assert (cfg.target_width, cfg.target_height) == (1280, 800)
        assert cfg.require_approval is True

    def test_enabled_reads_config(self):
        ctx = MagicMock()
        ctx.config.computer_use.enable = True
        assert ComputerUseTool.enabled(ctx) is True
        ctx.config.computer_use.enable = False
        assert ComputerUseTool.enabled(ctx) is False

    def test_create_from_ctx(self):
        ctx = MagicMock()
        ctx.config.computer_use = ComputerUseToolConfig(
            enable=True, backend="browser", target_width=1024, target_height=768
        )
        tool = ComputerUseTool.create(ctx)
        assert isinstance(tool, ComputerUseTool)
        assert tool.backend_name == "browser"
        assert (tool.target_width, tool.target_height) == (1024, 768)

    def test_tool_metadata(self):
        tool, _ = _tool()
        assert tool.name == "computer_use"
        assert tool.exclusive is True
        assert tool.read_only is False
        assert tool.concurrency_safe is False
        # not exposed to subagents
        assert "subagent" not in tool._scopes

    def test_schema_has_action_enum(self):
        tool, _ = _tool()
        action = tool.parameters["properties"]["action"]
        assert "screenshot" in action["enum"]
        assert "left_click" in action["enum"]
        assert tool.parameters["required"] == ["action"]


# --------------------------- execute dispatch ---------------------------

class TestExecute:
    @pytest.mark.asyncio
    async def test_screenshot_returns_image_blocks(self):
        tool, fb = _tool()
        result = await tool.execute(action="screenshot")
        images, texts = _split(result)
        assert len(images) == 1
        assert images[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "1280x800" in texts[-1]["text"]
        assert fb.calls == []  # screenshot performs no actuation

    @pytest.mark.asyncio
    async def test_left_click_scales_coordinates(self):
        tool, fb = _tool()  # real 2560x1600 -> target 1280x800 (2x)
        result = await tool.execute(action="left_click", x=100, y=50)
        assert fb.calls == [("click", 200, 100, "left", 1)]
        _, texts = _split(result)
        assert "left_click at (200, 100)" in texts[-1]["text"]

    @pytest.mark.asyncio
    async def test_click_accepts_coordinate_array(self):
        # Some models emit a combined [x, y] array (Anthropic's native convention).
        tool, fb = _tool()
        await tool.execute(action="left_click", x=[100, 50])
        assert fb.calls == [("click", 200, 100, "left", 1)]

    @pytest.mark.asyncio
    async def test_double_and_triple_click_counts(self):
        tool, fb = _tool()
        await tool.execute(action="double_click", x=10, y=10)
        await tool.execute(action="triple_click", x=10, y=10)
        assert fb.calls[0] == ("click", 20, 20, "left", 2)
        assert fb.calls[1] == ("click", 20, 20, "left", 3)

    @pytest.mark.asyncio
    async def test_right_and_middle_click_buttons(self):
        tool, fb = _tool()
        await tool.execute(action="right_click", x=5, y=5)
        await tool.execute(action="middle_click", x=5, y=5)
        assert fb.calls[0][3] == "right"
        assert fb.calls[1][3] == "middle"

    @pytest.mark.asyncio
    async def test_scroll_defaults_and_args(self):
        tool, fb = _tool()
        await tool.execute(action="scroll", x=100, y=100, scroll_direction="down", scroll_amount=5)
        assert fb.calls == [("scroll", 200, 200, "down", 5)]

    @pytest.mark.asyncio
    async def test_type_and_key(self):
        tool, fb = _tool()
        await tool.execute(action="type", text="hello")
        await tool.execute(action="key", text="ctrl+s")
        assert ("type", "hello") in fb.calls
        assert ("key", "ctrl+s") in fb.calls

    @pytest.mark.asyncio
    async def test_drag_and_move(self):
        tool, fb = _tool()
        await tool.execute(action="mouse_move", x=10, y=10)
        await tool.execute(action="left_click_drag", x=20, y=30)
        assert ("move", 20, 20) in fb.calls
        assert ("drag", 40, 60) in fb.calls

    @pytest.mark.asyncio
    async def test_wait(self):
        tool, fb = _tool()
        result = await tool.execute(action="wait", duration=0.0)
        _, texts = _split(result)
        assert "Waited" in texts[-1]["text"]

    # ---- error paths return a plain string (model can self-correct) ----

    @pytest.mark.asyncio
    async def test_unknown_action_errors(self):
        tool, _ = _tool()
        result = await tool.execute(action="frobnicate")
        assert isinstance(result, str) and "unknown action" in result

    @pytest.mark.asyncio
    async def test_click_requires_coordinates(self):
        tool, _ = _tool()
        result = await tool.execute(action="left_click")
        assert isinstance(result, str) and "requires" in result

    @pytest.mark.asyncio
    async def test_navigate_unsupported_on_desktop(self):
        tool, _ = _tool()
        result = await tool.execute(action="navigate", url="https://example.com")
        assert isinstance(result, str) and "Error" in result


class _BrowserFakeBackend(_FakeBackend):
    environment = "browser"

    async def navigate(self, url):
        self.calls.append(("navigate", url))


class TestAllowedDomainsPolicy:
    def _browser_tool(self, allowed):
        fb = _BrowserFakeBackend(width=1280, height=800)
        tool = ComputerUseTool(
            backend_impl=fb,
            backend="browser",
            target_width=1280,
            target_height=800,
            allowed_domains=allowed,
        )
        return tool, fb

    @pytest.mark.asyncio
    async def test_empty_allowlist_allows_all(self):
        tool, fb = self._browser_tool([])
        await tool.execute(action="navigate", url="https://anything.example/")
        assert ("navigate", "https://anything.example/") in fb.calls

    @pytest.mark.asyncio
    async def test_exact_domain_allowed(self):
        tool, fb = self._browser_tool(["example.com"])
        await tool.execute(action="navigate", url="https://example.com/path")
        assert any(c[0] == "navigate" for c in fb.calls)

    @pytest.mark.asyncio
    async def test_subdomain_allowed(self):
        tool, fb = self._browser_tool(["example.com"])
        await tool.execute(action="navigate", url="https://app.example.com/")
        assert any(c[0] == "navigate" for c in fb.calls)

    @pytest.mark.asyncio
    async def test_disallowed_domain_blocked(self):
        tool, fb = self._browser_tool(["example.com"])
        result = await tool.execute(action="navigate", url="https://evil.test/")
        assert isinstance(result, str) and "blocked by the allowed_domains" in result
        assert not any(c[0] == "navigate" for c in fb.calls)
