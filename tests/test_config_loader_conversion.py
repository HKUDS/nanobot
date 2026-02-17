from nanobot.config.loader import convert_keys, convert_to_camel


def test_convert_keys_preserves_extra_headers_key_casing() -> None:
    data = {
        "providers": {
            "openrouter": {
                "extraHeaders": {
                    "HTTP-Referer": "https://example.com",
                    "X-Title": "nanobot",
                }
            }
        }
    }

    converted = convert_keys(data)

    assert converted["providers"]["openrouter"]["extra_headers"] == {
        "HTTP-Referer": "https://example.com",
        "X-Title": "nanobot",
    }


def test_convert_keys_still_converts_non_header_keys() -> None:
    data = {
        "tools": {
            "restrictToWorkspace": True,
        }
    }

    converted = convert_keys(data)

    assert converted == {
        "tools": {
            "restrict_to_workspace": True,
        }
    }


def test_convert_keys_converts_provider_fields_but_preserves_header_entries() -> None:
    data = {
        "providers": {
            "openrouter": {
                "apiBase": "https://openrouter.ai/api/v1",
                "extraHeaders": {
                    "HTTP-Referer": "https://example.com",
                    "X-Title": "nanobot",
                },
            }
        }
    }

    converted = convert_keys(data)

    assert converted["providers"]["openrouter"]["api_base"] == "https://openrouter.ai/api/v1"
    assert converted["providers"]["openrouter"]["extra_headers"] == {
        "HTTP-Referer": "https://example.com",
        "X-Title": "nanobot",
    }


def test_header_keys_survive_convert_round_trip() -> None:
    snake_data = {
        "providers": {
            "openrouter": {
                "api_base": "https://openrouter.ai/api/v1",
                "extra_headers": {
                    "HTTP-Referer": "https://example.com",
                    "X-Title": "nanobot",
                },
            }
        },
        "tools": {
            "restrict_to_workspace": True,
        },
    }

    camel = convert_to_camel(snake_data)
    round_tripped = convert_keys(camel)

    assert round_tripped == snake_data


def test_convert_keys_keeps_preserve_entry_keys_param_compatibility() -> None:
    data = {
        "HTTPReferer": {
            "XTitle": "nanobot",
        }
    }

    converted = convert_keys(data, preserve_entry_keys=True)

    assert converted == {
        "HTTPReferer": {
            "x_title": "nanobot",
        }
    }
