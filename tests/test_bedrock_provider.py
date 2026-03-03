"""Tests for AWS Bedrock provider integration."""

import pytest

from nanobot.providers.registry import find_by_model, find_by_name


def test_bedrock_spec_exists():
    """Verify Bedrock is registered."""
    spec = find_by_name("bedrock")
    assert spec is not None
    assert spec.name == "bedrock"
    assert spec.litellm_prefix == "bedrock"
    assert spec.supports_prompt_caching is True
    assert spec.display_name == "AWS Bedrock"


def test_bedrock_keyword_matching():
    """Test model name matching by bedrock keyword."""
    spec = find_by_model("bedrock/claude-3-sonnet")
    assert spec is not None
    assert spec.name == "bedrock"


def test_bedrock_no_api_key_required():
    """Verify Bedrock doesn't require api_key (uses AWS credential chain)."""
    spec = find_by_name("bedrock")
    assert spec.env_key == ""


def test_bedrock_default_region():
    """Verify Bedrock has default region configured."""
    spec = find_by_name("bedrock")
    assert spec.default_api_base == "us-east-1"


def test_bedrock_env_extras_region_mapping():
    """Verify region mapping via env_extras."""
    spec = find_by_name("bedrock")
    assert len(spec.env_extras) > 0
    # Should have AWS_REGION_NAME mapping
    env_names = [e[0] for e in spec.env_extras]
    assert "AWS_REGION_NAME" in env_names


def test_bedrock_skip_prefixes():
    """Verify skip_prefixes to avoid double-prefixing."""
    spec = find_by_name("bedrock")
    assert "bedrock/" in spec.skip_prefixes


def test_bedrock_cache_control_support():
    """Verify Claude models support prompt caching."""
    spec = find_by_name("bedrock")
    assert spec.supports_prompt_caching is True


def test_bedrock_not_gateway():
    """Verify Bedrock is not marked as gateway."""
    spec = find_by_name("bedrock")
    assert spec.is_gateway is False


def test_bedrock_not_local():
    """Verify Bedrock is not marked as local deployment."""
    spec = find_by_name("bedrock")
    assert spec.is_local is False


def test_bedrock_not_oauth():
    """Verify Bedrock is not marked as OAuth (uses IAM)."""
    spec = find_by_name("bedrock")
    assert spec.is_oauth is False


# Test ARN format support (integration test)
@pytest.mark.parametrize("model,expected_result", [
    # ARN format should be auto-prefixed with bedrock/
    ("arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0",
     "bedrock/arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0"),
    # Already prefixed models should not be double-prefixed
    ("bedrock/anthropic.claude-3-haiku-20240307-v1:0", "bedrock/anthropic.claude-3-haiku-20240307-v1:0"),
])
def test_bedrock_arn_format_handling(model, expected_result):
    """Test that ARN format is correctly handled."""
    from nanobot.providers.litellm_provider import LiteLLMProvider

    provider = LiteLLMProvider(
        api_key="",
        api_base="us-east-1",
        default_model=model,
        provider_name="bedrock"
    )

    resolved = provider._resolve_model(model)
    assert resolved == expected_result


def test_bedrock_explicit_prefix_usage():
    """Test that Bedrock models should use explicit bedrock/ prefix.

    Note: Bare Bedrock model IDs like 'anthropic.claude-3-sonnet' contain 'anthropic'
    keyword which matches Anthropic provider first. Users must use 'bedrock/' prefix
    explicitly to use Bedrock provider.
    """
    from nanobot.providers.litellm_provider import LiteLLMProvider

    # Without bedrock/ prefix, model with 'bedrock' keyword is detected
    spec = find_by_model("bedrock-some-model")
    assert spec is not None
    assert spec.name == "bedrock"

    # With explicit bedrock/ prefix
    provider = LiteLLMProvider(
        api_key="",
        api_base="us-east-1",
        default_model="bedrock/anthropic.claude-3-haiku-20240307-v1:0",
        provider_name="bedrock"
    )
    resolved = provider._resolve_model("bedrock/anthropic.claude-3-haiku-20240307-v1:0")
    # Should not double-prefix due to skip_prefixes
    assert resolved == "bedrock/anthropic.claude-3-haiku-20240307-v1:0"
