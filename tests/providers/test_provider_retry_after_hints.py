from types import SimpleNamespace

from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def test_openai_compat_error_captures_retry_after_from_headers() -> None:
    err = Exception("boom")
    err.doc = None
    err.response = SimpleNamespace(
        text='{"error":{"message":"Rate limit exceeded"}}',
        headers={"Retry-After": "20"},
    )

    response = OpenAICompatProvider._handle_error(err)

    assert response.retry_after == 20.0
