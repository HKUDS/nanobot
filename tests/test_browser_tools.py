"""Tests for browser tools (no live browser required)."""

import pytest
from unittest.mock import AsyncMock, patch

from nanobot.agent.tools.browser import (
    BrowserSession,
    BrowserNavigateTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserSaveSessionTool,
    _validate_url,
    _get_win_username,
    create_browser_tools,
)
from nanobot.config.schema import BrowserToolConfig


def _make_session() -> BrowserSession:
    return BrowserSession()


# ── _validate_url ─────────────────────────────────────────────────────────────


def test_validate_url_valid():
    ok, err = _validate_url("http://example.com")
    assert ok is True and err == ""


def test_validate_url_rejects_ftp():
    ok, err = _validate_url("ftp://example.com")
    assert ok is False and "ftp" in err


def test_validate_url_rejects_no_scheme():
    ok, _ = _validate_url("example.com")
    assert ok is False


def test_validate_url_rejects_missing_domain():
    ok, err = _validate_url("https://")
    assert ok is False and "Missing domain" in err


# ── _get_win_username ─────────────────────────────────────────────────────────


def test_get_win_username_returns_string():
    # On Linux/CI falls back to $USER or "user" — verifies no crash
    result = _get_win_username()
    assert isinstance(result, str) and len(result) > 0


# ── create_browser_tools when Playwright unavailable ──────────────────────────


def test_create_browser_tools_no_playwright():
    with patch("nanobot.agent.tools.browser._PLAYWRIGHT_AVAILABLE", False):
        tools, session = create_browser_tools(BrowserToolConfig(enabled=True))
    assert tools == [] and session is None


# ── Tool schema ───────────────────────────────────────────────────────────────


def test_navigate_schema_has_required_url():
    params = BrowserNavigateTool(_make_session()).parameters
    assert "url" in params["properties"] and "url" in params["required"]


def test_navigate_browser_enum():
    params = BrowserNavigateTool(_make_session()).parameters
    enum_vals = params["properties"]["browser"]["enum"]
    assert "chromium" in enum_vals and "edge" in enum_vals and "default" in enum_vals


def test_click_schema_requires_ref():
    params = BrowserClickTool(_make_session()).parameters
    assert "ref" in params["required"] and params["properties"]["ref"]["type"] == "integer"


def test_type_schema_requires_ref_and_text():
    params = BrowserTypeTool(_make_session()).parameters
    assert "ref" in params["required"] and "text" in params["required"]
    assert "submit" not in params["required"]


def test_save_session_schema_no_required():
    assert BrowserSaveSessionTool(_make_session()).parameters["required"] == []


# ── BrowserSession remote flag ────────────────────────────────────────────────


def test_session_remote_flag():
    assert BrowserSession(cdp_url="http://localhost:9223")._remote is True
    assert BrowserSession()._remote is False


# ── BrowserSession.reconfigure ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconfigure_updates_headless():
    s = BrowserSession(headless=True)
    await s.reconfigure(headless=False)
    assert s._headless is False


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
async def test_reconfigure_closes_existing_page():
    s = BrowserSession()
    s._page = AsyncMock()
    s._context = AsyncMock()
    s._browser = AsyncMock()
    s._playwright = AsyncMock()

    await s.reconfigure(headless=False)

    assert s._page is None and s._headless is False


# ── BrowserNavigateTool.execute ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_navigate_rejects_invalid_url():
    result = await BrowserNavigateTool(_make_session()).execute(url="ftp://bad.com")
    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_navigate_uses_get_page():
    s = _make_session()
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
            tool = BrowserNavigateTool(s, default_cdp_url="http://localhost:9223")
            await tool.execute(url="https://example.com", browser="chromium")

    assert reconf_calls[0]["cdp_url"] == ""


# ── BrowserSaveSessionTool.execute ────────────────────────────────────────────


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
