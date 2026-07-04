import json

from blackcat.channels.feishu import _extract_share_card_content


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
