import json

from nanobot.channels.feishu.runtime import (
    _extract_post_content,
    _extract_share_card_content,
)


def test_extract_interactive_card_reads_user_dsl_body_elements() -> None:
    content = {
        "user_dsl": json.dumps(
            {
                "schema": "2.0",
                "body": {"elements": [{"tag": "markdown", "content": "**hello**"}]},
            }
        )
    }

    assert _extract_share_card_content(content, "interactive") == "**hello**"


def test_extract_interactive_card_reads_nested_text_elements() -> None:
    content = {"elements": [[{"tag": "text", "text": "hello"}]]}

    assert _extract_share_card_content(content, "interactive") == "hello"


def test_extract_interactive_card_reads_table_rows() -> None:
    content = {
        "elements": [
            {
                "tag": "table",
                "columns": [
                    {"name": "c0", "display_name": "Name"},
                    {"name": "c1", "display_name": "Score"},
                ],
                "rows": [{"c0": "Alice", "c1": 98}],
            }
        ]
    }

    assert _extract_share_card_content(content, "interactive") == "Name | Score\nAlice | 98"


def test_extract_post_content_tolerates_null_fields() -> None:
    text, images = _extract_post_content(
        {
            "title": None,
            "content": [
                [
                    {"tag": "text", "text": None},
                    {"tag": "a", "text": None},
                    {"tag": "at", "user_name": None},
                    {"tag": "text", "text": "ok"},
                    {"tag": "code_block", "language": None, "text": None},
                ]
            ],
        }
    )
    assert "@user" in text
    assert "ok" in text
    assert images == []
