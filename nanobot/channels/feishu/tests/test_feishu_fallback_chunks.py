from nanobot.channels.feishu.runtime import FeishuChannel


def test_fallback_text_chunks_nonpositive_limit_returns_unsplit() -> None:
    content = "hello world\nmore text that would hang without a limit guard"

    assert FeishuChannel._fallback_text_chunks(content, limit=0) == [content]
    assert FeishuChannel._fallback_text_chunks(content, limit=-1) == [content]


def test_fallback_text_chunks_positive_limit_splits() -> None:
    content = ("line one with some words\n" * 8).strip()
    chunks = FeishuChannel._fallback_text_chunks(content, limit=40)
    assert len(chunks) > 1
    assert all(len(chunk) <= 40 for chunk in chunks)
    assert all(chunk for chunk in chunks)
