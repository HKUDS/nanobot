from __future__ import annotations

import asyncio
import json

from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.x_search import XSearchConfig, XSearchTool, _build_x_search_body
from nanobot.config.schema import ToolsConfig


def test_x_search_body_maps_filters_to_server_side_tool() -> None:
    body = _build_x_search_body(
        model="grok-4.3",
        query="what are people saying about nanobot",
        allowed_x_handles=["@xai", " nousresearch "],
        from_date="2026-05-01",
        enable_image_understanding=True,
    )

    assert body["model"] == "grok-4.3"
    assert body["input"] == [{"role": "user", "content": "what are people saying about nanobot"}]
    assert body["tools"] == [
        {
            "type": "x_search",
            "allowed_x_handles": ["xai", "nousresearch"],
            "from_date": "2026-05-01",
            "enable_image_understanding": True,
        }
    ]


def test_x_search_tool_is_hidden_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr("nanobot.agent.tools.x_search.load_xai_oauth_credential", lambda: None)

    ctx = ToolContext(config=ToolsConfig(), workspace=".")

    assert XSearchTool.enabled(ctx) is False


def test_x_search_tool_is_visible_with_oauth_credentials(monkeypatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr("nanobot.agent.tools.x_search.load_xai_oauth_credential", lambda: object())

    ctx = ToolContext(config=ToolsConfig(), workspace=".")

    assert XSearchTool.enabled(ctx) is True


def test_x_search_execute_returns_answer_and_citations(monkeypatch) -> None:
    async def run() -> None:
        result = json.loads(await tool.execute("nanobot"))

        assert result["success"] is True
        assert result["credential_source"] == "xai"
        assert result["answer"] == "People are discussing nanobot."
        assert result["citations"] == ["https://x.com/example/status/1"]
        assert result["inline_citations"][0]["url"] == "https://x.com/example/status/1"

    tool = XSearchTool(config=XSearchConfig(api_key="api-key", retries=0))

    async def fake_post(bearer, body, config):
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "People are discussing nanobot.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://x.com/example/status/1",
                                    "title": "Example post",
                                    "start_index": 0,
                                    "end_index": 6,
                                }
                            ],
                        }
                    ],
                }
            ],
            "citations": ["https://x.com/example/status/1"],
            "status": "completed",
        }

    monkeypatch.setattr("nanobot.agent.tools.x_search._post_x_search", fake_post)

    asyncio.run(run())
