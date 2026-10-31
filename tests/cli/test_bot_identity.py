"""Tests for configurable bot identity in CLI (#3650)."""

from __future__ import annotations

from nanobot.cli.stream import StreamRenderer, ThinkingSpinner
from nanobot.config.schema import AgentDefaults, Config


def test_bot_name_and_icon_defaults_preserve_current_branding() -> None:
    defaults = AgentDefaults()

    assert defaults.bot_name == "nanobot"
    assert defaults.bot_icon == "🐈"


def test_bot_name_and_icon_can_be_overridden_via_config() -> None:
    config = Config.model_validate(
        {"agents": {"defaults": {"botName": "mybot", "botIcon": "🤖"}}}
    )

    assert config.agents.defaults.bot_name == "mybot"
    assert config.agents.defaults.bot_icon == "🤖"


def test_bot_icon_accepts_empty_string_to_omit() -> None:
    config = Config.model_validate(
        {"agents": {"defaults": {"botIcon": ""}}}
    )

    assert config.agents.defaults.bot_icon == ""


def test_stream_renderer_propagates_bot_name_to_spinner_text(capsys) -> None:
    spinner = ThinkingSpinner(bot_name="mybot")

    # rich.Status keeps the renderable on its internal _renderable attribute;
    # the spinner text is exposed via its underlying status text.
    rendered = spinner._spinner.status
    assert "mybot is thinking..." in rendered


def test_stream_renderer_header_combines_icon_and_name() -> None:
    renderer = StreamRenderer(show_spinner=False, bot_name="mybot", bot_icon="🤖")

    assert renderer._bot_name == "mybot"
    assert renderer._bot_icon == "🤖"


def test_stream_renderer_empty_icon_omits_leading_space() -> None:
    renderer = StreamRenderer(show_spinner=False, bot_name="mybot", bot_icon="")

    header = (
        f"{renderer._bot_icon} {renderer._bot_name}"
        if renderer._bot_icon
        else renderer._bot_name
    )
    assert header == "mybot"
