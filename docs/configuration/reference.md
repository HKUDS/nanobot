# Complete configuration reference

This page documents every option inside `~/.nanobot/config.json`, including expected types, default values, and usage notes.

> [!NOTE]
> Every key accepts both `camelCase` (for example `maxTokens`) and `snake_case` (`max_tokens`). You can mix styles in the same file.

---

## agents

The root node that controls agent behavior. It currently exposes the `defaults` section.

### agents.defaults

| Option | Type | Default | Description |
|------|------|--------|------|
| `workspace` | string | `~/.nanobot/workspace` | Workspace directory used for files, memory, and sessions (`~` is expanded) |
| `model` | string | `anthropic/claude-opus-4-5` | Default model in `provider/model-name` syntax |
| `provider` | string | `"auto"` | Force a provider or let nanobot auto-match from the model name |
| `max_tokens` | integer | `8192` | Maximum output tokens per LLM call |
| `context_window_tokens` | integer | `65536` | Context window size (tokens); triggers memory consolidation when exceeded |
| `temperature` | float | `0.1` | Sampling temperature (`0.0` deterministic, `1.0` random) |
| `max_tool_iterations` | integer | `40` | Maximum loop count through tools per request to prevent runaway iterations |
| `reasoning_effort` | string \| null | `null` | Thinking mode intensity: `"low"`, `"medium"`, `"high"`. Set to `null` to disable |

#### workspace

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace"
    }
  }
}
```

Nanobot reads/writes files, executes shell commands, and stores memory & session data inside this directory. When `tools.restrict_to_workspace` is enabled, all tool access is sandboxed to this path.

#### model

```json
{
  "agents": {
    "defaults": {
      "model": "openrouter/anthropic/claude-opus-4-5"
    }
  }
}
```

Model strings depend on the provider:

| Format | Example | Use case |
|------|------|----------|
| `provider/model` | `anthropic/claude-opus-4-5` | Standard LiteLLM syntax |
| `model-only` | `llama3.2` | Local models (Ollama) |
| Deployment name | `my-gpt4-deployment` | Azure OpenAI deployments |

#### provider

```json
{
  "agents": {
    "defaults": {
      "provider": "ollama"
    }
  }
}
```

`"auto"` (default) matches providers based on model prefixes and keywords. Set to a specific name (e.g., `"anthropic"`, `"openrouter"`) to force routing.

#### reasoning_effort

```json
{
  "agents": {
    "defaults": {
      "reasoning_effort": "high"
    }
  }
}
```

Enable Extended Thinking on models that support it (Claude Sonnet 3.7+). Set to `null` or omit the field to disable.

---

## channels

Root node for channel configurations. Besides shared global options, each platform (e.g., `"telegram"`, `"slack"`) owns its own subsection parsed by that adapter.

### Global channel options

| Option | Type | Default | Description |
|------|------|--------|------|
| `send_progress` | bool | `true` | Stream the agent’s textual progress into the channel |
| `send_tool_hints` | bool | `false` | Surface tool hints such as `read_file("…")` |

```json
{
  "channels": {
    "send_progress": true,
    "send_tool_hints": false,
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["123456789"]
    }
  }
}
```

### Shared channel fields

Most channels accept these options (some platforms add extra fields):

| Field | Type | Default | Description |
|------|------|--------|------|
| `enabled` | bool | `false` | Enable the channel |
| `allowFrom` | list[string] | `[]` | Whitelist of sender IDs. Empty denies all; `["*"]` allows everyone |

> [!WARNING]
> `allowFrom` defaults to an empty array, which denies all users. Whitelist the IDs you expect to interact with so the bot can reply.

---

## providers

Root node for LLM providers. Each provider key maps to an object with `api_key`, `api_base`, and optional `extra_headers`.

### ProviderConfig fields

| Field | Type | Default | Description |
|------|------|--------|------|
| `api_key` | string | `""` | API key |
| `api_base` | string \| null | `null` | Custom API endpoint URL |
| `extra_headers` | dict \| null | `null` | Additional HTTP headers (e.g., `APP-Code`) |

### Supported providers

| Provider key | Description | Get API key |
|----------|------|--------------|
| `custom` | Any OpenAI-compatible endpoint (direct, bypassing LiteLLM) | — |
| `anthropic` | Claude models (direct) | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT models (direct) | [platform.openai.com](https://platform.openai.com) |
| `openrouter` | Unified gateway covering 300+ models (recommended) | [openrouter.ai](https://openrouter.ai) |
| `azure_openai` | Azure OpenAI (set `model` to your deployment name) | [portal.azure.com](https://portal.azure.com) |
| `deepseek` | DeepSeek models (direct) | [platform.deepseek.com](https://platform.deepseek.com) |
| `gemini` | Google Gemini | [aistudio.google.com](https://aistudio.google.com) |
| `groq` | Groq LLM + Whisper STT | [console.groq.com](https://console.groq.com) |
| `moonshot` | Moonshot / Kimi | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `minimax` | MiniMax | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `zhipu` | Zhipu GLM | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `dashscope` | Alibaba DashScope (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `siliconflow` | SiliconFlow | [siliconflow.cn](https://siliconflow.cn) |
| `aihubmix` | AiHubMix gateway | [aihubmix.com](https://aihubmix.com) |
| `volcengine` | VolcEngine (pay-as-you-go) | [volcengine.com](https://www.volcengine.com) |
| `volcengine_coding_plan` | VolcEngine Coding Plan (subscription) | — |
| `byteplus` | BytePlus (international VolcEngine) | [byteplus.com](https://www.byteplus.com) |
| `byteplus_coding_plan` | BytePlus Coding Plan (subscription) | — |
| `mistral` | Mistral AI | [console.mistral.ai](https://console.mistral.ai) |
| `ollama` | Local Ollama models | — |
| `vllm` | Local vLLM or any OpenAI-compatible server | — |
| `openai_codex` | OpenAI Codex (OAuth, requires ChatGPT Plus/Pro) | `nanobot provider login openai-codex` |
| `github_copilot` | GitHub Copilot (OAuth) | `nanobot provider login github-copilot` |

### Examples

**Anthropic (direct):**

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  }
}
```

