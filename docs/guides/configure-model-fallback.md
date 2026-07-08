# How to Configure Model Fallback in nanobot

Model fallback lets nanobot try a primary model first, then fall back to one or
more named presets when the primary provider fails or rate-limits.

## What you will build

- two or more `modelPresets`
- a primary `agents.defaults.modelPreset`
- an ordered `agents.defaults.fallbackModels` chain

## When to use this

Use fallback when you want better reliability across rate limits, provider
outages, local model downtime, or cost-sensitive routing.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

Verify each provider works before adding it as a fallback.

## Minimal working example

Merge this shape into `~/.nanobot/config.json` and replace provider/model names
with ones you control:

```json
{
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "provider": "primary-provider",
      "model": "primary-model-id",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "deep": {
      "label": "Deep",
      "provider": "fallback-provider",
      "model": "fallback-model-id",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": ["deep"]
    }
  }
}
```

String entries in `fallbackModels` are preset names, not raw model IDs.
Replace the placeholder model IDs with currently supported model IDs from your
provider. The [Provider Cookbook](../provider-cookbook.md) has concrete recipes
for common providers.

## Production notes

- Keep fallback context windows realistic; smaller fallback windows constrain
  how much context can fit.
- Put cheaper or faster fallbacks before expensive ones when acceptable.
- Use `/model <preset>` for runtime switching without editing config.
- Keep labels human-readable for WebUI model lists.

## Security notes

- Different providers may have different data handling policies.
- Do not put provider keys directly in shared config files.
- Confirm fallback models can safely receive the same prompts and files.

## Troubleshooting

- If a fallback never triggers, confirm the primary error is treated as
  retryable/fallbackable.
- If startup fails, check that each fallback string matches a key under
  `modelPresets`.
- If output is truncated after fallback, review `maxTokens` and
  `contextWindowTokens`.

## Related nanobot docs

- [Providers and Models](../providers.md)
- [Provider Cookbook: Fallback Presets](../provider-cookbook.md#recipe-fallback-presets)
- [Configuration: Model Fallbacks](../configuration.md#model-fallbacks)
