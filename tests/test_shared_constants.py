def test_provider_and_direct_share_constants():
    """Ensure ClaudeCodeProvider uses the same constants as claude_direct."""
    from nanobot.api.claude_direct import (
        ANTHROPIC_API_URL,
        CLAUDE_CODE_HEADERS,
        CLAUDE_CODE_SYSTEM_PREFIX,
    )
    from nanobot.providers.claude_code_provider import (
        ANTHROPIC_API_URL as PROVIDER_URL,
        CLAUDE_CODE_HEADERS as PROVIDER_HEADERS,
        CLAUDE_CODE_SYSTEM_PREFIX as PROVIDER_PREFIX,
    )

    assert PROVIDER_URL is ANTHROPIC_API_URL
    assert PROVIDER_HEADERS is CLAUDE_CODE_HEADERS
    assert PROVIDER_PREFIX is CLAUDE_CODE_SYSTEM_PREFIX
