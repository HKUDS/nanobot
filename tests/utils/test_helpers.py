from blackcat.utils.helpers import split_message


def test_split_message_no_code_blocks_unchanged():
    content = "alpha beta gamma delta"

    assert split_message(content, max_len=12) == ["alpha beta", "gamma delta"]


def test_split_message_outside_code_block_unchanged():
    content = "alpha beta gamma delta\n```python\nx = 1\n```\ndone"

    chunks = split_message(content, max_len=12)

    assert chunks[0] == "alpha beta"
    assert chunks[1].startswith("gamma")


def test_split_message_inside_code_block_moves_before_fence():
    content = "Intro paragraph.\n```python\nprint('a')\nprint('b')\n```\nDone"

    chunks = split_message(content, max_len=35)

    assert chunks[0] == "Intro paragraph.\n"
    assert chunks[1].startswith("```python\nprint('a')")
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks[1:])


def test_split_message_code_block_longer_than_max_len_closes_and_reopens():
    content = "```python\n" + ("print('line one')\n" * 6) + "```\nDone"

    chunks = split_message(content, max_len=60)

    assert len(chunks) > 1
    assert all(len(chunk) <= 60 for chunk in chunks)
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert chunks[0].startswith("```python\n")
    assert chunks[0].endswith("\n```")
    assert chunks[1].startswith("```python\n")


def test_split_message_multiple_code_blocks_moves_second_block_to_next_chunk():
    content = (
        "First\n"
        "```js\n"
        "one();\n"
        "```\n"
        "Middle paragraph here\n"
        "```py\n"
        "two()\n"
        "three()\n"
        "```\n"
        "End"
    )

    chunks = split_message(content, max_len=55)

    assert chunks[0].endswith("Middle paragraph here\n")
    assert chunks[1].startswith("```py\n")
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
