# Check optional Feishu dependencies before running tests
try:
    from nanobot.channels import feishu
    FEISHU_AVAILABLE = getattr(feishu, "FEISHU_AVAILABLE", False)
except ImportError:
    FEISHU_AVAILABLE = False

if not FEISHU_AVAILABLE:
    import pytest
    pytest.skip("Feishu dependencies not installed (lark-oapi)", allow_module_level=True)

from nanobot.channels.feishu import FeishuChannel, _extract_post_content


def test_extract_post_content_supports_post_wrapper_shape() -> None:
    payload = {
        "post": {
            "zh_cn": {
                "title": "日报",
                "content": [
                    [
                        {"tag": "text", "text": "完成"},
                        {"tag": "img", "image_key": "img_1"},
                    ]
                ],
            }
        }
    }

    text, image_keys, media_items = _extract_post_content(payload)

    assert text == "日报 完成"
    assert image_keys == ["img_1"]
    assert media_items == []


def test_extract_post_content_keeps_direct_shape_behavior() -> None:
    payload = {
        "title": "Daily",
        "content": [
            [
                {"tag": "text", "text": "report"},
                {"tag": "img", "image_key": "img_a"},
                {"tag": "img", "image_key": "img_b"},
            ]
        ],
    }

    text, image_keys, media_items = _extract_post_content(payload)

    assert text == "Daily report"
    assert image_keys == ["img_a", "img_b"]
    assert media_items == []


def test_extract_post_content_extracts_media_tags() -> None:
    payload = {
        "title": "",
        "content": [
            [{"tag": "img", "image_key": "img_1", "width": 345, "height": 34}],
            [{"tag": "media", "file_key": "file_v3_0010j_abc", "image_key": "img_v3_0210j_xyz"}],
        ],
    }

    text, image_keys, media_items = _extract_post_content(payload)

    assert image_keys == ["img_1"]
    assert media_items == [{"tag": "media", "file_key": "file_v3_0010j_abc"}]


def test_extract_post_content_ignores_media_without_file_key() -> None:
    payload = {
        "content": [
            [{"tag": "media"}],
        ],
    }

    text, image_keys, media_items = _extract_post_content(payload)

    assert media_items == []


def test_register_optional_event_keeps_builder_when_method_missing() -> None:
    class Builder:
        pass

    builder = Builder()
    same = FeishuChannel._register_optional_event(builder, "missing", object())
    assert same is builder


def test_register_optional_event_calls_supported_method() -> None:
    called = []

    class Builder:
        def register_event(self, handler):
            called.append(handler)
            return self

    builder = Builder()
    handler = object()
    same = FeishuChannel._register_optional_event(builder, "register_event", handler)

    assert same is builder
    assert called == [handler]
