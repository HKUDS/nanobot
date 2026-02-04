# Changelog 2026-02-05

## Added

- Added `CustomLLMProvider` with `CustomLLMConfig` for configurable headers, api_url, api_key, and validation.
- Added cumulative token tracking with optional precheck/postcheck enforcement.
- Added response size metadata via `LLMResponse.response_size_bytes`.

## Changed

- Exported `CustomLLMProvider` from `nanobot.providers`.
