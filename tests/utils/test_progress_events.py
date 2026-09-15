from types import SimpleNamespace

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.tools.base import ToolResult
from nanobot.utils.progress_events import build_tool_event_finish_payloads


def test_tool_progress_keeps_structured_data_separate_from_result_text() -> None:
    data = {
        "kind": "mcp_app_result",
        "result": {"structuredContent": {"rows": [1]}},
    }
    context = AgentHookContext(
        iteration=1,
        messages=[],
        tool_calls=[SimpleNamespace(id="call-1", name="mcp_test_demo", arguments={})],
        tool_results=[ToolResult("model summary", data=data)],
        tool_events=[{"status": "ok"}],
    )

    [payload] = build_tool_event_finish_payloads(context)

    assert payload["result"] == "model summary"
    assert payload["data"] == data
