"""Tests for the sendProgress prompt gate.

``sendProgress`` gates delivery of progress text, but the text itself only exists
if the model writes it on the tool-calling assistant message -- and
``tool_contract.md`` tells the model to leave that message empty. So the switch
must also authorize the note, and it must do so on exactly the same value the
delivery gate reads. If the two ever disagree the user gets silence from a
switch that reads as on, which is the bug these tests exist to prevent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.channels.config_bools import channels_config_resolve_bool
from nanobot.config.schema import ChannelsConfig

PROGRESS_HEADING = "## Progress Notes"
TOOL_CONTRACT_ANSWER_RULE = "- Wait for tool results before writing the final answer."


@pytest.fixture
def builder(tmp_path: Path) -> ContextBuilder:
    return ContextBuilder(tmp_path)


class TestPromptGate:
    def test_section_absent_by_default(self, builder: ContextBuilder) -> None:
        prompt = builder.build_system_prompt(channel="qq")
        assert PROGRESS_HEADING not in prompt

    def test_section_present_when_enabled(self, builder: ContextBuilder) -> None:
        prompt = builder.build_system_prompt(channel="qq", progress_notes=True)
        assert PROGRESS_HEADING in prompt

    def test_enabling_leaves_tool_contract_rule_intact(
        self, builder: ContextBuilder
    ) -> None:
        """The answer rule is unchanged; this change only adds a note rule."""
        off = builder.build_system_prompt(channel="qq")
        on = builder.build_system_prompt(channel="qq", progress_notes=True)
        assert TOOL_CONTRACT_ANSWER_RULE in off
        assert TOOL_CONTRACT_ANSWER_RULE in on

    def test_enabling_only_appends(self, builder: ContextBuilder) -> None:
        """Enabling must not perturb or reorder the prompt the model already sees."""
        off = builder.build_system_prompt(channel="qq")
        on = builder.build_system_prompt(channel="qq", progress_notes=True)
        before, marker, after = on.partition(PROGRESS_HEADING)
        assert marker, "section should be present when enabled"
        # The whole existing prompt survives unchanged, and the new section is
        # the tail. Nothing existing is rewritten or reordered.
        assert before == off + "\n\n---\n\n"
        assert after.strip()
        assert PROGRESS_HEADING not in off

    def test_transcript_gate_propagates(self, builder: ContextBuilder) -> None:
        """The build_transcript path used by the runner honors the flag."""
        from nanobot.agent.context import TranscriptInput

        transcript = TranscriptInput(history=[], current_message="hi")
        off = builder.build_transcript(transcript, channel="qq")
        on = builder.build_transcript(transcript, channel="qq", progress_notes=True)
        assert PROGRESS_HEADING not in off[0]["content"]
        assert PROGRESS_HEADING in on[0]["content"]


class TestGateResolution:
    """The loop's gate must match the ChannelManager delivery gate."""

    @staticmethod
    def _probe(config: Any) -> Any:
        class Probe:
            _progress_notes_enabled = AgentLoop._progress_notes_enabled

        probe = Probe()
        probe.channels_config = config
        return probe

    def test_no_config_is_off(self) -> None:
        """SDK / CLI / test turns have no channel config; stay quiet."""
        assert self._probe(None)._progress_notes_enabled("qq") is False

    def test_default_is_off(self) -> None:
        assert self._probe(ChannelsConfig())._progress_notes_enabled("qq") is False

    def test_global_enable(self) -> None:
        config = ChannelsConfig(send_progress=True)
        assert self._probe(config)._progress_notes_enabled("qq") is True

    @pytest.mark.parametrize("key", ["send_progress", "sendProgress"])
    def test_per_channel_enable(self, key: str) -> None:
        config = ChannelsConfig(**{"qq": {key: True}})
        assert self._probe(config)._progress_notes_enabled("qq") is True

    @pytest.mark.parametrize("key", ["send_progress", "sendProgress"])
    def test_per_channel_overrides_global(self, key: str) -> None:
        config = ChannelsConfig(send_progress=True, **{"qq": {key: False}})
        assert self._probe(config)._progress_notes_enabled("qq") is False

    def test_per_channel_enable_over_global_disable(self) -> None:
        config = ChannelsConfig(send_progress=False, **{"qq": {"sendProgress": True}})
        assert self._probe(config)._progress_notes_enabled("qq") is True

    def test_non_bool_falls_through_to_global(self) -> None:
        """A malformed per-channel value must not silently enable or crash."""
        config = ChannelsConfig(send_progress=True, **{"qq": {"sendProgress": "yes"}})
        assert self._probe(config)._progress_notes_enabled("qq") is True

    def test_unknown_channel_uses_global(self) -> None:
        config = ChannelsConfig(send_progress=True)
        assert self._probe(config)._progress_notes_enabled("nope") is True

    def test_missing_channel_is_off(self) -> None:
        """No channel means no delivery target; do not spend prompt on it."""
        config = ChannelsConfig(send_progress=True)
        assert self._probe(config)._progress_notes_enabled(None) is False

    def test_gate_matches_delivery_for_every_case(self) -> None:
        """Generation and delivery must agree -- divergence is the #705 class."""
        cases = [
            ChannelsConfig(),
            ChannelsConfig(send_progress=True),
            ChannelsConfig(send_progress=True, **{"qq": {"sendProgress": False}}),
            ChannelsConfig(send_progress=False, **{"qq": {"sendProgress": True}}),
        ]
        for config in cases:
            section = dict(getattr(config, "model_extra", None) or {}).get("qq") or {}
            delivered = channels_config_resolve_bool(section, "send_progress")
            if delivered is None:
                delivered = channels_config_resolve_bool(config, "send_progress")
            delivered = bool(delivered)
            generated = self._probe(config)._progress_notes_enabled("qq")
            assert generated is delivered


class TestSharedResolver:
    """The extracted resolver keeps both call sites on one implementation."""

    def test_model_extra_and_dict_agree(self) -> None:
        config = ChannelsConfig(send_progress=True)
        as_dict = {"send_progress": True}
        assert channels_config_resolve_bool(config, "send_progress") is True
        assert channels_config_resolve_bool(as_dict, "send_progress") is True

    def test_absent_key_returns_none_not_default(self) -> None:
        """Callers layer this under a per-channel value, so None must survive."""
        assert channels_config_resolve_bool({}, "send_progress") is None
        assert channels_config_resolve_bool(None, "send_progress") is None

    def test_non_bool_is_not_treated_as_set(self) -> None:
        assert channels_config_resolve_bool({"sendProgress": 1}, "send_progress") is None
