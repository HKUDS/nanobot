# How to Configure Web Search for a nanobot AI Agent

nanobot includes built-in web search and web fetch tools. Search uses
DuckDuckGo by default and can be configured for API-backed or self-hosted
providers.

## What you will build

- web tools enabled in nanobot
- one search provider selected in the WebUI or `config.json`
- optional web fetch settings for page reading

## When to use this

Configure web search when the agent needs current information, public web
research, source discovery, or page fetching during a task.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

Web tools are enabled by default. Configure them only when you want a specific
provider, API key, proxy, fetch behavior, or SSRF allowlist.

## Minimal working example

For local interactive setup:

1. Run `nanobot webui`.
2. Open **Settings → Web**.
3. Enable web search, choose a provider, and enter its API key if required.
4. Save and restart when prompted.
5. Ask a question that requires current information and inspect the cited sources.

For manual or deployment-managed config, use the default search provider:

```json
{
  "tools": {
    "web": {
      "enable": true,
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

Or use an API-backed provider:

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "${BRAVE_API_KEY}"
      }
    }
  }
}
```

Ask a question that requires current information and inspect the tool activity
in the WebUI or logs.

## Production notes

- Keep API keys in environment variables.
- Set `maxResults` when you need fewer or more search results per query.
- Set `tools.web.proxy` only to a proxy you trust.
- Local page conversion is the default. Set `fetch.useJinaReader: true` only when you intend to share eligible URLs with Jina Reader.

## Security notes

- Web fetch and HTTP MCP share an SSRF guard.
- Private, loopback, link-local, and cloud metadata addresses are blocked by
  default.
- Add `tools.ssrfWhitelist` only for narrow trusted CIDRs.
- Do not give public chat users unrestricted web and shell access without
  review.

## Troubleshooting

- If search returns no results, switch provider or check the provider API key.
- If fetch is blocked, inspect the target URL and SSRF whitelist.
- If a proxy changes network behavior, verify `NO_PROXY` and proxy settings.

## Related nanobot docs

- [Configuration: Web Tools](../configuration.md#web-tools)
- [Security](../configuration.md#security)
- [WebUI](../webui.md)
