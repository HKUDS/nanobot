from pathlib import Path

from nanobot.agent.context import ContextBuilder


def test_system_prompt_marks_enabled_and_always_skills_explicitly(tmp_path: Path) -> None:
    builder = ContextBuilder(tmp_path)

    prompt = builder.build_system_prompt(
        session_metadata={
            "assistant": {
                "enabled_skills": ["weather"],
            }
        }
    )

    assert "# Skill Activation State" in prompt
    assert "- Always-loaded skills: memory" in prompt
    assert "- Enabled for this agent: weather" in prompt
    assert '<skill enabled="false" always="true" ' in prompt
    assert "<name>memory</name>" in prompt
    assert '<skill enabled="true" always="false" ' in prompt
    assert "<name>weather</name>" in prompt
    assert "runtime_available=" in prompt
    assert "<name>github</name>" not in prompt


def test_system_prompt_does_not_fall_back_to_all_skills_when_enabled_list_is_empty(tmp_path: Path) -> None:
    builder = ContextBuilder(tmp_path)

    prompt = builder.build_system_prompt(
        session_metadata={
            "assistant": {
                "enabled_skills": [],
            }
        }
    )

    assert "# Skill Activation State" in prompt
    assert "- Always-loaded skills: memory" in prompt
    assert "- Enabled for this agent: none" in prompt
    assert "<name>memory</name>" in prompt
    assert "<name>weather</name>" not in prompt
    assert "<name>github</name>" not in prompt
