import time

from nanobot.memory_index.indexer import (
    MIN_TOKENS,
    chunk_history_file,
    chunk_memory_file,
)


def test_chunk_memory_splits_on_headers(tmp_path):
    f = tmp_path / "MEMORY.md"
    f.write_text(
        "## Section A\n\nContent about section A.\n\n## Section B\n\nContent about section B.\n"
    )
    chunks = chunk_memory_file(f)
    assert len(chunks) == 2
    assert "Content about section A" in chunks[0].text
    assert "Content about section B" in chunks[1].text


def test_chunk_memory_skips_short_sections(tmp_path):
    f = tmp_path / "MEMORY.md"
    # 'hi' is way below MIN_TOKENS
    long_content = "word " * 60  # ~75 tokens
    f.write_text(f"## Tiny\n\nhi\n\n## Normal\n\n{long_content}\n")
    chunks = chunk_memory_file(f)
    # Tiny section (< MIN_TOKENS) should not produce a standalone chunk
    for c in chunks:
        assert len(c.text) // 4 >= MIN_TOKENS


def test_chunk_memory_created_at_from_mtime(tmp_path):
    f = tmp_path / "MEMORY.md"
    f.write_text("## Facts\n\nSome fact.\n")
    before = time.time()
    chunks = chunk_memory_file(f)
    after = time.time()
    assert chunks
    assert before - 1 <= chunks[0].created_at <= after + 1


def test_chunk_memory_large_section_splits_on_paragraphs(tmp_path):
    f = tmp_path / "MEMORY.md"
    # Each paragraph is ~50 tokens; with TARGET_TOKENS=400 we need 9+ paras to split
    para = "word " * 55 + "\n"  # ~55 tokens
    content = "\n\n".join([para] * 10)
    f.write_text(f"## Big Section\n\n{content}\n")
    chunks = chunk_memory_file(f)
    assert len(chunks) >= 2


def test_chunk_history_splits_by_timestamp(tmp_path):
    f = tmp_path / "HISTORY.md"
    f.write_text(
        "[2025-01-01 10:00] USER: hello world\n\n[2025-01-02 11:00] USER: another entry\n\n"
    )
    chunks = chunk_history_file(f)
    assert len(chunks) >= 1
    # created_at must be parsed from the timestamp, not file mtime
    assert chunks[0].created_at > 0
    # Jan 1 2025 is around unix 1735689600
    assert chunks[0].created_at > 1_700_000_000


def test_chunk_history_groups_small_entries(tmp_path):
    f = tmp_path / "HISTORY.md"
    entries = "".join(f"[2025-01-{i + 1:02d} 10:00] USER: short entry {i}\n\n" for i in range(5))
    f.write_text(entries)
    chunks = chunk_history_file(f)
    # All 5 tiny entries should fit in a single window
    assert len(chunks) == 1


def test_chunk_history_splits_large_window(tmp_path):
    f = tmp_path / "HISTORY.md"
    # Each entry ~60 tokens; 8 entries = ~480 tokens > TARGET_TOKENS
    big_entry = "word " * 60
    entries = "".join(f"[2025-01-{i + 1:02d} 10:00] USER: {big_entry}\n\n" for i in range(8))
    f.write_text(entries)
    chunks = chunk_history_file(f)
    assert len(chunks) >= 2


def test_chunk_memory_merges_short_tail(tmp_path):
    # Create a MEMORY.md with one section that splits into paragraphs,
    # where the last paragraph is very short (< 50 tokens)
    content = "# Long-term Memory\n\n## Big Section\n\n"
    # Add a large first paragraph (> 400 tokens)
    content += "A " * 250 + "\n\n"  # ~250 tokens first paragraph
    # Add a short second paragraph (< 50 tokens)
    content += "Short tail.\n"

    p = tmp_path / "MEMORY.md"
    p.write_text(content)
    chunks = chunk_memory_file(p)

    # Should not have a standalone chunk for "Short tail."
    # The short tail should be merged into the last chunk
    assert not any(c.text.strip() == "Short tail." for c in chunks)
    # The last chunk should contain "Short tail."
    assert "Short tail." in chunks[-1].text


def test_chunk_memory_overlap_on_split(tmp_path):
    # Create a single section with two large paragraphs that together exceed TARGET_TOKENS
    content = "## Big Section\n\n"
    content += "Alpha " * 250 + "\n\n"  # ~250 tokens first para
    content += "Beta " * 250 + "\n"  # ~250 tokens second para
    # Together ~500 tokens > TARGET_TOKENS=400, so the section will split

    p = tmp_path / "MEMORY.md"
    p.write_text(content)
    chunks = chunk_memory_file(p)

    # Should produce multiple chunks
    assert len(chunks) >= 2
    # The second chunk should contain overlap text from the end of the first chunk.
    # Overlap is the last OVERLAP_TOKENS * TOKEN_ESTIMATE_RATIO = 200 chars of chunk[0].
    overlap_text = chunks[0].text[-200:]
    assert overlap_text.strip() in chunks[1].text