**OpenRouter (gateway to every supported model):**

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-..."
    }
  },
  "agents": {
    "defaults": {
      "model": "openrouter/anthropic/claude-opus-4-5"
    }
  }
}
```

**Custom OpenAI-compatible endpoint:**

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

> [!TIP]
> For local servers without authentication, set `apiKey` to any non-empty string (e.g., `"no-key"`).

**AiHubMix (requires `extra_headers`):**

```json
{
  "providers": {
    "aihubmix": {
      "apiKey": "your-key",
      "extraHeaders": {
        "APP-Code": "your-app-code"
      }
    }
  }
}
```

**Ollama (local):**

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434"
    }
  },
  "agents": {
    "defaults": {
      "provider": "ollama",
      "model": "llama3.2"
    }
  }
}
```

**Special `apiBase` overrides:**

| Provider | Situation | `apiBase` value |
|--------|---------|-------------|
| `zhipu` | Coding Plan endpoints | `https://open.bigmodel.cn/api/coding/paas/v4` |
| `minimax` | Mainland China access | `https://api.minimax.io/v1` |
| `dashscope` | Alibaba BaiLian compatibility | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

---

## gateway

HTTP gateway server settings.

| Option | Type | Default | Description |
|------|------|--------|------|
| `host` | string | `"0.0.0.0"` | Network interface to bind (all interfaces) |
| `port` | integer | `18790` | TCP port |
| `heartbeat.enabled` | bool | `true` | Enable the heartbeat service |
| `heartbeat.interval_s` | integer | `1800` | Heartbeat interval in seconds (default 30 minutes) |

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790,
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  }
}
```

> [!TIP]
> When running multiple instances, assign each a unique port (e.g., `18790`, `18791`, `18792`). Override it with `nanobot gateway --port 18791` if needed.

---

## tools

Root node for tool settings covering networking, shell execution, input limits, and MCP servers.

### tools.web

| Option | Type | Default | Description |
|------|------|--------|------|
| `proxy` | string \| null | `null` | HTTP/SOCKS5 proxy URL that routes search & fetch requests |

```json
{
  "tools": {
    "web": {
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

Supported values:
- HTTP proxy: `"http://127.0.0.1:7890"`
- SOCKS5 proxy: `"socks5://127.0.0.1:1080"`

### tools.web.search

| Option | Type | Default | Description |
|------|------|--------|------|
| `provider` | string | `"brave"` | Search backend: `"brave"`, `"tavily"`, `"duckduckgo"`, `"searxng"`, `"jina"` |
| `api_key` | string | `""` | API key for Brave or Tavily |
| `base_url` | string | `""` | Base URL for self-hosted SearXNG |
| `max_results` | integer | `5` | Number of results per search (recommended 1–10) |

#### Provider comparison

| Provider | Requires key | Free | Env var fallback |
|--------|---------|------|------------|
| `brave` (default) | yes | no | `BRAVE_API_KEY` |
| `tavily` | yes | no | `TAVILY_API_KEY` |
| `jina` | yes | yes (10M tokens) | `JINA_API_KEY` |
| `searxng` | no (self-hosted) | yes | `SEARXNG_BASE_URL` |
| `duckduckgo` | no | yes | — |

> [!NOTE]
> Without credentials, nanobot automatically falls back to DuckDuckGo.

**Brave (default):**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "brave",
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

**Jina (free tier):**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "jina",
        "apiKey": "jina_..."
      }
    }
  }
}
```

**SearXNG (self-hosted, no key):**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "searxng",
        "baseUrl": "https://searx.example.com"
      }
    }
  }
}
```

**DuckDuckGo (zero config):**

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

### tools.exec

| Option | Type | Default | Description |
|------|------|--------|------|
| `timeout` | integer | `60` | Shell command timeout (seconds) |
| `path_append` | string | `""` | Additional directories appended to `PATH` during execution |

```json
{
  "tools": {
    "exec": {
      "timeout": 120,
      "pathAppend": "/usr/local/sbin:/usr/sbin"
    }
  }
}
```

