from blackcat.utils.helpers import split_message


def test_split_message_no_code_blocks_unchanged():
    content = "alpha beta gamma delta"

    assert split_message(content, max_len=12) == ["alpha beta", "gamma delta"]
