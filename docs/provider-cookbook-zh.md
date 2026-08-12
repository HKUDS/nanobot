# Provider 食谱

本页适用于您已经知道要连接什么，并且需要可直接粘贴的配置的情况。每个食谱都会说明要设置什么、要运行什么，以及失败通常意味着什么。

如果这是您第一次安装，且您不熟悉终端命令，请从 [`start-without-technical-background.md`](start-without-technical-background-zh.md) 开始。如果您想了解逐字段说明，请阅读 [`providers.md`](providers-zh.md)，然后阅读 [`configuration.md#providers`](configuration-zh.md#providers)。

下面的大多数示例都是要合并到 `~/.nanobot/config.json` 中的片段。保留您仍然需要的现有部分，并且仅在您自己的机器上将 `${OPENROUTER_API_KEY}` 等占位符密钥替换为环境变量引用或真实值。

食谱是示例，并非排名。请选择与您已经打算使用的凭据、endpoint 和 model ID 相匹配的食谱。

## 选择食谱

将食谱与您已有的凭据或 endpoint 相匹配：

| 您拥有的内容 | 食谱 | 必须匹配 |
|---|---|---|
| 一个 gateway 密钥和包含 model family 路径的 model ID，例如 `provider/model-name` | [OpenRouter Gateway](#recipe-openrouter-gateway) | API 密钥、provider 配置键、预设 provider 和 gateway model ID |
| 一个 OpenCode Zen 或 Go 密钥 | [OpenCode Zen 或 Go](#recipe-opencode-zen-or-go) | `OPENCODE_API_KEY`、Zen/Go provider 键，以及来自对应 OpenCode endpoint 的 model ID |
| 一个 OpenAI platform API 密钥和 OpenAI model ID | [OpenAI 直连](#recipe-openai-direct) | `OPENAI_API_KEY`、`provider: "openai"`，以及该账户可用的 OpenAI model |
| 一个 Anthropic API 密钥和 Anthropic model ID | [Anthropic 直连](#recipe-anthropic-direct) | `ANTHROPIC_API_KEY`、`provider: "anthropic"` 和非 gateway model ID |
| 一个 Kimi Coding Plan 密钥 | [Kimi Coding Plan](#recipe-kimi-coding-plan) | `KIMI_CODING_API_KEY`、`provider: "kimi_coding"` 和 `model: "kimi-for-coding"` |
| 一个不是已命名 nanobot provider 的 OpenAI-compatible `/v1` endpoint | [自定义 OpenAI-Compatible Provider](#recipe-custom-openai-compatible-provider) | `apiBase`、可选 API 密钥，以及该 endpoint 提供的 model ID |
| 已在本地运行的 Ollama | [Ollama 本地 Model](#recipe-ollama-local-model) | Ollama `apiBase`、已拉取的 model 名称和本地服务器可用性 |
| vLLM、LM Studio 或其他本地 OpenAI-compatible 服务器 | [vLLM 或 LM Studio](#recipe-vllm-or-lm-studio) | 本地 `/v1` 基础 URL、任何所需的密钥和所提供的 model 名称 |
| 一个主 model 加上一个或多个备用 model | [Fallback Presets](#recipe-fallback-presets) | 在 `modelPresets` 中命名的 presets，由 `agents.defaults.fallbackModels` 引用 |
| 一个可正常工作的 agent 和一个 Langfuse 项目 | [Langfuse Tracing](#recipe-langfuse-tracing) | 在启动 nanobot 的同一进程环境中的 Langfuse env vars |

## 如何使用食谱

1. 安装 nanobot 并运行一次 `nanobot onboard`，以便创建 `~/.nanobot/config.json`。如果您更喜欢提示操作而不是手动编辑 JSON，请使用 `nanobot onboard --wizard`。
2. 尽可能将密钥放在环境变量中。
3. 将食谱片段合并到 `~/.nanobot/config.json`。
4. 运行 `nanobot status`。
5. 运行 `nanobot agent -m "Hello!"`。
6. 如果 CLI 可用，再连接 WebUI、gateway 或聊天应用。

活动 model 通常应来自 `agents.defaults.modelPreset`，且该名称应指向 `modelPresets` 中的一个条目。直接使用 `agents.defaults.provider` 和 `agents.defaults.model` 仍适用于旧配置，但 presets 更易于切换，也更易于复用为 fallback。

## 密钥设置

环境变量可以避免将 API 密钥写入配置文件。

使用您所选食谱中显示的变量名称。下面的命令仅以 `OPENROUTER_API_KEY` 为例；OpenAI 直连食谱使用 `OPENAI_API_KEY`，Anthropic 直连食谱使用 `ANTHROPIC_API_KEY`，自定义 endpoint 可以使用您在 `config.json` 中引用的任何变量名称。

**macOS / Linux**

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
nanobot agent -m "Hello!"
```

**Windows PowerShell**

```powershell
$env:OPENROUTER_API_KEY = "sk-or-v1-..."
nanobot agent -m "Hello!"
```

以这种方式设置的环境变量仅适用于当前终端。对于 systemd、Docker、LaunchAgent 或远程 shell 等长期运行的服务，请在启动 nanobot 前在该服务环境中设置变量。

## 食谱：OpenRouter Gateway

当一个 API 密钥可路由多个托管 model family 时，适用此食谱。

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Primary",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

验证：

```bash
nanobot status
nanobot agent -m "Hello!"
```

如果出现 `401` 或 `unauthorized` 错误，请检查 `OPENROUTER_API_KEY` 在启动 nanobot 的同一终端或服务中是否可见。如果出现 `model not found` 错误，请选择 OpenRouter 为您的账户列出的 model ID。

## 食谱：OpenCode Zen 或 Go

当您的凭据来自 OpenCode Zen 或 OpenCode Go 时，适用此食谱。
两个 provider 都使用 `OPENCODE_API_KEY`；请选择与您希望使用的订阅或余额相匹配的 provider 块。

OpenCode Zen：

```json
{
  "providers": {
    "opencodeZen": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "OpenCode Zen",
      "provider": "opencode_zen",
      "model": "opencode/deepseek-v4-pro",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

OpenCode Go：

```json
{
  "providers": {
    "opencodeGo": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "OpenCode Go",
      "provider": "opencode_go",
      "model": "opencode-go/deepseek-v4-flash",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

验证：

```bash
nanobot status
nanobot agent -m "Hello!"
```

OpenCode 的文档列出了多种 endpoint 类型下的 models。nanobot 中的 `opencode_zen`
和 `opencode_go` providers 使用 OpenAI-compatible
`chat/completions` 路径。如果一个 model 出现 `model not found` 或 endpoint
格式错误，请从 OpenCode 为对应 Zen 或 Go endpoint 的 `chat/completions` 所列 models 中选择。

## 食谱：OpenAI 直连

当您拥有 OpenAI API 密钥，并希望直接调用 OpenAI 而不是通过 gateway 时，适用此食谱。

```json
{
  "providers": {
    "openai": {
      "apiKey": "${OPENAI_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "OpenAI",
      "provider": "openai",
      "model": "gpt-5",
      "maxTokens": 4096,
      "contextWindowTokens": 128000,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

验证：

```bash
OPENAI_API_KEY="sk-..." nanobot agent -m "Hello!"
```

如果您的 shell 无法使用内联环境变量，请先设置 `OPENAI_API_KEY`，然后运行 `nanobot agent -m "Hello!"`。如果 provider 拒绝 `apiType`，请移除 `apiType`，除非您正在使用已文档化的 OpenAI-specific 模式。

## 食谱：Anthropic 直连

当您的密钥来自 Anthropic，且您的 model 名称是 Anthropic model ID 而不是 OpenRouter model 路径时，适用此食谱。

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "${ANTHROPIC_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Anthropic",
      "provider": "anthropic",
      "model": "claude-sonnet-4-5",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

验证：

```bash
ANTHROPIC_API_KEY="sk-ant-..." nanobot agent -m "Hello!"
```

如果您复制了诸如 `anthropic/claude-sonnet-4.5` 的 model 名称，它是 gateway 风格的 model 路径，应配置在 `provider: "openrouter"` 下，而不是 `provider: "anthropic"`。

如果您使用 Anthropic-compatible proxy，请将 preset provider 保持为 `anthropic`，并设置 `providers.anthropic.apiBase`：

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "${ANTHROPIC_API_KEY}",
      "apiBase": "https://anthropic-proxy.example.com"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Anthropic proxy",
      "provider": "anthropic",
      "model": "claude-sonnet-4-5",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

不要将 Anthropic-compatible endpoints 配置为任意的自定义 provider 名称；已命名的自定义 providers 使用 OpenAI-compatible 请求格式。

## 食谱：Kimi Coding Plan

当您的密钥来自 Kimi 的 Coding Plan endpoint 时，适用此食谱。Nanobot 为该 Anthropic Messages API endpoint 使用专用的 `kimi_coding` provider；请勿将其配置为通用 `custom` provider。

```json
{
  "providers": {
    "kimiCoding": {
      "apiKey": "${KIMI_CODING_API_KEY}"
    }
  },
  "modelPresets": {
    "kimiCoding": {
      "label": "Kimi Coding",
      "provider": "kimi_coding",
      "model": "kimi-for-coding",
      "maxTokens": 4096,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "kimiCoding"
    }
  }
}
```

验证：

```bash
nanobot status
nanobot agent -m "Hello!"
```

默认基础 URL 为 `https://api.kimi.com/coding/v1`。该 endpoint 需要 Claude-compatible `User-Agent`；nanobot 默认发送 `claude-code/0.1.0`。如果您的账户需要不同的值，请使用 `providers.kimiCoding.extraHeaders.User-Agent` 覆盖它。
## 配方：自定义 OpenAI-Compatible Provider

本配方适用于与 OpenAI 兼容、但不是具名 nanobot provider 的服务。

```json
{
  "providers": {
    "custom": {
      "apiKey": "${CUSTOM_API_KEY}",
      "apiBase": "https://api.example.com/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Custom",
      "provider": "custom",
      "model": "provider-model-name",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

在归咎于 nanobot 之前先验证端点：

```bash
curl -sS https://api.example.com/v1/models
nanobot agent -m "Hello!"
```

`apiBase` 是 HTTP 基础 URL，不是模型名称。当服务要求时，请包含版本路径，例如 `/v1`。如果服务要求非空 key 但不会验证它，请使用占位符，例如 `"apiKey": "EMPTY"`。

对于多个自定义端点，不要复用单个 `custom` 块。在 `providers` 下为每个端点命名，并在 preset 中引用相同的名称：

```json
{
  "providers": {
    "workProxy": {
      "apiKey": "${WORK_PROXY_API_KEY}",
      "apiBase": "https://proxy.example.com/v1"
    },
    "lab-local": {
      "apiBase": "http://127.0.0.1:8000/v1"
    }
  },
  "modelPresets": {
    "work": {
      "label": "Work proxy",
      "provider": "workProxy",
      "model": "gpt-4o-mini",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "lab": {
      "label": "Lab local",
      "provider": "lab-local",
      "model": "served-model-name",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "work"
    }
  }
}
```

这些自定义名称的行为与直接的 OpenAI-compatible provider 相同：`apiBase` 是必需的；当端点允许匿名或占位凭据时，`apiKey` 是可选的；`apiType` 应保持未设置。它们不支持 Anthropic-compatible 端点；对于该场景，请使用带有 `apiBase` 的 `anthropic` provider。

## 配方：Ollama 本地模型

本配方适用于已安装 Ollama 且模型已拉取到本地的情况。

```bash
ollama serve
ollama pull llama3.2
```

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/v1"
    }
  },
  "modelPresets": {
    "local": {
      "label": "Local",
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 2048,
      "contextWindowTokens": 32768,
      "temperature": 0.2
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "local"
    }
  }
}
```

验证：

```bash
curl -sS http://localhost:11434/v1/models
nanobot agent -m "Hello!"
```

如果看到 `connection refused`，则 Ollama 未运行，或 `apiBase` 指向了错误的端口。如果每个响应都很慢，请尝试更小的本地模型或降低 `contextWindowTokens`。

如果直接的 Ollama 响应很快，但使用 tool 的 nanobot 回合反复评估
数千个 prompt token，则模型的聊天模板可能在请求之间移动其 tool
定义。请参阅
[改善 Ollama Tool-Calling Prompt Cache Reuse](guides/configure-ollama-prompt-cache-zh.md)
以获取诊断流程和可选的特定模型解决方法。

## 配方：vLLM 或 LM Studio

本配方适用于本地服务器暴露 OpenAI-compatible `/v1` API 的情况。

```json
{
  "providers": {
    "vllm": {
      "apiBase": "http://127.0.0.1:8000/v1",
      "apiKey": "EMPTY"
    }
  },
  "modelPresets": {
    "local": {
      "label": "Local",
      "provider": "vllm",
      "model": "served-model-name",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.2
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "local"
    }
  }
}
```

对于 LM Studio，请使用其本地基础 URL 和 provider 名称：

```json
{
  "providers": {
    "lmStudio": {
      "apiBase": "http://localhost:1234/v1"
    }
  },
  "modelPresets": {
    "local": {
      "label": "LM Studio",
      "provider": "lm_studio",
      "model": "local-model",
      "maxTokens": 2048,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "local"
    }
  }
}
```

配置 key 可以是 `lmStudio` 或 `lm_studio`，但 preset provider 应使用注册表名称 `lm_studio`。

## 配方：Fallback Preset

本配方适用于某个 provider 有时会限流、某个模型成本较高，或你希望使用本地备用模型的情况。

```json
{
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "deep": {
      "label": "Deep",
      "provider": "anthropic",
      "model": "claude-sonnet-4-5",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    },
    "local": {
      "label": "Local",
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 2048,
      "contextWindowTokens": 32768,
      "temperature": 0.2
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": ["deep", "local"]
    }
  }
}
```

`fallbackModels` 属于 `agents.defaults`。字符串条目是 preset 名称，而不是原始模型名称。nanobot 会先尝试活动 preset，然后按顺序尝试 fallback preset。

请保持 fallback 候选项切合实际。如果本地 fallback 的 context window 更小，nanobot 必须构建能适配活动链中最小 window 的 context。

## 配方：Langfuse Tracing

本配方适用于 agent 已能工作且你希望观察 OpenAI-compatible provider 调用的情况。

在运行 nanobot 的同一 Python 环境中安装可选包：

```bash
nanobot plugins enable langfuse
```

在启动 nanobot 前设置环境变量：

```bash
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
nanobot agent -m "Hello!"
```

PowerShell：

```powershell
$env:LANGFUSE_SECRET_KEY = "sk-lf-..."
$env:LANGFUSE_PUBLIC_KEY = "pk-lf-..."
$env:LANGFUSE_BASE_URL = "https://cloud.langfuse.com"
nanobot agent -m "Hello!"
```

Langfuse 不是 `config.json` 中的 model provider。它通过环境变量配置，并追踪受支持的 OpenAI-compatible provider 调用。不使用该 client 路径的原生 provider 可能不会生成 Langfuse OpenAI-wrapper trace。

## 配方：在运行时切换模型

在拥有多个 preset 并通过受支持的 channel 聊天后使用此方法。

```json
{
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536
    },
    "local": {
      "label": "Local",
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 2048,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast"
    }
  }
}
```

在聊天中：

```text
/model
/model local
/model fast
```

`/model` 会将选择存储在当前 session 中，而不会重写 `config.json`。
该选择会在重启后保留，不影响其他 session，并且进行中的
回合会继续使用其启动时使用的模型。

## 快速故障对照表

| 症状 | 通常意味着 | 首先检查 |
|---|---|---|
| `401`、`unauthorized` 或 `invalid API key` | key 缺失、错误、已过期，或位于错误的 provider 下 | 在同一终端或服务中输出或重新设置环境变量 |
| `model not found` | model ID 不属于选定的 provider 或 gateway | 对比 `modelPresets.<name>.provider` 和 `modelPresets.<name>.model` |
| `connection refused` | 本地服务器未运行，或 `apiBase` 的端口/路径错误 | 运行 `curl <apiBase>/models` |
| `provider not found` | Provider 名称拼写错误，或使用了 config key 而非注册表名称 | 使用如 `openrouter`、`openai`、`anthropic`、`ollama`、`vllm`、`lm_studio` 的名称 |
| Langfuse 未显示 trace | Env var 缺失、活动 Python 环境中未安装 `langfuse`，或 provider 路径为原生路径 | 运行 `python -m pip show langfuse`，并从同一环境重启 nanobot |

## 后续参考

| 需求 | 阅读 |
|---|---|
| 字段含义和 provider 解析 | [`providers.md`](providers-zh.md) |
| 完整 schema 和 provider 表 | [`configuration.md#providers`](configuration-zh.md#providers) |
| Langfuse 详情 | [`configuration.md#langfuse-observability`](configuration-zh.md#langfuse-observability) |
| 首次运行诊断 | [`troubleshooting.md`](troubleshooting-zh.md) |
