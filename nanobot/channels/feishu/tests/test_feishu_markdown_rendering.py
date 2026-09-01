# Check optional Feishu dependencies before running tests
try:
    from nanobot.channels.feishu.runtime import FEISHU_AVAILABLE
except ImportError:
    FEISHU_AVAILABLE = False

if not FEISHU_AVAILABLE:
    import pytest
    pytest.skip("Feishu dependencies not installed (lark-oapi)", allow_module_level=True)

from nanobot.channels.feishu.runtime import FeishuChannel


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


def test_build_card_elements_keeps_fenced_markdown_tables_intact() -> None:
    channel = FeishuChannel.__new__(FeishuChannel)
    text = "Before\n\n```\n| a | b |\n| - | - |\n| 1 | 2 |\n```\n\nAfter"

    elements = channel._build_card_elements(text)

    assert all(el.get("tag") != "table" for el in elements)
    joined = "\n".join(el["content"] for el in elements if el.get("tag") == "markdown")
    assert "```\n| a | b |\n| - | - |\n| 1 | 2 |\n```" in joined


def test_build_card_elements_still_parses_unfenced_markdown_tables() -> None:
    channel = FeishuChannel.__new__(FeishuChannel)
    text = "Before\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\nAfter"

    elements = channel._build_card_elements(text)

    assert any(el.get("tag") == "table" for el in elements)
