# Web Search Providers

NanoBot supports multiple web search providers. Configure in `~/.nanobot/config.json` under `tools.web.search`.

| Provider | Key | Env var |
|----------|-----|---------|
| `brave` (default) | `apiKey` | `BRAVE_API_KEY` |
| `tavily` | `apiKey` | `TAVILY_API_KEY` |
| `searxng` | `baseUrl` | `SEARXNG_BASE_URL` |
| `duckduckgo` | — | — |

Each provider uses the same `apiKey` field — set the provider and key together. If no provider is specified but `apiKey` is given, Brave is assumed.

When credentials are missing and `fallbackToDuckduckgo` is `true` (the default), searches fall back to DuckDuckGo automatically.

## Examples

**Brave** (default — just set the key):

```json
{
  "tools": {
    "web": {
      "search": {
        "apiKey": "BSA..."
      }
    }
  }
}
```

**Tavily:**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "tavily",
        "apiKey": "tvly-..."
      }
    }
  }
}
```

**SearXNG** (self-hosted, no API key needed):

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "searxng",
        "baseUrl": "https://searx.example"
      }
    }
  }
}
```

**DuckDuckGo** (no credentials required):

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

## Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `provider` | string | `"brave"` | Search backend |
| `apiKey` | string | `""` | API key for the selected provider |
| `baseUrl` | string | `""` | Base URL for SearXNG (appends `/search`) |
| `maxResults` | integer | `5` | Default results per search |
| `fallbackToDuckduckgo` | boolean | `true` | Fall back to DuckDuckGo when credentials are missing |

## Custom providers

Plugins can register additional providers at runtime via the dispatch dict:

```python
async def my_search(query: str, n: int) -> str:
    ...

tool._provider_dispatch["my-engine"] = my_search
```
