"""Tests for screenshot-based computer control."""

from __future__ import annotations

import asyncio
import io
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.computer_use import ComputerUseTool, ComputerUseToolConfig
from nanobot.agent.tools.computer_use_backends.base import ComputerBackend, SessionBackendPool
from nanobot.agent.tools.computer_use_backends.desktop_pyautogui import DesktopBackend
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.config.schema import ToolsConfig


class _FakeBackend(ComputerBackend):
    """Records actuation calls and serves a solid-colour PNG of a fixed size."""

    environment = "desktop"

    def __init__(self, width: int = 2560, height: int = 1600):
        self.calls: list[tuple] = []
        self._w, self._h = width, height
        self.closed = False

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

    async def close(self):
        self.closed = True
    # navigate() inherited -> raises NotImplementedError (desktop has no navigate)


def _split(result):
    assert isinstance(result, list), f"expected content blocks, got {result!r}"
    images = [b for b in result if isinstance(b, dict) and b.get("type") == "image_url"]
    texts = [b for b in result if isinstance(b, dict) and b.get("type") == "text"]
    return images, texts


def _tool(**kw):
    fb = _FakeBackend(width=kw.pop("w", 2560), height=kw.pop("h", 1600))
    config = ComputerUseToolConfig(target_width=1280, target_height=800, **kw)
    tool = ComputerUseTool(config, backend_impl=fb)
    return tool, fb


# --------------------------- config + metadata ---------------------------

class TestConfigAndMetadata:
    def test_defaults_off(self):
        cfg = ComputerUseToolConfig()
        assert cfg.enable is False
        assert cfg.backend == "desktop"
        assert (cfg.target_width, cfg.target_height) == (1280, 800)
        assert cfg.max_sessions == 8
        assert "require_approval" not in type(cfg).model_fields

    def test_tools_config_accepts_camel_case(self):
        cfg = ToolsConfig.model_validate({
            "browser": {"enable": True, "maxSessions": 4},
            "computerUse": {"enable": True, "backend": "browser", "maxSessions": 6},
        })

        assert cfg.browser.enable is True
        assert cfg.browser.max_sessions == 4
        assert cfg.computer_use.enable is True
        assert cfg.computer_use.backend == "browser"
        assert cfg.computer_use.max_sessions == 6
        dumped = cfg.model_dump(by_alias=True)
        assert "computerUse" in dumped
        assert dumped["computerUse"]["maxSessions"] == 6

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
        assert tool.config.backend == "browser"
        assert (tool.config.target_width, tool.config.target_height) == (1024, 768)

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
    async def test_click_clamps_coordinates_to_screen(self):
        tool, fb = _tool()
        await tool.execute(action="left_click", x=5000, y=-10)
        assert fb.calls == [("click", 2559, 0, "left", 1)]

    @pytest.mark.parametrize(
        ("action", "kwargs", "expected"),
        [
            ("double_click", {"x": 10, "y": 10}, ("click", 20, 20, "left", 2)),
            ("triple_click", {"x": 10, "y": 10}, ("click", 20, 20, "left", 3)),
            ("right_click", {"x": 5, "y": 5}, ("click", 10, 10, "right", 1)),
            ("middle_click", {"x": 5, "y": 5}, ("click", 10, 10, "middle", 1)),
            (
                "scroll",
                {"x": 100, "y": 100, "scroll_direction": "down", "scroll_amount": 5},
                ("scroll", 200, 200, "down", 5),
            ),
            ("type", {"text": "hello"}, ("type", "hello")),
            ("key", {"text": "ctrl+s"}, ("key", "ctrl+s")),
            ("mouse_move", {"x": 10, "y": 10}, ("move", 20, 20)),
            ("left_click_drag", {"x": 20, "y": 30}, ("drag", 40, 60)),
        ],
    )
    @pytest.mark.asyncio
    async def test_actions_dispatch_to_backend(self, action, kwargs, expected):
        tool, fb = _tool()
        await tool.execute(action=action, **kwargs)
        assert fb.calls == [expected]

    @pytest.mark.asyncio
    async def test_wait(self):
        tool, fb = _tool()
        result = await tool.execute(action="wait", duration=0.0)
        _, texts = _split(result)
        assert "Waited" in texts[-1]["text"]

    @pytest.mark.parametrize(
        ("kwargs", "error"),
        [
            ({"action": "frobnicate"}, "unknown action"),
            ({"action": "left_click"}, "requires"),
            ({"action": "navigate", "url": "https://example.com"}, "Error"),
        ],
    )
    @pytest.mark.asyncio
    async def test_errors_are_returned_to_model(self, kwargs, error):
        tool, _ = _tool()
        result = await tool.execute(**kwargs)
        assert isinstance(result, str) and error in result
        assert result.is_error is True


