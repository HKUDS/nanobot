"""Tests for FeishuChannel._split_elements_by_table_limit.

Feishu cards reject messages that contain more than one table element
(API error 11310: card table number over limit).  The helper splits a flat
list of card elements into groups so that each group contains at most one
table, allowing nanobot to send multiple cards instead of failing.
"""

from nanobot.channels.feishu import FeishuChannel


def _md(text: str) -> dict:
    return {"tag": "markdown", "content": text}


def _table() -> dict:
    return {
        "tag": "table",
        "columns": [{"tag": "column", "name": "c0", "display_name": "A", "width": "auto"}],
        "rows": [{"c0": "v"}],
        "page_size": 2,
    }


split = FeishuChannel._split_elements_by_table_limit


def test_empty_list_returns_single_empty_group() -> None:
    assert split([]) == [[]]


def test_no_tables_returns_single_group() -> None:
    els = [_md("hello"), _md("world")]
    result = split(els)
    assert result == [els]


def test_single_table_stays_in_one_group() -> None:
    els = [_md("intro"), _table(), _md("outro")]
    result = split(els)
    assert len(result) == 1
    assert result[0] == els


def test_two_tables_split_into_two_groups() -> None:
    # Use different row values so the two tables are not equal
    t1 = {
        "tag": "table",
        "columns": [{"tag": "column", "name": "c0", "display_name": "A", "width": "auto"}],
        "rows": [{"c0": "table-one"}],
        "page_size": 2,
    }
    t2 = {
        "tag": "table",
        "columns": [{"tag": "column", "name": "c0", "display_name": "B", "width": "auto"}],
        "rows": [{"c0": "table-two"}],
        "page_size": 2,
    }
    els = [_md("before"), t1, _md("between"), t2, _md("after")]
    result = split(els)
    assert len(result) == 2
    # First group: text before table-1 + table-1
    assert t1 in result[0]
    assert t2 not in result[0]
    # Second group: text between tables + table-2 + text after
    assert t2 in result[1]
    assert t1 not in result[1]


def test_three_tables_split_into_three_groups() -> None:
    tables = [
        {"tag": "table", "columns": [], "rows": [{"c0": f"t{i}"}], "page_size": 1} for i in range(3)
    ]
    els = tables[:]
    result = split(els)
    assert len(result) == 3
    for i, group in enumerate(result):
        assert tables[i] in group


def test_leading_markdown_stays_with_first_table() -> None:
    intro = _md("intro")
    t = _table()
    result = split([intro, t])
    assert len(result) == 1
    assert result[0] == [intro, t]


def test_trailing_markdown_after_second_table() -> None:
    t1, t2 = _table(), _table()
    tail = _md("end")
    result = split([t1, t2, tail])
    assert len(result) == 2
    assert result[1] == [t2, tail]


def test_non_table_elements_before_first_table_kept_in_first_group() -> None:
    head = _md("head")
    t1, t2 = _table(), _table()
    result = split([head, t1, t2])
    # head + t1 in group 0; t2 in group 1
    assert result[0] == [head, t1]
    assert result[1] == [t2]
