"""End-to-end DOM-browser tests: models that FAIL pixel-based clicking succeed
here because they act by element ref instead of by pixel coordinates.

This is the model-agnostic action path. ``include_screenshot=False`` below proves
it needs no vision at all — the model acts purely on the text element list.

Run:
    pip install 'nanobot-ai[computer-use]' && playwright install chromium
    COMPUTER_USE_E2E=1 OPENROUTER_API_KEY=sk-or-... \
        pytest tests/e2e/test_browser_dom_e2e.py -v -s

Default models are ones that failed pixel clicking (see test_computer_use_e2e
"Findings") to demonstrate the DOM mode fixes them. Override with
COMPUTER_USE_E2E_MODELS.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.browser_tool import BrowserTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import AgentDefaults

pytestmark = pytest.mark.skipif(
    not (os.getenv("COMPUTER_USE_E2E") and os.getenv("OPENROUTER_API_KEY")),
    reason="set COMPUTER_USE_E2E=1 and OPENROUTER_API_KEY to run browser DOM e2e tests",
)

# Default to models that FAILED pixel clicking — DOM mode should fix them.
_DEFAULT_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-2.5-pro",
]
_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars

_TEST_PAGE = """<!doctype html><html><head><meta charset=utf-8><title>dom e2e</title></head>
<body>
 <div id=number style="font-size:80px">42</div>
 <button id=submit onclick="document.getElementById('status').textContent='SUBMITTED'">Submit</button>
 <div id=status>idle</div>
 <input id=name placeholder="your name">
 <button id=greet onclick="document.getElementById('greeting').textContent='HELLO '+document.getElementById('name').value">Greet</button>
 <div id=greeting></div>
</body></html>"""


def _models() -> list[str]:
    env = os.getenv("COMPUTER_USE_E2E_MODELS", "").strip()
    return [m.strip() for m in env.split(",") if m.strip()] or _DEFAULT_MODELS


def _make_provider(model: str):
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider

    provider = OpenAICompatProvider(
        api_key=os.environ["OPENROUTER_API_KEY"],
        api_base="https://openrouter.ai/api/v1",
        default_model=model,
    )
    provider.generation = SimpleNamespace(max_tokens=2048, temperature=0.0, reasoning_effort=None)
    return provider


@pytest.fixture(scope="module")
def page_url() -> str:
    fd, path = tempfile.mkstemp(suffix=".html", prefix="nanobot_dom_")
    Path(path).write_text(_TEST_PAGE, encoding="utf-8")
    os.close(fd)
    yield f"file://{path}"
    try:
        os.unlink(path)
    except OSError:
        pass


def _tool(start_url: str) -> BrowserTool:
    # No screenshot — pure DOM, to prove vision is not required.
    return BrowserTool(start_url=start_url, headless=True, include_screenshot=False)


async def _run(provider, tool: BrowserTool, objective: str, max_iterations: int = 12):
    tools = ToolRegistry()
    tools.register(tool)
    return await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": objective}],
        tools=tools,
        model=provider.get_default_model(),
        max_iterations=max_iterations,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_dom_click_button(model: str, page_url: str):
    attempts = max(1, int(os.getenv("COMPUTER_USE_E2E_ATTEMPTS", "2")))
    ok = False
    for _ in range(attempts):
        tool = _tool(page_url)
        try:
            await _run(
                _make_provider(model),
                tool,
                "The page is already open. Use the browser tool (start with action=snapshot) "
                "to find and click the 'Submit' button.",
            )
            backend = await tool._get_backend()
            status = await backend._page.evaluate("document.getElementById('status').textContent")
            if status == "SUBMITTED":
                ok = True
                break
        finally:
            await tool.close()
    assert ok, f"[{model}] DOM click should set #status to SUBMITTED"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_dom_type_and_submit(model: str, page_url: str):
    attempts = max(1, int(os.getenv("COMPUTER_USE_E2E_ATTEMPTS", "2")))
    ok = False
    for _ in range(attempts):
        tool = _tool(page_url)
        try:
            await _run(
                _make_provider(model),
                tool,
                "The page is already open. Use the browser tool: snapshot the page, type "
                "'Ada' into the name input, then click the 'Greet' button.",
                max_iterations=16,
            )
            backend = await tool._get_backend()
            greeting = await backend._page.evaluate(
                "document.getElementById('greeting').textContent"
            )
            if greeting and "ADA" in greeting.upper():
                ok = True
                break
        finally:
            await tool.close()
    assert ok, f"[{model}] DOM type+greet should produce a greeting with the typed name"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_dom_read_text_no_vision(model: str, page_url: str):
    """Pure text path: the model reads the page via read_text (no screenshot at all)."""
    attempts = max(1, int(os.getenv("COMPUTER_USE_E2E_ATTEMPTS", "2")))
    ok = False
    for _ in range(attempts):
        tool = _tool(page_url)
        try:
            result = await _run(
                _make_provider(model),
                tool,
                "Use the browser tool's read_text action to read the page, then tell me the "
                "number shown. Reply with just the number.",
            )
            if result.final_content and "42" in result.final_content:
                ok = True
                break
        finally:
            await tool.close()
    assert ok, f"[{model}] should read '42' via read_text (no vision)"
