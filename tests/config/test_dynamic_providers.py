import json
from nanobot.config.loader import load_config
from nanobot.providers.registry import find_by_name

def test_dynamic_provider_loading(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "provider": "my_new_ai",
                        "model": "gpt-4o"
                    }
                },
                "providers": {
                    "my_new_ai": {
                        "apiKey": "sk-dynamic-key",
                        "apiBase": "https://api.dynamic.ai/v1"
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    
    # 1. Test find_by_name synthesizes for unknown names
    spec = find_by_name("my_new_ai")
    assert spec is not None
    assert spec.name == "my_new_ai"
    assert spec.display_name == "My New Ai"
    assert spec.backend == "openai_compat"
    
    # 2. Test _get_provider_config retrieves from model_extra
    p_conf = config._get_provider_config("my_new_ai")
    assert p_conf is not None
    assert p_conf.api_key == "sk-dynamic-key"
    assert p_conf.api_base == "https://api.dynamic.ai/v1"

    # 3. Test _match_provider with forced provider
    matched_p, matched_name = config._match_provider()
    assert matched_name == "my_new_ai"
    assert matched_p is not None
    assert matched_p.api_key == "sk-dynamic-key"

def test_dynamic_provider_prefix_matching(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "provider": "auto",
                        "model": "another_ai/fast-model"
                    }
                },
                "providers": {
                    "another_ai": {
                        "apiKey": "sk-another-key",
                        "apiBase": "https://api.another.ai/v1"
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    
    # Test that prefix "another_ai" matches the dynamic provider
    matched_p, matched_name = config._match_provider()
    assert matched_name == "another_ai"
    assert matched_p is not None
    assert matched_p.api_key == "sk-another-key"

def test_dynamic_provider_fallback(tmp_path) -> None:
    # Test that it doesn't match if no key is provided
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "empty_ai": {
                        "apiBase": "https://api.empty.ai/v1"
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    matched_p, matched_name = config._match_provider(model="empty_ai/model")
    
    # It should NOT match empty_ai because it has no api_key and is not local
    assert matched_name != "empty_ai"
