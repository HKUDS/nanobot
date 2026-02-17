"""Tests for browser tools (no live browser required)."""

import pytest
from unittest.mock import AsyncMock, patch

from nanobot.agent.tools.browser import BrowserSession, BrowserNavigateTool, BrowserSaveSessionTool


@pytest.mark.asyncio
async def test_reconfigure_closes_existing_page():
    s = BrowserSession()
    s._page = AsyncMock()
    s._context = AsyncMock()
    s._browser = AsyncMock()
    s._playwright = AsyncMock()
    await s.reconfigure(headless=False)
    assert s._page is None and s._headless is False


@pytest.mark.asyncio
async def test_reconfigure_updates_cdp_url():
    s = BrowserSession(cdp_url="")
    await s.reconfigure(cdp_url="http://localhost:9223")
    assert s._cdp_url == "http://localhost:9223" and s._remote is True


@pytest.mark.asyncio
async def test_reconfigure_clears_remote_flag():
    s = BrowserSession(cdp_url="http://localhost:9223")
    await s.reconfigure(cdp_url="")
    assert s._remote is False


@pytest.mark.asyncio
async def test_navigate_uses_get_page():
    s = BrowserSession()
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(return_value=None)
    with patch.object(s, "get_page", return_value=mock_page):
        result = await BrowserNavigateTool(s).execute(url="https://example.com")
    assert "Navigated to https://example.com" in result
    mock_page.goto.assert_called_once_with("https://example.com", wait_until="load")


@pytest.mark.asyncio
async def test_navigate_browser_chromium_sets_empty_cdp():
    s = BrowserSession(cdp_url="http://localhost:9223")
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(return_value=None)
    reconf_calls = []

    async def _fake_reconfigure(**kw):
        reconf_calls.append(kw)
        s._cdp_url = kw.get("cdp_url", s._cdp_url)
        s._remote = bool(s._cdp_url)

    with patch.object(s, "reconfigure", side_effect=_fake_reconfigure):
        with patch.object(s, "get_page", return_value=mock_page):
            await BrowserNavigateTool(s, default_cdp_url="http://localhost:9223").execute(
                url="https://example.com", browser="chromium"
            )
    assert reconf_calls[0]["cdp_url"] == ""


@pytest.mark.asyncio
async def test_save_session_no_path_configured():
    result = await BrowserSaveSessionTool(BrowserSession(storage_state_path="")).execute()
    assert "Error:" in result


@pytest.mark.asyncio
async def test_save_session_not_started():
    result = await BrowserSaveSessionTool(BrowserSession(storage_state_path="/tmp/x.json")).execute()
    assert "Error:" in result


@pytest.mark.asyncio
async def test_save_session_remote_mode_not_supported():
    s = BrowserSession(cdp_url="http://localhost:9223", storage_state_path="/tmp/test.json")
    ok, msg = await s.save_storage_state()
    assert ok is False and ("remote" in msg.lower() or "not supported" in msg.lower())
