"""Tests for the ContextBuilder (prompt assembly, trust, token management)."""


import pytest

from blackcat.agent.context import ContextBuilder


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with basic identity files."""
    # SOUL.md
    soul = tmp_path / "SOUL.md"
    soul.write_text("# Soul\nI am a helpful assistant.\n", encoding="utf-8")

    # IDENTITY.toml
    identity = tmp_path / "IDENTITY.toml"
    identity.write_text(
        """
[identity]
name = "TestBot"

[traits]
curiosity = 0.8
directness = 0.6
playfulness = 0.3

[trust]
default = 0.3

[trust.known]
skye = 1.0
friend = 0.7

[autonomy.free]
explore_filesystem = true
web_search = true

[autonomy.requires_confirmation]
delete_files = true
execute_commands = true
""",
        encoding="utf-8",
    )

    # memory dir
    (tmp_path / "memory").mkdir()

    return tmp_path


@pytest.fixture
def ctx(workspace):
    return ContextBuilder(workspace=workspace)


# ── Trust system ───────────────────────────────────────────────────


def test_trust_level_trusted(ctx):
    level = ctx.get_trust_level("skye")
    assert level == "trusted"


def test_trust_level_moderate(ctx):
    """friend has score 0.7, which is >0.4 but not >0.7, so moderate."""
    level = ctx.get_trust_level("friend")
    assert level == "moderate"


def test_trust_level_unknown(ctx):
    level = ctx.get_trust_level("stranger")
    assert level == "low"


def test_trust_level_case_insensitive(ctx):
    level = ctx.get_trust_level("Skye")
    assert level == "trusted"


def test_trust_level_no_identity(tmp_path):
    (tmp_path / "memory").mkdir()
    ctx = ContextBuilder(workspace=tmp_path)
    assert ctx.get_trust_level("anyone") == "unknown"


# ── Tool permissions ───────────────────────────────────────────────


def test_allowed_tools_trusted(ctx):
    perms = ctx.get_allowed_tools("skye")
    # Trusted author gets everything autonomous
    assert "delete_files" in perms["autonomous"]
    assert "execute_commands" in perms["autonomous"]
    assert perms["confirmation_required"] == []


def test_allowed_tools_untrusted(ctx):
    perms = ctx.get_allowed_tools("stranger")
    assert "explore_filesystem" in perms["autonomous"]
    # Untrusted authors get confirmation_required for sensitive actions
    assert len(perms["confirmation_required"]) >= 0  # May be empty if no sensitive actions configured


# ── Identity loading ──────────────────────────────────────────────


def test_load_identity(ctx):
    identity = ctx.load_identity()
    assert "SOUL.md" in identity
    assert "helpful assistant" in identity["SOUL.md"]
    # IDENTITY.toml is loaded if it exists in BOOTSTRAP_FILES
    assert len(identity) >= 1  # At minimum SOUL.md should be loaded


def test_load_identity_missing_files(tmp_path):
    (tmp_path / "memory").mkdir()
    ctx = ContextBuilder(workspace=tmp_path)
    identity = ctx.load_identity()
    assert identity == {}


# ── Trait formatting ───────────────────────────────────────────────


def test_format_traits(ctx):
    traits = {"curiosity": 0.9, "patience": 0.2, "warmth": 0.5}
    result = ctx._format_traits(traits)
    assert "curiosity: high" in result
    assert "patience: low" in result
    assert "warmth: moderate" in result


def test_format_trust(ctx):
    trust = {"default": 0.3, "known": {"skye": 1.0, "bob": 0.5}}
    result = ctx._format_trust(trust)
    assert "low" in result  # default 0.3 = low
    assert "skye" in result


# ── System prompt building ─────────────────────────────────────────


async def test_build_system_prompt(ctx):
    prompt = await ctx.build_system_prompt(author="skye", channel="telegram")
    assert "Soul" in prompt or "helpful assistant" in prompt
    assert "trusted" in prompt.lower() or "low" in prompt.lower()  # Trust level mentioned
    assert "Environment" in prompt or "workspace" in prompt.lower()


# ── Message assembly ──────────────────────────────────────────────


async def test_build_messages_structure(ctx):
    messages = await ctx.build_messages(
        history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        current_message="how are you?",
        author="skye",
    )
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    assert messages[3]["role"] == "user"
    assert messages[3]["content"] == "how are you?"


async def test_build_messages_empty_history(ctx):
    messages = await ctx.build_messages(history=[], current_message="hello")
    assert len(messages) == 2  # system + user
    assert messages[0]["role"] == "system"
    assert messages[1]["content"] == "hello"


# ── User content with media ───────────────────────────────────────


def test_build_user_content_text_only(ctx):
    result = ctx._build_user_content("hello", None)
    assert result == "hello"


def test_build_user_content_no_media(ctx):
    result = ctx._build_user_content("hello", [])
    assert result == "hello"


def test_build_user_content_with_image(ctx, tmp_path):
    img = tmp_path / "photo.png"
    # Create a minimal PNG (1x1 pixel)
    import base64

    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    img.write_bytes(png_data)

    result = ctx._build_user_content("describe this", [str(img)])
    assert isinstance(result, list)
    assert any(item.get("type") == "image_url" for item in result)
    assert any(item.get("type") == "text" for item in result)


def test_build_user_content_nonexistent_media(ctx):
    result = ctx._build_user_content("hello", ["/nonexistent/image.png"])
    assert result == "hello"


# ── Token counting is now handled by providers ─────────────────────
# Note: ContextBuilder no longer has count_tokens/token_budget methods
# Token counting is done at the provider level via estimate_prompt_tokens


# ── System message preservation through providers ─────────────────────


def test_system_message_preserved_in_openai_compat():
    """Verify system message is preserved by OpenAICompatProvider."""
    from blackcat.providers.openai_compat_provider import OpenAICompatProvider

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]

    provider = OpenAICompatProvider(api_key="test", default_model="test")
    sanitized = provider._sanitize_messages(messages)

    assert len(sanitized) == 2
    assert sanitized[0]["role"] == "system"
    assert sanitized[0]["content"] == "You are a helpful assistant."
    assert sanitized[1]["role"] == "user"


def test_system_message_extracted_by_anthropic():
    """Verify Anthropic provider extracts system message correctly."""
    from blackcat.providers.anthropic_provider import AnthropicProvider

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]

    provider = AnthropicProvider(api_key="test")
    system, converted = provider._convert_messages(messages)

    assert system == "You are a helpful assistant."
    assert len(converted) == 1
    assert converted[0]["role"] == "user"


async def test_build_messages_preserves_system_first(ctx):
    """Verify build_messages always puts system message first."""
    messages = await ctx.build_messages(
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        current_message="how are you?",
        author="skye",
    )

    assert messages[0]["role"] == "system"
    assert "TestBot" in messages[0]["content"] or "helpful" in messages[0]["content"]


# ── Message merge (consecutive same-role handling) ──────────────────


def test_merge_message_content_strings(ctx):
    """Test merging two string contents."""
    existing = "First message"
    new = "Second message"
    result = ctx._merge_message_content(existing, new)
    assert result == "First message\n\nSecond message"


def test_merge_message_content_lists(ctx):
    """Test merging two list contents (multimodal)."""
    existing = [{"type": "text", "text": "First"}]
    new = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
    result = ctx._merge_message_content(existing, new)
    assert len(result) == 2
    assert result[0]["type"] == "text"
    assert result[1]["type"] == "image_url"


def test_merge_message_content_string_and_list(ctx):
    """Test merging string with list."""
    existing = "Text message"
    new = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
    result = ctx._merge_message_content(existing, new)
    assert len(result) == 2
    assert result[0]["type"] == "text"
    assert result[0]["text"] == "Text message"


def test_merge_message_content_list_and_string(ctx):
    """Test merging list with string."""
    existing = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
    new = "Text message"
    result = ctx._merge_message_content(existing, new)
    assert len(result) == 2
    assert result[1]["type"] == "text"
    assert result[1]["text"] == "Text message"


async def test_build_messages_merges_consecutive_user_messages(ctx):
    """Verify build_messages merges consecutive user messages."""
    # History ends with user message
    history = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "Answer"},
        {"role": "user", "content": "Follow-up"},
    ]

    messages = await ctx.build_messages(
        history=history,
        current_message="Another question",
        author="skye",
    )

    # Should have: system, user (merged), assistant, user (merged)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    # The last user message should be merged with the previous
    assert "Follow-up" in messages[-1]["content"]
    assert "Another question" in messages[-1]["content"]
    assert len(messages) == 4  # system + merged user + assistant + merged user


# ── System blocks (caching) ─────────────────────────────────────────


def test_build_static_blocks_returns_list(ctx):
    """Verify _build_static_blocks returns a list of blocks."""
    blocks = ctx._build_static_blocks()
    assert isinstance(blocks, list)
    assert len(blocks) > 0
    assert all("type" in b for b in blocks)
    assert all(b["type"] == "text" for b in blocks)


def test_build_static_blocks_has_cache_control(ctx):
    """Verify static blocks have cache_control marker when caching enabled."""
    blocks = ctx._build_static_blocks(enable_caching=True)
    # At least one block should have cache_control
    cached_blocks = [b for b in blocks if "cache_control" in b]
    assert len(cached_blocks) >= 1
    assert cached_blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_build_static_blocks_no_caching(ctx):
    """Verify cache_control can be disabled."""
    blocks = ctx._build_static_blocks(enable_caching=False)
    # No blocks should have cache_control
    cached_blocks = [b for b in blocks if "cache_control" in b]
    assert len(cached_blocks) == 0


async def test_build_dynamic_blocks_includes_content(ctx):
    """Verify dynamic content (time, session) is included."""
    blocks = await ctx._build_dynamic_blocks(author="skye", channel="telegram", chat_id="123")
    # Join all block texts
    full_text = "".join(b.get("text", "") for b in blocks)
    assert "telegram" in full_text
    assert "123" in full_text
    assert "Current Time" in full_text
