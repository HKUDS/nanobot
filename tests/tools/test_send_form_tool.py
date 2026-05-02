"""Tests for the ``send_form`` tool — registered template dispatch."""

import pytest

from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.send_form import SendFormTool
from nanobot.bus.events import OutboundMessage
from nanobot.config.schema import FormInputConfig, FormTemplateConfig


def _checkin_template() -> FormTemplateConfig:
    return FormTemplateConfig(
        id="checkin-v1",
        title="Check-in",
        button_label="📝 Check-in",
        inputs=[
            FormInputConfig(type="text", custom_id="sleep", label="Sleep"),
            FormInputConfig(
                type="radio",
                custom_id="energy",
                label="Energy",
                options=[
                    {"label": "1", "value": "1"},
                    {"label": "2", "value": "2"},
                    {"label": "3", "value": "3"},
                ],
            ),
        ],
    )


def _niggle_template() -> FormTemplateConfig:
    return FormTemplateConfig(
        id="niggle-v1",
        title="Niggle",
        button_style="secondary",
        inputs=[
            FormInputConfig(type="text", custom_id="location", label="Where"),
            FormInputConfig(
                type="radio",
                custom_id="severity",
                label="Severity",
                options=[
                    {"label": "1", "value": "1"},
                    {"label": "5", "value": "5"},
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_send_form_dispatches_template_as_button_with_modal() -> None:
    """The synthesized buttons payload mirrors what the model used to author by hand."""
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    message_tool = MessageTool(send_callback=_send)
    tool = SendFormTool(message_tool=message_tool, templates=[_checkin_template()])

    result = await tool.execute(
        content="Morning brief…",
        forms=["checkin-v1"],
        channel="discord",
        chat_id="user:1",
    )

    assert "Error" not in (result or "")
    assert len(sent) == 1
    components = sent[0].metadata["_components"]
    assert len(components) == 1  # one row
    row = components[0]
    assert len(row) == 1
    button = row[0]
    assert button["type"] == "button"
    assert button["custom_id"] == "checkin-v1"
    assert button["label"] == "📝 Check-in"
    assert button["modal"]["title"] == "Check-in"
    inputs = button["modal"]["inputs"]
    assert inputs[0]["custom_id"] == "sleep" and inputs[0]["type"] == "text"
    assert inputs[1]["custom_id"] == "energy" and inputs[1]["type"] == "radio"
    assert len(inputs[1]["options"]) == 3


@pytest.mark.asyncio
async def test_send_form_attaches_multiple_templates_in_one_row() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = SendFormTool(
        message_tool=MessageTool(send_callback=_send),
        templates=[_checkin_template(), _niggle_template()],
    )

    await tool.execute(
        content="Morning",
        forms=["checkin-v1", "niggle-v1"],
        channel="discord",
        chat_id="user:1",
    )

    row = sent[0].metadata["_components"][0]
    assert [b["custom_id"] for b in row] == ["checkin-v1", "niggle-v1"]
    assert [b["style"] for b in row] == ["primary", "secondary"]


@pytest.mark.asyncio
async def test_send_form_rejects_unknown_template_id() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = SendFormTool(
        message_tool=MessageTool(send_callback=_send),
        templates=[_checkin_template()],
    )

    result = await tool.execute(
        content="hi",
        forms=["nope-v1"],
        channel="discord",
        chat_id="user:1",
    )

    assert "unknown form template id(s): nope-v1" in result
    assert sent == []


@pytest.mark.asyncio
async def test_send_form_requires_non_empty_content_and_forms() -> None:
    tool = SendFormTool(
        message_tool=MessageTool(),
        templates=[_checkin_template()],
    )

    assert "non-empty list" in await tool.execute(content="hi", forms=[])
    assert "required" in await tool.execute(content="   ", forms=["checkin-v1"])


@pytest.mark.asyncio
async def test_send_form_caps_at_five_forms_per_message() -> None:
    """Discord allows max 5 buttons in one action row."""
    tpl = _checkin_template()
    tool = SendFormTool(
        message_tool=MessageTool(),
        templates=[tpl],
    )

    result = await tool.execute(
        content="x",
        forms=["checkin-v1"] * 6,
        channel="discord",
        chat_id="user:1",
    )
    assert "max 5" in result


@pytest.mark.asyncio
async def test_send_form_description_lists_template_ids() -> None:
    tool = SendFormTool(
        message_tool=MessageTool(),
        templates=[_checkin_template(), _niggle_template()],
    )
    desc = tool.description
    assert "checkin-v1" in desc
    assert "niggle-v1" in desc


@pytest.mark.asyncio
async def test_send_form_no_templates_registered_emits_helpful_error() -> None:
    tool = SendFormTool(message_tool=MessageTool(), templates=[])
    result = await tool.execute(content="hi", forms=["x"], channel="discord", chat_id="user:1")
    assert "no templates registered" in result.lower()
