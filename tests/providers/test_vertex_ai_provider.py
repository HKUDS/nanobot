"""Tests for Claude models served through Google Vertex AI."""

from unittest.mock import patch

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.factory import make_provider
from nanobot.providers.registry import find_by_name
from nanobot.providers.vertex_ai_provider import VertexAIProvider


def test_vertex_provider_is_registered_without_api_key() -> None:
    spec = find_by_name("google_vertex_ai")
    assert spec is not None
    assert spec.backend == "google_vertex_ai"
    assert spec.is_direct is True
    assert hasattr(ProvidersConfig(), "google_vertex_ai")

    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "google_vertex_ai/claude-sonnet-4-5@20250929",
            }
        },
        "providers": {
            "googleVertexAi": {
                "project": "test-project",
                "region": "us-east5",
            }
        },
    })

    assert config.get_provider_name() == "google_vertex_ai"
    assert config.get_provider().project == "test-project"


def test_vertex_provider_builds_anthropic_vertex_client() -> None:
    with patch("anthropic.lib.vertex.AsyncAnthropicVertex") as client:
        provider = VertexAIProvider(
            default_model="google_vertex_ai/claude-sonnet-4-5@20250929",
            project="test-project",
            region="europe-west1",
        )

    client.assert_called_once_with(
        project_id="test-project",
        region="europe-west1",
        max_retries=0,
    )
    assert provider._strip_prefix(provider.default_model) == "claude-sonnet-4-5@20250929"


def test_factory_creates_vertex_provider() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "google_vertex_ai/claude-sonnet-4-5@20250929",
                "provider": "google_vertex_ai",
            }
        },
        "providers": {
            "googleVertexAi": {
                "project": "test-project",
                "region": "us-east5",
            }
        },
    })

    with patch("anthropic.lib.vertex.AsyncAnthropicVertex") as client:
        provider = make_provider(config)

    assert isinstance(provider, VertexAIProvider)
    client.assert_called_once_with(
        project_id="test-project",
        region="us-east5",
        max_retries=0,
    )
