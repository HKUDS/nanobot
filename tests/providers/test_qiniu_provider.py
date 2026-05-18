"""Tests for the Qiniu OpenAI-compatible provider entry."""

from nanobot.config.schema import ProvidersConfig
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_qiniu_config_field_exists():
    """ProvidersConfig should have a qiniu field."""
    config = ProvidersConfig()
    assert hasattr(config, "qiniu")


def test_qiniu_provider_in_registry():
    specs = {spec.name: spec for spec in PROVIDERS}
    assert "qiniu" in specs
    qiniu = specs["qiniu"]
    assert qiniu.backend == "openai_compat"
    assert qiniu.env_key == "QINIU_API_KEY"
    assert qiniu.default_api_base == "https://api.qnaigc.com/v1"


def test_find_by_name_qiniu():
    """find_by_name should resolve the qiniu provider."""
    spec = find_by_name("qiniu")
    assert spec is not None
    assert spec.name == "qiniu"
