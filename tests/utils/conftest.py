import pytest
import tiktoken


@pytest.fixture
def byte_encoding() -> tiktoken.Encoding:
    """Exercise the tokenizer API without downloading an upstream vocabulary."""
    return tiktoken.Encoding(
        name="test-bytes",
        pat_str=r"(?s).",
        mergeable_ranks={bytes([value]): value for value in range(256)},
        special_tokens={"<|endoftext|>": 256},
    )
