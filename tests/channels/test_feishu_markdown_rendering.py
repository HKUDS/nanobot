# Check optional Feishu dependencies before running tests
try:
    from nanobot.channels import feishu
    FEISHU_AVAILABLE = getattr(feishu, "FEISHU_AVAILABLE", False)
except ImportError:
    FEISHU_AVAILABLE = False

if not FEISHU_AVAILABLE:
    import pytest
    pytest.skip("Feishu dependencies not installed (lark-oapi)", allow_module_level=True)

from nanobot.channels.feishu import FeishuChannel


def test_parse_md_table_strips_markdown_formatting_in_headers_and_cells() -> None:
    table = FeishuChannel._parse_md_table(
        """
| **Name** | __Status__ | *Notes* | ~~State~~ |
| --- | --- | --- | --- |
| **Alice** | __Ready__ | *Fast* | ~~Old~~ |
"""
    )

    assert table is not None
    assert [col["display_name"] for col in table["columns"]] == [
        "Name",
        "Status",
        "Notes",
        "State",
    ]
    assert table["rows"] == [
        {"c0": "Alice", "c1": "Ready", "c2": "Fast", "c3": "Old"}
    ]


def test_split_headings_strips_embedded_markdown_before_bolding() -> None:
    channel = FeishuChannel.__new__(FeishuChannel)

    elements = channel._split_headings("# **Important** *status* ~~update~~")

    assert elements == [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**Important status update**",
            },
        }
    ]


def test_split_headings_keeps_markdown_body_and_code_blocks_intact() -> None:
    channel = FeishuChannel.__new__(FeishuChannel)

    elements = channel._split_headings(
        "# **Heading**\n\nBody with **bold** text.\n\n```python\nprint('hi')\n```"
    )

    assert elements[0] == {
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": "**Heading**",
        },
    }
    assert elements[1]["tag"] == "markdown"
    assert "Body with **bold** text." in elements[1]["content"]
    assert "```python\nprint('hi')\n```" in elements[1]["content"]
