"""Complex, multi-step DOM-browser e2e against a small local web app.

Pages live in ``tests/e2e/pages/`` and are served over a local HTTP server (so
localStorage and cross-page navigation work). Scenarios exercise realistic
flows: a multi-field form (text + select + radio + checkbox), an add-to-cart +
checkout flow across pages, picking one row out of 60, and a login → dashboard
redirect. All run in DOM mode (act by element ref), so they are model-agnostic.

Run:
    pip install 'nanobot-ai[computer-use]' && playwright install chromium
    COMPUTER_USE_E2E=1 OPENROUTER_API_KEY=sk-or-... \
        pytest tests/e2e/test_browser_complex_e2e.py -v -s
"""

from __future__ import annotations

import functools
import http.server
import os
import socketserver
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.browser_tool import BrowserTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import AgentDefaults

pytestmark = pytest.mark.skipif(
    not (os.getenv("COMPUTER_USE_E2E") and os.getenv("OPENROUTER_API_KEY")),
    reason="set COMPUTER_USE_E2E=1 and OPENROUTER_API_KEY to run complex browser e2e tests",
)

_DEFAULT_MODELS = [
    "openai/gpt-5.1",
    "anthropic/claude-sonnet-4.5",
]
_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars
_PAGES = Path(__file__).parent / "pages"


def _models() -> list[str]:
    env = os.getenv("COMPUTER_USE_E2E_MODELS", "").strip()
    return [m.strip() for m in env.split(",") if m.strip()] or _DEFAULT_MODELS


def _attempts() -> int:
    try:
        return max(1, int(os.getenv("COMPUTER_USE_E2E_ATTEMPTS", "2")))
    except ValueError:
        return 2


def _make_provider(model: str):
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider

    provider = OpenAICompatProvider(
        api_key=os.environ["OPENROUTER_API_KEY"],
        api_base="https://openrouter.ai/api/v1",
        default_model=model,
    )
    provider.generation = SimpleNamespace(max_tokens=4096, temperature=0.0, reasoning_effort=None)
    return provider


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request stderr logging
        pass


@pytest.fixture(scope="module")
def base_url() -> str:
    handler = functools.partial(_QuietHandler, directory=str(_PAGES))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _tool(start_url: str) -> BrowserTool:
    return BrowserTool(start_url=start_url, headless=True, include_screenshot=False, max_elements=120)


async def _run(provider, tool: BrowserTool, objective: str, max_iterations: int = 24):
    tools = ToolRegistry()
    tools.register(tool)
    return await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": objective}],
        tools=tools,
        model=provider.get_default_model(),
        max_iterations=max_iterations,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))


async def _eval(tool: BrowserTool, expr: str):
    backend = await tool._get_backend()
    return await backend._page.evaluate(expr)


async def _attempt(model, start_page, objective, check, base_url, max_iterations=24):
    """Run up to N attempts; check(tool)->bool decides success. Returns bool."""
    for _ in range(_attempts()):
        tool = _tool(f"{base_url}/{start_page}")
        try:
            await _run(_make_provider(model), tool, objective, max_iterations)
            if await check(tool):
                return True
        finally:
            await tool.close()
    return False


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_multifield_form(model: str, base_url: str):
    """Fill a form with text inputs, a <select>, a radio group, and a checkbox."""
    objective = (
        "The signup form is open. Using the browser tool, complete it: set Full name to "
        "'Ada Lovelace', Email to 'ada@example.com', Country to 'United States', choose the "
        "'Pro' plan, accept the terms, then click 'Create account'."
    )

    async def check(tool):
        result = await _eval(tool, "document.getElementById('result').textContent")
        return bool(result) and all(
            s in result for s in ("Ada Lovelace", "ada@example.com", "us", "pro", "agreed")
        )

    assert await _attempt(model, "form.html", objective, check, base_url, max_iterations=28), \
        f"[{model}] form should be filled and submitted with all fields correct"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_add_to_cart_flow(model: str, base_url: str):
    """Add two specific products, navigate to the cart, verify the total."""
    objective = (
        "The shop page is already open — do NOT navigate to any URL. Start by calling the "
        "browser tool's 'snapshot' action, then add BOTH the 'Wireless Mouse' and the "
        "'Mechanical Keyboard' to the cart (not the monitor), and finally click the "
        "'View cart' link."
    )

    async def check(tool):
        items = await _eval(tool, "document.getElementById('items') ? document.getElementById('items').textContent : ''")
        total = await _eval(tool, "document.getElementById('total') ? document.getElementById('total').textContent : ''")
        return ("Wireless Mouse" in items and "Mechanical Keyboard" in items
                and "Monitor" not in items and "70" in total)

    assert await _attempt(model, "shop.html", objective, check, base_url), \
        f"[{model}] cart should contain both items with total $70"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_pick_row_among_many(model: str, base_url: str):
    """Pick the correct row out of 60 (selecting among many similar elements)."""
    objective = (
        "The list page is open. Using the browser tool, find 'Row 42' and click its 'Pick' "
        "button."
    )

    async def check(tool):
        picked = await _eval(tool, "document.getElementById('picked').textContent")
        return picked == "42"

    assert await _attempt(model, "list.html", objective, check, base_url), \
        f"[{model}] should pick Row 42"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_login_then_dashboard(model: str, base_url: str):
    """Log in (two fields + submit) and follow the redirect to the dashboard."""
    objective = (
        "The login page is open. Using the browser tool, sign in with username 'admin' and "
        "password 'secret', then submit."
    )

    async def check(tool):
        welcome = await _eval(
            tool, "document.getElementById('welcome') ? document.getElementById('welcome').textContent : ''"
        )
        return "Welcome admin" in welcome

    assert await _attempt(model, "login.html", objective, check, base_url), \
        f"[{model}] should log in and reach the dashboard"
