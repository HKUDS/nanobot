"""Tests for the configurable classifier prompt / rubric."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


def _make_loop(model_router_overrides: dict | None = None):
    """Create a minimal AgentLoop with mocked deps, returning (loop, router_config)."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ModelRouterConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    router = ModelRouterConfig(**(model_router_overrides or {}))

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace,
                         model_router=router)
    return loop, router


def test_classify_tool_uses_built_in_defaults_when_unconfigured() -> None:
    loop, _ = _make_loop()
    tool = loop._build_classify_tool()
    desc = tool[0]["function"]["parameters"]["properties"]["complexity"]["description"]
    assert "greeting" in desc          # from default simple_description
    assert "tool use" in desc          # from default complex_description


def test_classify_tool_uses_custom_descriptions_when_configured() -> None:
    loop, _ = _make_loop({
        "simple_description": "short, cheap, banal",
        "complex_description": "needs deep thought",
    })
    tool = loop._build_classify_tool()
    desc = tool[0]["function"]["parameters"]["properties"]["complexity"]["description"]
    assert "simple = short, cheap, banal" in desc
    assert "complex = needs deep thought" in desc
    # Built-in defaults should not leak through when overridden.
    assert "greeting" not in desc
    assert "tool use" not in desc


def test_custom_simple_description_only_keeps_default_complex() -> None:
    loop, _ = _make_loop({"simple_description": "only my simple def"})
    tool = loop._build_classify_tool()
    desc = tool[0]["function"]["parameters"]["properties"]["complexity"]["description"]
    assert "only my simple def" in desc
    assert "tool use" in desc  # complex still default


def test_classifier_system_prompt_default_used_when_unconfigured() -> None:
    loop, _ = _make_loop()
    assert "Classify the user's message" in loop._DEFAULT_CLASSIFIER_SYSTEM_PROMPT
    # When config is blank, the loop should resolve to this default.
    assert loop.model_router.classifier_system_prompt == ""


def test_classifier_system_prompt_can_be_overridden() -> None:
    custom = "You are a triage bot. Be ruthless."
    loop, _ = _make_loop({"classifier_system_prompt": custom})
    assert loop.model_router.classifier_system_prompt == custom
