# Development

This page collects contributor-facing notes for extending nanobot. User-facing setup
and runtime options live in [`configuration.md`](./configuration.md).

## Adding an LLM Provider

nanobot uses the provider registry in `nanobot/providers/registry.py` as the
source of truth for LLM provider metadata. Most OpenAI-compatible providers need
only two changes.

1. Add a `ProviderSpec` entry to `PROVIDERS`:

```python
ProviderSpec(
    name="myprovider",
    keywords=("myprovider", "mymodel"),
    env_key="MYPROVIDER_API_KEY",
    display_name="My Provider",
    default_api_base="https://api.myprovider.com/v1",
)
```

2. Add a field to `ProvidersConfig` in `nanobot/config/schema.py`:

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = Field(default_factory=ProviderConfig)
```

Environment variables, config matching, provider status, and WebUI credential
display derive from those two entries.

Useful `ProviderSpec` options:

| Field | Description |
|---|---|
| `default_api_base` | Default OpenAI-compatible base URL. |
| `env_extras` | Additional environment variables derived from the provider config. |
| `model_overrides` | Per-model request parameter overrides. |
| `is_gateway` | Provider can route many model families, like OpenRouter. |
| `detect_by_key_prefix` | Match configured gateways by API-key prefix. |
| `detect_by_base_keyword` | Match configured gateways by API base URL. |
| `strip_model_prefix` | Strip `provider/` before sending the model to the upstream API. |
| `supports_max_completion_tokens` | Use `max_completion_tokens` instead of `max_tokens`. |
| `is_transcription_only` | Provider has credentials but cannot serve chat completions. |

## Adding a Transcription Provider

Transcription is intentionally split into two layers:

- `nanobot/audio/transcription_registry.py` owns provider names, aliases, default
  models, and adapter loading.
- `nanobot/providers/transcription.py` owns provider-specific HTTP behavior.

Credentials still live under `providers.<provider>` so chat channels, WebUI, and
desktop resolve API keys and API bases the same way.

1. Add provider credentials to `ProvidersConfig`.

```python
class ProvidersConfig(BaseModel):
    ...
    my_stt: ProviderConfig = Field(default_factory=ProviderConfig)
```

2. Add a `ProviderSpec` in `nanobot/providers/registry.py`.

For transcription-only providers, set `is_transcription_only=True` so they show up
in credential/settings surfaces but stay out of chat model selection.

```python
ProviderSpec(
    name="my_stt",
    keywords=("my_stt",),
    env_key="MY_STT_API_KEY",
    display_name="My STT",
    default_api_base="https://api.example.com/v1",
    is_transcription_only=True,
)
```

3. Add an adapter class in `nanobot/providers/transcription.py`.

Adapters receive resolved credentials and settings. They return an empty string
for provider errors so channel voice messages fail quietly instead of crashing the
agent loop.

```python
class MySTTTranscriptionProvider:
    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("MY_STT_API_KEY")
        self.api_base = api_base or "https://api.example.com/v1"
        self.language = language or None
        self.model = model or "my-default-stt-model"

    async def transcribe(self, file_path: str | Path) -> str:
        ...
```

4. Register the adapter in `nanobot/audio/transcription_registry.py`.

```python
TranscriptionProviderSpec(
    name="my_stt",
    default_model="my-default-stt-model",
    adapter="nanobot.providers.transcription:MySTTTranscriptionProvider",
    aliases=("mystt",),
)
```

5. Add tests.

At minimum, cover:

- config resolution in `tests/providers/test_transcription.py`
- adapter request/response behavior and retry/error handling
- WebUI settings payload/update behavior in `tests/webui/test_settings_api.py`
- provider brand mapping if the provider appears in Settings

6. Update user-facing docs.

Add the provider to [`configuration.md`](./configuration.md) where users choose
`transcription.provider`, but keep implementation details in this development
guide.
