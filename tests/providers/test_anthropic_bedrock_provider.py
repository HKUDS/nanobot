from unittest.mock import patch

from nanobot.providers.anthropic_provider import AnthropicProvider


def test_anthropic_provider_strips_bedrock_prefix():
    model = "bedrock/arn:aws:bedrock:us-west-2:123456789012:application-inference-profile/test"

    assert AnthropicProvider._strip_prefix(model) == (
        "arn:aws:bedrock:us-west-2:123456789012:application-inference-profile/test"
    )


def test_anthropic_provider_uses_bedrock_client_for_bedrock_mode():
    with patch("anthropic.AsyncAnthropicBedrock") as mock_bedrock:
        AnthropicProvider(
            default_model="bedrock/anthropic.claude-3-haiku-20240307-v1:0",
            use_bedrock=True,
            aws_profile="default",
            aws_region="us-west-2",
            extra_headers={"x-test-header": "enabled"},
        )

    kwargs = mock_bedrock.call_args.kwargs
    assert kwargs["aws_profile"] == "default"
    assert kwargs["aws_region"] == "us-west-2"
    assert kwargs["default_headers"]["x-test-header"] == "enabled"
