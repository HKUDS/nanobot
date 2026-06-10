"""Tests for the DOM-based browser tool (model-agnostic web actions).

Backend is a duck-typed fake, so no playwright is needed (only Pillow for the
optional screenshot path)."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.browser_tool import BrowserTool, BrowserToolConfig


class _FakeDomBackend:
    environment = "browser"

    def __init__(self):
        self.calls: list[tuple] = []
        self.elements = [
            {"ref": 1, "tag": "button", "role": "", "type": "", "name": "Submit", "href": ""},
            {"ref": 2, "tag": "input", "role": "", "type": "text", "name": "your name", "href": ""},
        ]

    async def navigate(self, url):
        self.calls.append(("navigate", url))

    async def dom_snapshot(self, max_elements=200):
        return self.elements

    async def click_ref(self, ref):
        self.calls.append(("click", ref))

    async def fill_ref(self, ref, text, submit=False):
        self.calls.append(("fill", ref, text, submit))

    async def select_ref(self, ref, value):
        self.calls.append(("select", ref, value))

    async def scroll_page(self, direction, amount):
        self.calls.append(("scroll", direction, amount))

    async def key(self, combo):
        self.calls.append(("key", combo))

    async def go_back(self):
        self.calls.append(("back",))

    async def read_text(self, max_chars=4000):
        return "the number is 42"

    async def current_url(self):
        return "http://test.local/page"

    async def screenshot(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1280, 800), (0, 0, 0)).save(buf, format="PNG")
        return buf.getvalue()

    async def close(self):
        self.calls.append(("close",))


def _tool(**kw):
    fb = _FakeDomBackend()
    return BrowserTool(backend_impl=fb, **kw), fb


class TestConfigAndMetadata:
    def test_defaults_off(self):
        cfg = BrowserToolConfig()
        assert cfg.enable is False
        assert cfg.headless is True
        assert cfg.include_screenshot is False
        assert cfg.max_elements == 200

    def test_enabled_reads_config(self):
        ctx = MagicMock()
        ctx.config.browser.enable = True
        assert BrowserTool.enabled(ctx) is True
        ctx.config.browser.enable = False
        assert BrowserTool.enabled(ctx) is False

    def test_create_from_ctx(self):
        ctx = MagicMock()
        ctx.config.browser = BrowserToolConfig(enable=True, allowed_domains=["example.com"])
        tool = BrowserTool.create(ctx)
        assert isinstance(tool, BrowserTool)
        assert tool.allowed_domains == ["example.com"]

    def test_metadata(self):
        tool, _ = _tool()
        assert tool.name == "browser"
        assert tool.exclusive is True
        assert tool.read_only is False
        assert "subagent" not in tool._scopes

    def test_schema_actions(self):
        tool, _ = _tool()
        enum = tool.parameters["properties"]["action"]["enum"]
        for a in ("navigate", "snapshot", "click", "type", "read_text"):
            assert a in enum


class TestDispatch:
    @pytest.mark.asyncio
    async def test_navigate_returns_snapshot(self):
        tool, fb = _tool()
        result = await tool.execute(action="navigate", url="https://example.com")
        assert ("navigate", "https://example.com") in fb.calls
        assert isinstance(result, str)
        assert "Navigated to https://example.com" in result
        # snapshot of interactive elements is appended
        assert '[1] button "Submit"' in result
        assert '[2] input[text] "your name"' in result

    @pytest.mark.asyncio
    async def test_click_by_ref(self):
        tool, fb = _tool()
        result = await tool.execute(action="click", ref=1)
        assert ("click", 1) in fb.calls
        assert "Clicked element [1]" in result
        # fresh snapshot returned so refs stay current
        assert "Interactive elements" in result

    @pytest.mark.asyncio
    async def test_type_with_submit(self):
        tool, fb = _tool()
        await tool.execute(action="type", ref=2, text="Ada", submit=True)
        assert ("fill", 2, "Ada", True) in fb.calls

    @pytest.mark.asyncio
    async def test_select(self):
        tool, fb = _tool()
        await tool.execute(action="select", ref=2, value="opt1")
        assert ("select", 2, "opt1") in fb.calls

    @pytest.mark.asyncio
    async def test_scroll_and_key_and_back(self):
        tool, fb = _tool()
        await tool.execute(action="scroll", scroll_direction="down", scroll_amount=4)
        await tool.execute(action="key", text="Enter")
        await tool.execute(action="back")
        assert ("scroll", "down", 4) in fb.calls
        assert ("key", "Enter") in fb.calls
        assert ("back",) in fb.calls

    @pytest.mark.asyncio
    async def test_read_text_returns_text_no_snapshot(self):
        tool, _ = _tool()
        result = await tool.execute(action="read_text")
        assert isinstance(result, str)
        assert "the number is 42" in result
        assert "Interactive elements" not in result

    @pytest.mark.asyncio
    async def test_include_screenshot_returns_blocks(self):
        tool, _ = _tool(include_screenshot=True)
        result = await tool.execute(action="click", ref=1)
        assert isinstance(result, list)
        imgs = [b for b in result if b.get("type") == "image_url"]
        texts = [b for b in result if b.get("type") == "text"]
        assert imgs and texts
        assert "Clicked element [1]" in texts[-1]["text"]


class TestErrorsAndPolicy:
    @pytest.mark.asyncio
    async def test_unknown_action(self):
        tool, _ = _tool()
        result = await tool.execute(action="teleport")
        assert isinstance(result, str) and "unknown action" in result

    @pytest.mark.asyncio
    async def test_click_requires_ref(self):
        tool, _ = _tool()
        result = await tool.execute(action="click")
        assert isinstance(result, str) and "requires an element 'ref'" in result

    @pytest.mark.asyncio
    async def test_navigate_blocked_by_allowlist(self):
        tool, fb = _tool(allowed_domains=["example.com"])
        result = await tool.execute(action="navigate", url="https://evil.test/")
        assert "blocked by the allowed_domains" in result
        assert not any(c[0] == "navigate" for c in fb.calls)

    @pytest.mark.asyncio
    async def test_navigate_allowed_subdomain(self):
        tool, fb = _tool(allowed_domains=["example.com"])
        await tool.execute(action="navigate", url="https://app.example.com/x")
        assert ("navigate", "https://app.example.com/x") in fb.calls
