"""Tests for DOM-based browser control."""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.browser_tool import BrowserTool, BrowserToolConfig
from nanobot.agent.tools.computer_use_backends import browser_playwright
from nanobot.agent.tools.computer_use_backends.browser_playwright import BrowserBackend


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
    return BrowserTool(BrowserToolConfig(**kw), backend_impl=fb), fb


def _route(url: str, *, navigation: bool):
    return SimpleNamespace(
        request=SimpleNamespace(
            url=url,
            is_navigation_request=MagicMock(return_value=navigation),
        ),
        abort=AsyncMock(),
        continue_=AsyncMock(),
    )


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
        assert tool.config.allowed_domains == ["example.com"]

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
    @pytest.mark.parametrize(
        ("action", "kwargs", "expected"),
        [
            ("click", {"ref": 1}, ("click", 1)),
            ("type", {"ref": 2, "text": "Ada", "submit": True}, ("fill", 2, "Ada", True)),
            ("select", {"ref": 2, "value": "opt1"}, ("select", 2, "opt1")),
        ],
    )
    @pytest.mark.asyncio
    async def test_element_actions(self, action, kwargs, expected):
        tool, fb = _tool()
        result = await tool.execute(action=action, **kwargs)
        assert expected in fb.calls
        assert "Interactive elements" in result

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
    @pytest.mark.parametrize(
        ("kwargs", "error"),
        [
            ({"action": "teleport"}, "unknown action"),
            ({"action": "click"}, "requires an element 'ref'"),
        ],
    )
    @pytest.mark.asyncio
    async def test_tool_errors_are_returned_to_model(self, kwargs, error):
        tool, _ = _tool()
        result = await tool.execute(**kwargs)
        assert isinstance(result, str) and error in result

    @pytest.mark.asyncio
    async def test_backend_blocks_disallowed_navigation(self):
        backend = BrowserBackend(allowed_domains=["example.com"])
        page = SimpleNamespace(goto=AsyncMock())
        backend._page = page

        with pytest.raises(ValueError, match="allowed_domains"):
            await backend.navigate("https://evil.test/")

        page.goto.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_backend_allows_subdomain_navigation(self, monkeypatch: pytest.MonkeyPatch):
        check = MagicMock(return_value=(True, ""))
        monkeypatch.setattr(browser_playwright, "validate_url_target", check)
        backend = BrowserBackend(allowed_domains=["example.com"])
        page = SimpleNamespace(goto=AsyncMock())
        backend._page = page

        await backend.navigate("https://app.example.com/x")

        page.goto.assert_awaited_once_with("https://app.example.com/x")
        check.assert_called_once()

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "http://127.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "ws://localhost/socket",
        ],
    )
    @pytest.mark.asyncio
    async def test_browser_network_policy_blocks_local_targets(self, url: str):
        backend = BrowserBackend()
        with pytest.raises(ValueError, match="blocked"):
            await backend.navigate(url)

    @pytest.mark.asyncio
    async def test_backend_intercepts_blocked_navigation(self):
        backend = BrowserBackend(allowed_domains=["example.com"])
        route = _route("https://evil.test/", navigation=True)

        await backend._route_request(route)

        route.abort.assert_awaited_once_with("blockedbyclient")
        route.continue_.assert_not_awaited()
        assert "allowed_domains" in (backend.pop_blocked_navigation() or "")

    @pytest.mark.asyncio
    async def test_backend_intercepts_private_subresource(self):
        backend = BrowserBackend()
        route = _route(
            "http://169.254.169.254/latest/meta-data/",
            navigation=False,
        )

        await backend._route_request(route)

        route.abort.assert_awaited_once_with("blockedbyclient")
        assert backend.pop_blocked_navigation() is None

    @pytest.mark.asyncio
    async def test_backend_does_not_apply_navigation_allowlist_to_subresources(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            browser_playwright,
            "validate_url_target",
            MagicMock(return_value=(True, "")),
        )
        backend = BrowserBackend(allowed_domains=["example.com"])
        route = _route("https://cdn.other.test/app.js", navigation=False)

        await backend._route_request(route)

        route.continue_.assert_awaited_once()
        route.abort.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_backend_intercepts_private_websocket(self):
        backend = BrowserBackend()
        web_socket = SimpleNamespace(
            url="ws://127.0.0.1/socket",
            close=AsyncMock(),
            connect_to_server=AsyncMock(),
        )

        await backend._route_web_socket(web_socket)

        web_socket.close.assert_awaited_once()
        web_socket.connect_to_server.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_backend_rejects_file_start_url_before_launch(self):
        backend = BrowserBackend(start_url="file:///etc/passwd")
        with pytest.raises(ValueError, match="start_url is blocked"):
            await backend.dimensions()