> [!TIP]
> Append directories containing commands the agent cannot find (e.g., `ufw`, `iptables`).

### tools.input_limits

| Option | Type | Default | Description |
|------|------|--------|------|
| `max_input_images` | integer | `3` | Max number of images per request |
| `max_input_image_bytes` | integer | `10485760` (10 MB) | Max bytes per image |

```json
{
  "tools": {
    "inputLimits": {
      "maxInputImages": 3,
      "maxInputImageBytes": 10485760
    }
  }
}
```

### tools.restrict_to_workspace

| Option | Type | Default | Description |
|------|------|--------|------|
| `restrict_to_workspace` | bool | `false` | When `true`, all tool access (shell, filesystem) is limited to the workspace directory |

```json
{
  "tools": {
    "restrictToWorkspace": true
  }
}
```

> [!WARNING]
> Enable this in production to prevent path traversal or access outside the workspace.

### tools.mcp_servers

Define MCP (Model Context Protocol) servers keyed by name.

> [!TIP]
> The format matches Claude Desktop / Cursor MCP configs, so you can reuse their README snippets.

#### MCPServerConfig fields

| Field | Type | Default | Description |
|------|------|--------|------|
| `type` | `"stdio"` \| `"sse"` \| `"streamableHttp"` \| null | `null` | Transport mode (auto-detected when omitted) |
| `command` | string | `""` | **Stdio mode:** command to run (e.g., `"npx"`) |
| `args` | list[string] | `[]` | **Stdio mode:** command arguments |
| `env` | dict[string, string] | `{}` | **Stdio mode:** extra environment variables |
| `url` | string | `""` | **HTTP/SSE mode:** endpoint URL |
| `headers` | dict[string, string] | `{}` | **HTTP/SSE mode:** custom headers |
| `tool_timeout` | integer | `30` | Timeout per tool call (seconds) |
| `enabled_tools` | list[string] | `"["*""` | Tools to register; `"["*""` means all, `[]` means none |

#### Detecting transport

| Condition | Transport |
|------|---------|
| `command` present | `stdio` |
| `url` ending with `/sse` | `sse` |
| Other `url` | `streamableHttp` |

#### Stdio example

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "git": {
        "command": "uvx",
        "args": ["mcp-server-git", "--repository", "/path/to/repo"]
      }
    }
  }
}
```

#### HTTP/SSE example

```json
{
  "tools": {
    "mcpServers": {
      "my-remote-mcp": {
        "url": "https://example.com/mcp/",
        "headers": {
          "Authorization": "Bearer xxxxx"
        }
      }
    }
  }
}
```

#### Custom timeout

```json
{
  "tools": {
    "mcpServers": {
      "slow-service": {
        "url": "https://example.com/mcp/",
        "toolTimeout": 120
      }
    }
  }
}
```

#### Tool filtering

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
        "enabledTools": ["read_file", "mcp_filesystem_write_file"]
      }
    }
  }
}
```

`enabled_tools` accepts MCP-native names (e.g., `read_file`) or nanobot-wrapped names (`mcp_filesystem_read_file`).

| Value | Behavior |
|-------------------|------|
| `"["*""` | Register all tools |
| `[]` | Register no tools (disable the server temporarily) |
| `["tool_a", "tool_b"]` | Register only the listed tools |

---

## Full configuration example

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "provider": "auto",
      "maxTokens": 8192,
      "contextWindowTokens": 65536,
      "temperature": 0.1,
      "maxToolIterations": 40,
      "reasoningEffort": null
    }
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    },
    "slack": {
      "enabled": false,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "allowFrom": ["U01234567"]
    },
    "discord": {
      "enabled": false,
      "token": "YOUR_DISCORD_BOT_TOKEN",
      "allowFrom": ["123456789012345678"]
    }
  },
  "providers": {
    "anthropic": { "apiKey": "sk-ant-..." },
    "openai": { "apiKey": "sk-..." },
    "openrouter": { "apiKey": "sk-or-v1-..." },
    "deepseek": { "apiKey": "sk-..." },
    "gemini": { "apiKey": "AIza..." },
    "groq": { "apiKey": "gsk_..." },
    "ollama": { "apiBase": "http://localhost:11434" },
    "custom": {
      "apiKey": "your-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790,
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  },
  "tools": {
    "web": {
      "proxy": null,
      "search": {
        "provider": "brave",
        "apiKey": "BSA...",
        "baseUrl": "",
        "maxResults": 5
      }
    },
    "exec": {
      "timeout": 60,
      "pathAppend": ""
    },
    "inputLimits": {
      "maxInputImages": 3,
      "maxInputImageBytes": 10485760
    },
    "restrictToWorkspace": false,
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
        "toolTimeout": 30,
        "enabledTools": ["*"]
      },
      "remote-api": {
        "url": "https://mcp.example.com/sse",
        "headers": {
          "Authorization": "Bearer token"
        },
        "toolTimeout": 60,
        "enabledTools": ["search", "fetch"]
      }
    }
  }
}
```
