from nanobot.config.schema import Config
from nanobot.providers.registry import find_by_model, find_by_name


def test_providers_config_accepts_canonical_zai_key():
    config = Config.model_validate(
        {
            "providers": {
                "zai": {
                    "apiKey": "zai-key",
                    "apiBase": "https://api.z.ai/api/coding/paas/v4/",
                }
            }
        }
    )

    assert config.providers.zai.api_key == "zai-key"
    assert config.providers.zhipu.api_key == "zai-key"  # backward-compatible attribute alias
    assert config.get_provider_name("glm-4") == "zai"


def test_providers_config_accepts_legacy_zhipu_key():
    config = Config.model_validate(
        {
            "providers": {
                "zhipu": {
                    "apiKey": "legacy-key",
                }
            }
        }
    )

    assert config.providers.zai.api_key == "legacy-key"
    assert config.get_provider_name("zhipu/glm-4") == "zai"


def test_zai_registry_spec_has_default_base_and_coding_override_docs():
    spec = find_by_name("zai")

    assert spec is not None
    assert spec.default_api_base == "https://open.bigmodel.cn/api/paas/v4"
    assert ("ZHIPUAI_API_BASE", "{api_base}") in spec.env_extras
    assert ("ZAI_API_BASE", "{api_base}") in spec.env_extras


def test_find_by_model_routes_glm_models_to_zai():
    spec = find_by_model("glm-4-plus")

    assert spec is not None
    assert spec.name == "zai"
