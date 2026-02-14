# Model Paths and Providers

This document explains how model paths are defined when using different LLM providers in Nanobot.

## Overview

Nanobot uses a unified provider system that supports 100+ models through LiteLLM. The provider registry (`nanobot/providers/registry.py`) is the single source of truth for all provider-specific behavior, including:

- **Model prefixing**: How model names are transformed for LiteLLM
- **API key mapping**: Environment variables and configuration keys
- **Gateway detection**: Special handling for API gateways
- **Local deployments**: Support for self-hosted models (vLLM, Ollama)
- **Parameter overrides**: Provider-specific model parameter adjustments

## Provider Types

### 1. Gateway Providers

Gateways can route any model from multiple providers through a single API. They are detected by `api_key` prefix or `api_base` URL, not by model name.

#### OpenRouter

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-..."
    }
  }
}
```

- **Detection**: API keys starting with `sk-or-`
- **Model prefixing**: `claude-3` → `openrouter/claude-3`
- **Default API base**: `https://openrouter.ai/api/v1`

#### AiHubMix

```json
{
  "providers": {
    "aihubmix": {
      "apiKey": "your-key",
      "apiBase": "https://aihubmix.com/v1"
    }
  }
}
```

- **Detection**: URL contains `aihubmix`
- **Model prefixing**: Strips provider prefix, then adds `openai/`
  - `anthropic/claude-3` → `claude-3` → `openai/claude-3`
- **Uses OpenAI-compatible interface**

### 2. Standard Providers

Standard providers are matched by model name keywords. Each provider may require specific prefixing for LiteLLM routing.

#### Anthropic (Claude)

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5"
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  }
}
```

- **Keywords**: `anthropic`, `claude`
- **Model prefixing**: None (LiteLLM recognizes `claude-*` natively)
- **Environment variable**: `ANTHROPIC_API_KEY`

#### OpenAI

```json
{
  "agents": {
    "defaults": {
      "model": "gpt-4o"
    }
  },
  "providers": {
    "openai": {
      "apiKey": "sk-..."
    }
  }
}
```

- **Keywords**: `openai`, `gpt`
- **Model prefixing**: None (LiteLLM recognizes `gpt-*` natively)
- **Environment variable**: `OPENAI_API_KEY`

#### DeepSeek

```json
{
  "agents": {
    "defaults": {
      "model": "deepseek-chat"
    }
  },
  "providers": {
    "deepseek": {
      "apiKey": "your-deepseek-key"
    }
  }
}
```

- **Keywords**: `deepseek`
- **Model prefixing**: Adds `deepseek/` prefix
  - `deepseek-chat` → `deepseek/deepseek-chat`
- **Environment variable**: `DEEPSEEK_API_KEY`

#### Zhipu AI (GLM)

```json
{
  "agents": {
    "defaults": {
      "model": "glm-4"
    }
  },
  "providers": {
    "zhipu": {
      "apiKey": "your-zhipu-key",
      "apiBase": "https://api.z.ai/api/coding/paas/v4"
    }
  }
}
```

- **Keywords**: `zhipu`, `glm`, `zai`
- **Model prefixing**: Adds `zai/` prefix
  - `glm-4` → `zai/glm-4`
- **Environment variables**: `ZAI_API_KEY`, `ZHIPUAI_API_KEY`

#### DashScope (Qwen)

```json
{
  "agents": {
    "defaults": {
      "model": "qwen-max"
    }
  },
  "providers": {
    "dashscope": {
      "apiKey": "your-dashscope-key"
    }
  }
}
```

- **Keywords**: `qwen`, `dashscope`
- **Model prefixing**: Adds `dashscope/` prefix
  - `qwen-max` → `dashscope/qwen-max`
- **Environment variable**: `DASHSCOPE_API_KEY`

#### Moonshot (Kimi)

```json
{
  "agents": {
    "defaults": {
      "model": "kimi-k2.5"
    }
  },
  "providers": {
    "moonshot": {
      "apiKey": "your-moonshot-key",
      "apiBase": "https://api.moonshot.ai/v1"
    }
  }
}
```

- **Keywords**: `moonshot`, `kimi`
- **Model prefixing**: Adds `moonshot/` prefix
  - `kimi-k2.5` → `moonshot/kimi-k2.5`
- **Special handling**: Kimi K2.5 requires `temperature >= 1.0`
- **Environment variable**: `MOONSHOT_API_KEY`, `MOONSHOT_API_BASE`

#### MiniMax

```json
{
  "agents": {
    "defaults": {
      "model": "MiniMax-M2.1"
    }
  },
  "providers": {
    "minimax": {
      "apiKey": "your-minimax-key"
    }
  }
}
```

- **Keywords**: `minimax`
- **Model prefixing**: Adds `minimax/` prefix
  - `MiniMax-M2.1` → `minimax/MiniMax-M2.1`
- **Default API base**: `https://api.minimax.io/v1`
- **Environment variable**: `MINIMAX_API_KEY`