@pytest.mark.asyncio
async def test_backend_pool_isolates_sessions_and_closes_all():
    created: list[_FakeBackend] = []
    finalized: list[bool] = []

    def factory():
        backend = _FakeBackend()
        created.append(backend)
        return backend

    async def finalize():
        finalized.append(all(backend.closed for backend in created))

    pool = SessionBackendPool(factory, finalizer=finalize)
    with request_context(RequestContext(channel="test", chat_id="a", session_key="test:a")):
        first = await pool.get()
        assert await pool.get() is first
    with request_context(RequestContext(channel="test", chat_id="b", session_key="test:b")):
        second = await pool.get()

    assert first is not second
    await pool.close()
    assert len(created) == 2
    assert all(backend.closed for backend in created)
    assert finalized == [True]

    await pool.close()
    assert finalized == [True]


@pytest.mark.asyncio
async def test_backend_pool_evicts_least_recently_used_session():
    created: list[_FakeBackend] = []

    def factory():
        backend = _FakeBackend()
        created.append(backend)
        return backend

    pool = SessionBackendPool(factory, max_backends=2)
    contexts = [
        RequestContext(channel="test", chat_id=key, session_key=f"test:{key}")
        for key in ("a", "b", "c")
    ]
    with request_context(contexts[0]):
        first = await pool.get()
    with request_context(contexts[1]):
        second = await pool.get()
    with request_context(contexts[0]):
        assert await pool.get() is first
    with request_context(contexts[2]):
        await pool.get()

    assert first.closed is False
    assert second.closed is True
    await pool.close()


@pytest.mark.asyncio
async def test_desktop_tool_serializes_calls_across_sessions():
    class SlowBackend(_FakeBackend):
        active = 0
        max_active = 0

        async def dimensions(self):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return await super().dimensions()

    backend = SlowBackend(width=1280, height=800)
    tool = ComputerUseTool(backend_impl=backend)

    async def screenshot(session: str):
        with request_context(RequestContext(channel="test", chat_id=session, session_key=session)):
            return await tool.execute(action="screenshot")

    await asyncio.gather(screenshot("a"), screenshot("b"))

    assert backend.max_active == 1


@pytest.mark.asyncio
async def test_desktop_backend_uses_safe_pyautogui_calls():
    pg = MagicMock()
    pg.easeInOutQuad = object()
    backend = DesktopBackend()
    backend._pg = pg

    await backend.drag(10, 20)
    await backend.scroll(10, 20, "down", 3)

    assert pg.dragTo.call_args.kwargs == {
        "duration": 0.3,
        "tween": pg.easeInOutQuad,
        "button": "left",
    }
    pg.scroll.assert_called_once_with(-3)


@pytest.mark.asyncio
async def test_desktop_backend_rejects_unicode_instead_of_typing_incorrect_keys():
    pg = MagicMock()
    backend = DesktopBackend()
    backend._pg = pg

    with pytest.raises(ValueError, match="ASCII"):
        await backend.type_text("你好")

    pg.typewrite.assert_not_called()


def test_desktop_backend_preserves_pyautogui_failsafe(monkeypatch):
    pg = SimpleNamespace(FAILSAFE=True)
    monkeypatch.setitem(sys.modules, "pyautogui", pg)

    backend = DesktopBackend()
    assert backend._ensure() is pg
    assert pg.FAILSAFE is True
