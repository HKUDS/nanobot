from nanobot.utils.helpers import split_message


def test_split_message_plain_text_keeps_existing_boundary_behavior() -> None:
    assert split_message("abc def", 4) == ["abc", "def"]


def test_split_message_reopens_fenced_code_block_across_chunks() -> None:
    content = (
        "Intro\n\n"
        "```python\n"
        "first = 'alpha'\n"
        "second = 'beta'\n"
        "third = 'gamma'\n"
        "```\n"
        "Outro"
    )

    chunks = split_message(content, 46)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 46 for chunk in chunks)
    assert chunks[0].endswith("\n```")
    assert chunks[1].startswith("```python\n")


def test_split_message_repeatedly_repairs_long_fenced_code_block() -> None:
    content = "```python\n" + "\n".join(f"print({i})" for i in range(12)) + "\n```"

    chunks = split_message(content, 34)

    assert len(chunks) > 2
    assert all(len(chunk) <= 34 for chunk in chunks)
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert any(chunk.startswith("```python\n") for chunk in chunks[1:])


def test_split_message_does_not_reopen_before_original_closing_fence() -> None:
    content = "Intro\n\n```python\n" + "\n".join(f"print({i})" for i in range(8)) + "\n```\nOutro"

    chunks = split_message(content, 40)

    assert chunks[-1] == "Outro"
    assert "```python\n```\n" not in "\n".join(chunks)
