"""End-to-end computer_use tests: REAL vision models (via OpenRouter) driving the
REAL Playwright browser backend through the full AgentRunner loop.

These are gated and excluded from normal CI. To run:

    pip install 'nanobot-ai[computer-use]'
    playwright install chromium
    COMPUTER_USE_E2E=1 OPENROUTER_API_KEY=sk-or-... \
        pytest tests/e2e/test_computer_use_e2e.py -v -s

Model selection (must be vision + tool-calling capable on OpenRouter):
    COMPUTER_USE_E2E_MODELS="anthropic/claude-sonnet-4.5,openai/gpt-4o,google/gemini-2.5-pro"

Vision models are not deterministic, so each scenario is allowed a few attempts
(COMPUTER_USE_E2E_ATTEMPTS, default 2) and passes if any attempt succeeds.

NOTE: This harness is model-agnostic by design — every model goes through the
same OpenAI-compatible OpenRouter endpoint, and screenshots are delivered as
follow-up user messages (see runner._split_tool_result_media), so no
provider-specific code path is exercised.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.computer_use import ComputerUseTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import AgentDefaults

pytestmark = pytest.mark.skipif(
    not (os.getenv("COMPUTER_USE_E2E") and os.getenv("OPENROUTER_API_KEY")),
    reason="set COMPUTER_USE_E2E=1 and OPENROUTER_API_KEY to run computer_use e2e tests",
)

# Default to a computer-use-trained model that reliably grounds pixel
# coordinates. Pass COMPUTER_USE_E2E_MODELS to test others — but note that
# general/GUI VLMs reliably PERCEIVE the screen (test_read_screen) yet usually
# miss pixel-precise clicks (see tests/e2e/README.md "Findings").
_DEFAULT_MODELS = [
    "anthropic/claude-sonnet-4.5",
]
_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars

_TEST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>nanobot cu e2e</title>
<style>
 body{font-family:sans-serif;margin:40px;background:#fff;color:#111}
 #number{font-size:120px;font-weight:bold;color:#0a0}
 button{font-size:28px;padding:16px 32px;margin-top:24px}
 #status{font-size:32px;margin-top:24px;color:#c00}
 input{font-size:28px;padding:8px}
</style></head>
<body>
 <div id="number">42</div>
 <button id="submit" onclick="document.getElementById('status').textContent='SUBMITTED'">Submit</button>
 <div id="status">idle</div>
 <hr>
 <input id="name" placeholder="your name">
 <button id="greet" onclick="document.getElementById('greeting').textContent='HELLO '+document.getElementById('name').value">Greet</button>
 <div id="greeting"></div>
</body></html>
"""


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
    # The runner reads provider.generation for sampling params (mirrors factory).
    provider.generation = SimpleNamespace(max_tokens=2048, temperature=0.0, reasoning_effort=None)
    return provider


@pytest.fixture(scope="module")
def page_url() -> str:
    fd, path = tempfile.mkstemp(suffix=".html", prefix="nanobot_cu_")
    Path(path).write_text(_TEST_PAGE, encoding="utf-8")
    os.close(fd)
    yield f"file://{path}"
    try:
        os.unlink(path)
    except OSError:
        pass


async def _run(provider, tool: ComputerUseTool, objective: str, max_iterations: int = 12):
    tools = ToolRegistry()
    tools.register(tool)
    runner = AgentRunner(provider)
    return await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": objective}],
        tools=tools,
        model=provider.get_default_model(),
        max_iterations=max_iterations,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))


def _browser_tool(start_url: str) -> ComputerUseTool:
    return ComputerUseTool(
        backend="browser",
        target_width=1280,
        target_height=800,
        start_url=start_url,
        headless=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_read_screen(model: str, page_url: str):
    """The model must read the number rendered on the page from a screenshot."""
    attempts = _attempts()
    ok = False
    for _ in range(attempts):
        tool = _browser_tool(page_url)
        try:
            result = await _run(
                _make_provider(model),
                tool,
                "Use the computer_use tool: take a screenshot of the page and tell me "
                "the big number shown. Reply with just the number.",
            )
            if result.final_content and "42" in result.final_content:
                ok = True
                break
        finally:
            await tool.close()
    assert ok, f"[{model}] expected the model to read '42' from the screenshot"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_click_button(model: str, page_url: str):
    """The model must locate and click the Submit button (asserted via the DOM)."""
    attempts = _attempts()
    ok = False
    for _ in range(attempts):
        tool = _browser_tool(page_url)
        try:
            await _run(
                _make_provider(model),
                tool,
                "Use the computer_use tool to click the 'Submit' button on the page. "
                "Take a screenshot first to locate it.",
            )
            backend = await tool._get_backend()
            status = await backend._page.evaluate("document.getElementById('status').textContent")
            if status == "SUBMITTED":
                ok = True
                break
        finally:
            await tool.close()
    assert ok, f"[{model}] expected #status to become 'SUBMITTED' after clicking Submit"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", _models())
async def test_type_and_submit(model: str, page_url: str):
    """The model must type into a field and click a button (multi-step)."""
    attempts = _attempts()
    ok = False
    for _ in range(attempts):
        tool = _browser_tool(page_url)
        try:
            await _run(
                _make_provider(model),
                tool,
                "Use the computer_use tool: click the name input, type 'Ada', then click "
                "the 'Greet' button. Take screenshots to guide yourself.",
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
    assert ok, f"[{model}] expected greeting to contain the typed name"
