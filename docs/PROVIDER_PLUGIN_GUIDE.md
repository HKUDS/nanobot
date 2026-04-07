# Provider Plugin Guide

Build a custom nanobot provider plugin with a public, supported registry surface.

This guide covers the PR 1 provider plugin API introduced under `nanobot.plugins.providers`.

## What PR 1 Provides

nanobot now exposes a small public provider extension surface:

- `ProviderSpec` for public provider metadata
- `ProviderFactory` for custom provider construction
- runtime registration helpers for tests and embedded usage
- entry-point discovery for packaged plugins
- explicit fallback: if a plugin factory fails, nanobot logs and falls back to the native provider path
- a shared helper to apply nanobot generation defaults to plugin-created providers

## Entry Point Groups

Provider plugins use two Python entry-point groups:

- `nanobot.provider_specs`: publishes a `ProviderSpec`
- `nanobot.providers`: publishes a callable `ProviderFactory`

The entry-point name is normalized with the same rules as provider names in config: hyphens and camelCase become snake_case.

## Quick Start Example

This example adds a new provider named `demo_cloud`.

### Project Structure

```text
nanobot-provider-demo/
├── nanobot_provider_demo/
│   ├── __init__.py
│   ├── factory.py
│   └── spec.py
└── pyproject.toml
```

### 1. Declare the ProviderSpec

```python
# nanobot_provider_demo/spec.py
from nanobot.plugins.providers import ProviderSpec

PROVIDER_SPEC = ProviderSpec(
    name="demo_cloud",
    keywords=("demo-cloud", "demo"),
    env_key="DEMO_CLOUD_API_KEY",
    display_name="Demo Cloud",
    backend="openai_compat",
    default_api_base="https://api.demo-cloud.example/v1",
)
```

### 2. Implement the Factory

```python
# nanobot_provider_demo/factory.py
from nanobot.plugins.providers import apply_generation_defaults
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def make_demo_cloud_provider(*, config, model, spec):
    provider = OpenAICompatProvider(
        api_key=config.api_key if config else None,
        api_base=config.api_base if config and config.api_base else spec.default_api_base,
        default_model=model,
        extra_headers=config.extra_headers if config else None,
        spec=spec,
    )
    return provider
```

If you build your own provider class, nanobot will still apply generation defaults after the factory returns.

### 3. Register Entry Points

```toml
[project]
name = "nanobot-provider-demo"
version = "0.1.0"
dependencies = ["nanobot-ai>=0.1.5"]

[project.entry-points."nanobot.provider_specs"]
demo-cloud = "nanobot_provider_demo.spec:PROVIDER_SPEC"

[project.entry-points."nanobot.providers"]
demo-cloud = "nanobot_provider_demo.factory:make_demo_cloud_provider"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

### 4. Configure nanobot

```json
{
  "agents": {
    "defaults": {
      "provider": "demo-cloud",
      "model": "demo-cloud/chat-pro"
    }
  },
  "providers": {
    "demo-cloud": {
      "apiKey": "demo-secret",
      "apiBase": "https://api.demo-cloud.example/v1",
      "extraHeaders": {
        "X-Tenant": "team-a"
      },
      "region": "cn-hz"
    }
  }
}
```

Notes:

- nanobot normalizes `demo-cloud`, `demo_cloud`, and `demoCloud` to the same provider name
- plugin provider sections are accepted as extra config entries under `providers`
- plugin-specific fields like `region` are preserved on the config object for the factory to read

### 5. Run nanobot

```bash
pip install -e .
nanobot status
nanobot agent
```

If the plugin factory cannot initialize, nanobot keeps the process alive and falls back to the native provider path.

## Runtime Registration Example

For tests or embedded usage, you can register a provider without packaging an entry point:

```python
from nanobot.plugins.providers import (
    ProviderSpec,
    register_provider_factory,
    register_provider_spec,
)


register_provider_spec(
    ProviderSpec(
        name="demo_cloud",
        keywords=("demo",),
        env_key="DEMO_CLOUD_API_KEY",
        display_name="Demo Cloud",
    )
)


def make_demo_cloud_provider(*, config, model, spec):
    ...


register_provider_factory("demo-cloud", make_demo_cloud_provider)
```

This path is useful for unit tests and for applications embedding nanobot as a library.