#### Gemini

```json
{
  "agents": {
    "defaults": {
      "model": "gemini-pro"
    }
  },
  "providers": {
    "gemini": {
      "apiKey": "your-gemini-key"
    }
  }
}
```

- **Keywords**: `gemini`
- **Model prefixing**: Adds `gemini/` prefix
  - `gemini-pro` → `gemini/gemini-pro`
- **Environment variable**: `GEMINI_API_KEY`

### 3. Local Deployments

Self-hosted models running locally or on your own infrastructure.

#### vLLM / OpenAI-Compatible Local Servers

```json
{
  "agents": {
    "defaults": {
      "model": "Llama-3-8B"
    }
  },
  "providers": {
    "vllm": {
      "apiKey": "your-vllm-key",
      "apiBase": "http://192.168.88.113:8317/v1"
    }
  }
}
```

- **Detection**: Config key must be `"vllm"` (provider name)
- **Model prefixing**: Adds `hosted_vllm/` prefix
  - `Llama-3-8B` → `hosted_vllm/Llama-3-8B`
- **Environment variable**: `HOSTED_VLLM_API_KEY`
- **Note**: You must provide the `apiBase` URL in your config

### 4. Auxiliary Providers

Providers that are primarily used for specific functions (like transcription) but can also serve LLM requests.

#### Groq

```json
{
  "providers": {
    "groq": {
      "apiKey": "your-groq-key"
    }
  }
}
```

- **Keywords**: `groq`
- **Model prefixing**: Adds `groq/` prefix
  - `llama3-8b-8192` → `groq/llama3-8b-8192`
- **Primary use**: Whisper voice transcription
- **Environment variable**: `GROQ_API_KEY`

## Model Path Resolution Flow

The model name is resolved through the following steps:

```
1. User specifies model (e.g., "glm-4")
   ↓
2. Check if gateway is active
   ├─ Yes: Apply gateway prefix (e.g., "openrouter/")
   │         Optionally strip existing provider prefix
   └─ No: Continue to step 3
   ↓
3. Match model against provider keywords
   ├─ Match found: Apply provider prefix if needed
   │               Check skip_prefixes to avoid double-prefixing
   └─ No match: Use model as-is
   ↓
4. Apply model-specific parameter overrides
   ↓
5. Set environment variables for API keys
   ↓
6. Call LiteLLM with resolved model name
```

### Example Transformations

| User Input | Gateway | Provider | Final Model |
|------------|---------|----------|-------------|
| `claude-3` | None | Anthropic | `claude-3` (no change) |
| `claude-3` | OpenRouter | - | `openrouter/claude-3` |
| `deepseek-chat` | None | DeepSeek | `deepseek/deepseek-chat` |
| `glm-4` | AiHubMix | Zhipu | `openai/glm-4` |
| `Llama-3-8B` | None | vLLM | `hosted_vllm/Llama-3-8B` |
| `kimi-k2.5` | None | Moonshot | `moonshot/kimi-k2.5` |

## Configuration Schema

Each provider is configured in `~/.nanobot/config.json`:

```json
{
  "agents": {
    "defaults": {
      "model": "your-model-name",
      "maxTokens": 8192,
      "temperature": 0.7
    }
  },
  "providers": {
    "provider-key": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.example.com/v1"
    }
  }
}
```

### Field Descriptions

- `model`: The model identifier (e.g., `gpt-4o`, `claude-opus-4-5`)
- `apiKey`: API key for the provider
- `apiBase`: Optional custom API endpoint URL
- `maxTokens`: Maximum tokens in the response
- `temperature`: Sampling temperature (0.0 - 1.0, depends on model)

## Adding a New Provider

To add support for a new provider:

1. **Add provider spec to registry** (`nanobot/providers/registry.py`):

