"""Exercise the provider retry classifier with structured errors."""

from nanobot.providers.base import LLMProvider, LLMResponse


def main() -> None:
    bad_gateway = LLMResponse(
        content="origin_bad_gateway",
        finish_reason="error",
        error_status_code=502,
    )
    auth_error = LLMResponse(
        content="invalid api key",
        finish_reason="error",
        error_status_code=401,
    )
    print(f"502_transient={LLMProvider.is_transient_response(bad_gateway)}")
    print(f"401_transient={LLMProvider.is_transient_response(auth_error)}")


if __name__ == "__main__":
    main()
