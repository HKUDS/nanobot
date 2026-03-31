from __future__ import annotations

import pytest

from nanobot.agent.tools.ask_question import AskQuestionTool


@pytest.mark.asyncio
async def test_ask_question_renders_structured_prompt() -> None:
    tool = AskQuestionTool()
    result = await tool.execute(
        title="Need clarification",
        questions=[
            {
                "id": "q1",
                "prompt": "Choose environment",
                "options": [
                    {"id": "prod", "label": "Production"},
                    {"id": "stage", "label": "Staging"},
                ],
            },
            {
                "id": "q2",
                "prompt": "Pick channels",
                "allow_multiple": True,
                "options": [
                    {"id": "tg", "label": "Telegram"},
                    {"id": "dc", "label": "Discord"},
                ],
            },
        ],
    )

    assert "Need clarification" in result
    assert "Q1 (q1) [single]" in result
    assert "- prod: Production" in result
    assert "Q2 (q2) [multiple]" in result
    assert "Format example: q1=a,q2=b|c" in result


@pytest.mark.asyncio
async def test_ask_question_rejects_invalid_option_set() -> None:
    tool = AskQuestionTool()
    result = await tool.execute(
        questions=[
            {
                "id": "q1",
                "prompt": "Bad question",
                "options": [{"id": "only", "label": "Only one"}],
            }
        ]
    )

    assert "at least 2 options" in result