```python
ProviderSpec(
    name="newprovider",
    keywords=("newprovider", "model-keyword"),
    env_key="NEWPROVIDER_API_KEY",
    display_name="New Provider",
    litellm_prefix="newprovider",        # "model" → "newprovider/model"
    skip_prefixes=("newprovider/",),    # avoid double-prefix
    env_extras=(),
    is_gateway=False,
    is_local=False,
    detect_by_key_prefix="",
    detect_by_base_keyword="",
    default_api_base="https://api.newprovider.com/v1",
    strip_model_prefix=False,
    model_overrides=(),
)
```

2. **Add config field** (`nanobot/config/schema.py`):

```python
class ProvidersConfig(BaseModel):
    # ... existing providers ...
    newprovider: Optional[ProviderConfig] = None
```

3. **That's it!** The system will automatically:
   - Set the correct environment variables
   - Apply model prefixing
   - Match by keywords
   - Display correctly in `nanobot status`

## Provider Matching Logic

See `nanobot/config/schema.py` (lines 261-307) for the complete matching logic:

1. **Gateway/local providers**: Matched by `provider_name`, `api_key` prefix, or `api_base` keyword
2. **Standard providers**: Matched by model name keywords
3. **Fallback order**: Gateways → Standard providers (by registry order)

## Related Files

- `nanobot/providers/registry.py` - Provider specifications and matching logic
- `nanobot/providers/litellm_provider.py` - LiteLLM provider implementation
- `nanobot/config/schema.py` - Configuration schema including provider config
- `nanobot/providers/base.py` - Base provider interface

## Free Web Search Providers

Nanobot supports multiple **free search providers** that don't require API keys:

### DuckDuckGo (Default)

- **Engine**: `ddg_search` or `web_search(engine="ddg")`
- **No API key required**
- **Best for**: General web search, privacy-focused
- **Installation**: `pip install duckduckgo-search`

### SearXNG

- **Engine**: `web_search(engine="searxng")` (not available as standalone tool)
- **No API key required** (if using public SearXNG instance)
- **Features**:
  - Aggregates 70+ search engines (Google, Bing, Brave, DuckDuckGo, etc.)
  - Privacy-focused with no tracking
  - JSON format
  - Rate limit: generous
- **Best for**: Comprehensive results, privacy, research
- **API**: [SearXNG Documentation](https://docs.searxng.org)
- **Self-hosted option**: Run your own instance for complete privacy

### Wikipedia

- **Engine**: `web_search(engine="wikipedia")` (not available as standalone tool)
- **No API key required**
- **Features**:
  - Full-text search of Wikipedia articles
  - Encyclopedic, factual knowledge
  - JSON output
  - Unlimited free queries
- **Best for**: Factual queries, definitions, research, learning
- **API**: [Wikipedia API](https://www.mediawiki.org/wiki/API:Main_page)

### Combine Mode (Search All Engines)

- **Engine**: `web_search(combine=True)` or `web_search(engine="combine")`
- **No API key required** for free engines (DuckDuckGo, SearXNG, Wikipedia)
- **Features**:
  - Searches all available engines simultaneously
  - Combines results from all successful searches
  - Best coverage and redundancy
  - Falls back gracefully if engines fail
- **Best for**: Maximum results, research, comprehensive queries

### Quick Comparison

| Provider | API Key | Engine Name | Best For |
|---|---|---|---|---|
| **DuckDuckGo** | ❌ No | `ddg_search` or `engine="ddg"` | General web search |
| **SearXNG** | ❌ No | `engine="searxng"` | Privacy, research |
| **Wikipedia** | ❌ No | `engine="wikipedia"` | Facts, definitions |
| **Brave** | ✅ Yes | `engine="brave"` | Fast, accurate |
| **Combine** | ❌ No (free) | `combine=True` or `engine="combine"` | All engines at once |
| **Google CSE** | ✅ Yes | `engine="google"` | Google results |

### Usage Examples

```python
# Use DuckDuckGo (default, free)
await ddg_search("python async tutorial")

# Use SearXNG (free, privacy-focused)
await searxng_search("climate change research")

# Use Wikipedia (free, factual)
await wikipedia_search("quantum physics")

# Use web_search with auto-selection (tries Brave, falls back to DuckDuckGo)
await web_search("best AI tools 2026", engine="auto")
```

## Further Reading

- [ARCHITECTURE.md](./ARCHITECTURE.md) - Overall system architecture
- [STRUCTURE.md](./STRUCTURE.md) - Detailed code structure
- [README.md](../README.md) - Project overview and setup
