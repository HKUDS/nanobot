from nanobot.utils.anthropic_compat_proxy import (
    join_upstream_url,
    rewrite_json_payload,
    rewrite_model_name,
    should_rewrite_model,
)


def test_should_rewrite_claude_aliases_and_full_names():
    assert should_rewrite_model("opus")
    assert should_rewrite_model("sonnet")
    assert should_rewrite_model("claude-opus-4-1")
    assert should_rewrite_model("claude-sonnet-4-6")


def test_should_not_rewrite_non_claude_models():
    assert not should_rewrite_model("qwen3.5-plus")
    assert not should_rewrite_model("gemini-3.1-pro-high")


def test_rewrite_model_name_maps_to_target():
    assert rewrite_model_name("opus", "glm-5") == "glm-5"
    assert rewrite_model_name("claude-opus-4-1", "glm-5") == "glm-5"
    assert rewrite_model_name("qwen3.5-plus", "glm-5") == "qwen3.5-plus"


def test_rewrite_json_payload_only_updates_model_field():
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 32}

    rewritten, changed = rewrite_json_payload(payload, "glm-5")

    assert changed is True
    assert rewritten["model"] == "glm-5"
    assert rewritten["max_tokens"] == 32
    assert payload["model"] == "claude-sonnet-4-6"


def test_join_upstream_url_avoids_double_v1():
    assert (
        join_upstream_url("http://127.0.0.1:9000/v1", "/v1/messages", "")
        == "http://127.0.0.1:9000/v1/messages"
    )
    assert (
        join_upstream_url("http://127.0.0.1:9000/v1", "/messages", "a=1")
        == "http://127.0.0.1:9000/v1/messages?a=1"
    )
