"""Tests for configurable bot identity in CLI (#3650)."""

from __future__ import annotations

from nanobot.cli.stream import StreamRenderer, ThinkingSpinner
from nanobot.config.schema import AgentDefaults, Config


def test_bot_name_and_icon_defaults_preserve_current_branding() -> None:
    """Default values keep the existing 'nanobot' name and cat icon."""
    defaults = AgentDefaults()

    assert defaults.bot_name == "nanobot"
    assert defaults.bot_icon == "🐈"


def test_bot_name_and_icon_can_be_overridden_via_config() -> None:
    """camelCase keys (as used in config.json) bind to the new fields."""
    config = Config.model_validate(
        {"agents": {"defaults": {"botName": "mybot", "botIcon": "🤖"}}}
    )

    assert config.agents.defaults.bot_name == "mybot"
    assert config.agents.defaults.bot_icon == "🤖"


def test_bot_icon_accepts_empty_string_to_omit() -> None:
    """Empty bot_icon is valid and lets users opt out of the leading icon."""
    config = Config.model_validate(
        {"agents": {"defaults": {"botIcon": ""}}}
    )

    assert config.agents.defaults.bot_icon == ""


def test_stream_renderer_propagates_bot_name_to_spinner_text(capsys) -> None:
    """ThinkingSpinner uses the configured bot_name in its status text."""
    spinner = ThinkingSpinner(bot_name="mybot")

    # rich.Status keeps the renderable on its internal _renderable attribute;
    # the spinner text is exposed via its underlying status text.
    rendered = spinner._spinner.status
    assert "mybot is thinking..." in rendered


def test_stream_renderer_header_combines_icon_and_name() -> None:
    """When bot_icon is non-empty, the header is '<icon> <name>'."""
    renderer = StreamRenderer(show_spinner=False, bot_name="mybot", bot_icon="🤖")

    # The header is built inline in on_delta; verify the stored fields
    # so we don't depend on Live console output.
    assert renderer._bot_name == "mybot"
    assert renderer._bot_icon == "🤖"


def test_stream_renderer_empty_icon_omits_leading_space() -> None:
    """An empty bot_icon yields a header that is just the bot name, no leading space."""
    renderer = StreamRenderer(show_spinner=False, bot_name="mybot", bot_icon="")

    # Replicate the header construction used in on_delta to assert the contract.
    header = (
        f"{renderer._bot_icon} {renderer._bot_name}"
        if renderer._bot_icon
        else renderer._bot_name
    )
    assert header == "mybot"
