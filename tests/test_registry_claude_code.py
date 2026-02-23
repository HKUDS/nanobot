from nanobot.providers.registry import find_by_name


def test_claude_code_in_registry():
    spec = find_by_name("claude_code")
    assert spec is not None
    assert spec.is_oauth is True
    assert spec.is_direct is True
    assert spec.env_key == "CLAUDE_CODE_OAUTH_TOKEN"
    assert spec.display_name == "Claude Code CLI"
