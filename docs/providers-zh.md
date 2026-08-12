# Provider 和模型

当第一条回复因 provider/model 不匹配而失败，或你想将具体配置示例调整为其他 provider 时，请使用本页面。如果你已经知道想使用哪个 provider，并且只需要可直接粘贴的配置，请使用 [`provider-cookbook.md`](provider-cookbook-zh.md)。

对于正常的本地配置，请在 WebUI 中打开 **设置 → 模型**，添加 provider 凭据、创建模型预设并选择活动模型。对于手动部署、本地 endpoint、provider 特定字段或问题诊断，请使用下面的 JSON。

对于每种配置，请回答三个问题：

1. 哪个 provider 拥有该凭据或 endpoint？
2. 该 provider 期望的模型名称是什么？
3. 该 provider 需要 `apiKey`、`apiBase`、OAuth 登录、云凭据，还是只需要本地服务器 URL？

建议为模型/provider 对使用命名的 `modelPresets` 条目，然后通过 `agents.defaults.modelPreset` 选择它。现有配置仍可直接使用 `agents.defaults.provider` 和 `agents.defaults.model`，但预设能让运行时 `/model` 切换和回退链更加清晰。设置期间请将 `provider` 固定在预设中；之后可以切换回 `"auto"`。

## 不要猜测，选择 Provider

文档展示具体的 provider 名称，是为了让 JSON 可以直接复制，而不是因为 nanobot 对 provider 进行排名。请从你实际控制的服务或 endpoint 开始：

| 如果你有…… | 配置…… |
|---|---|
| 来自托管 provider 或 gateway 的 API 密钥 | 该 provider 的 `providers.<name>.apiKey`，然后创建一个使用该 provider 名称和该服务模型 ID 的预设。 |
| OpenCode Zen 或 Go 密钥 | `providers.opencodeZen.apiKey` 或 `providers.opencodeGo.apiKey`，然后创建一个 `provider: "opencode_zen"` 或 `provider: "opencode_go"` 的预设。 |
| 公司代理或区域 endpoint | 匹配的 provider 配置块；如果代理提供 URL，还要配置 `apiBase`。 |
| 本地 OpenAI 兼容服务器 | 本地 provider 配置块，例如 `ollama`、`vllm`、`lmStudio` 或 `custom`，通常还要配置 `apiBase`。 |
| 基于 OAuth 的账户 | 运行匹配的 `nanobot provider login ...` 命令，然后在预设中显式选择该 provider。 |
| 还没有 provider | 根据账户访问权限、价格、区域可用性、隐私要求以及所需模型 ID，在 nanobot 外部选择一个 provider。然后带着它的密钥和模型 ID 返回。 |

## 最小结构

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4.5",
      "maxTokens": 8192,
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

provider 配置向 nanobot 提供凭据和 endpoint 详细信息。模型预设命名 provider/model 对。agent 默认配置选择正常轮次使用的命名预设。请同时替换示例中的 provider 和模型；将一个 provider 的 API 密钥与另一个 provider 的模型 ID 混用，是首次运行失败的最常见原因。

## Provider、模型、API 密钥和基础 URL

这些字段回答的是不同的问题：

| 字段 | 所在位置 | 含义 |
|---|---|---|
| `provider` | `modelPresets.<name>.provider` | 应由哪个 nanobot provider 适配器发送请求。 |
| `model` | `modelPresets.<name>.model` | 该 provider 或 gateway 期望的模型 ID。 |
| `apiKey` | `providers.<provider>.apiKey` | 该 provider 的凭据。对于机密信息，请使用 `${ENV_VAR}`。 |
| `apiBase` | `providers.<provider>.apiBase` | provider endpoint 的 HTTP 基础 URL。 |
| `proxy` | `providers.<provider>.proxy` | 仅用于此 provider 的可选 HTTP 代理。OpenAI 兼容 provider、OpenAI Codex 和 xAI OAuth 支持此配置。 |

对于 OpenRouter、Anthropic direct、OpenAI direct、Groq 或 Bedrock 等内置托管 provider，通常可以省略 `apiBase`，因为 nanobot 已知晓它们的默认 endpoint。对于 `custom`、本地 OpenAI 兼容服务器、provider 代理、区域 endpoint 或订阅 endpoint，请设置 `apiBase`。当 endpoint 要求版本路径时，请包含该路径，例如 `https://api.example.com/v1` 或 `http://localhost:11434/v1`。

当某个 provider 必须通过代理发送 HTTP 流量，但你又不想修改进程级别的 `HTTP_PROXY` / `HTTPS_PROXY` 时，请使用 `proxy`。nanobot 的 OpenAI 兼容客户端所支持的 provider 都支持此配置，包括 `openai`、`custom`、命名的自定义 provider、OpenRouter 风格的 gateway、本地 OpenAI 兼容服务器以及类似的注册表条目。`openai_codex` 和 `xai_grok` 也支持此配置，包括 OAuth 令牌交换/刷新和模型请求。`anthropic`、`bedrock`、`azure_openai` 和 `github_copilot` 等原生 provider 后端会拒绝 `proxy`；请改用它们各自 endpoint 特定的配置。

## 常见 Provider 模式

### OpenRouter Gateway

用于通过 OpenRouter 提供的模型 ID 的 gateway 风格配置。

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4.5",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

请严格使用 OpenRouter 列出的模型 ID。

### Eden AI Gateway

Eden AI 在 `https://api.edenai.run/v3` 提供 OpenAI 兼容的聊天补全 endpoint。请配置内置的 `edenai` provider，并使用 Eden AI 列出的完整 `provider/model` 标识符：

```json
{
  "providers": {
    "edenai": {
      "apiKey": "${EDENAI_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "edenai",
      "model": "anthropic/claude-sonnet-4-5",
      "maxTokens": 8192
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

Nanobot 会原样发送模型 ID，包括其中的 provider 前缀。请使用 Eden AI 的[模型列表](https://www.edenai.co/docs/v3/llms/listing-models)选择当前可用的模型。在 Eden AI API 密钥保存到 **设置 → 模型** 后，WebUI 也可以加载该目录。

### OpenCode Zen 和 Go

OpenCode Zen 和 OpenCode Go 是由 OpenCode 管理的、面向 coding-agent 模型的 gateway。它们共用 `OPENCODE_API_KEY`，但在 nanobot 中使用独立的 provider 配置键和默认基础 URL。

```json
{
  "providers": {
    "opencodeZen": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "opencode_zen",
      "model": "opencode/deepseek-v4-pro",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

对于 OpenCode Go，请切换 provider 配置块和预设：

```json
{
  "providers": {
    "opencodeGo": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "opencode_go",
      "model": "opencode-go/deepseek-v4-flash",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  }
}
```

OpenCode 使用 `opencode/<model-id>` 记录 Zen 的模型 ID，使用 `opencode-go/<model-id>` 记录 Go 的模型 ID。nanobot 接受这些前缀，并在向 OpenCode 发送请求前将其移除。请使用 OpenCode 在 `chat/completions` endpoint 下列出的模型 ID；仅在 `responses`、`messages` 或 provider 特定 endpoint 下列出的模型，不受此 OpenAI 兼容 provider 路径支持。

### Anthropic Direct

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "${ANTHROPIC_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "anthropic",
      "model": "claude-opus-4-5",
      "maxTokens": 8192,
      "contextWindowTokens": 200000
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

Anthropic direct 使用原生 Anthropic provider。除非 provider 是 OpenRouter，否则不要使用 OpenRouter 模型 ID。

如果使用 Anthropic 兼容代理，请保持 provider 为 `anthropic`，并覆盖 `apiBase`：

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
      "provider": "anthropic",
      "model": "claude-sonnet-4-5"
    }
  }
}
```

任意自定义 provider 名称仅兼容 OpenAI；它们不使用 Anthropic Messages API 请求格式。

### OpenAI Direct

```json
{
  "providers": {
    "openai": {
      "apiKey": "${OPENAI_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "openai",
      "model": "gpt-5",
      "maxTokens": 8192,
      "contextWindowTokens": 128000
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

当需要强制使用特定的 OpenAI API 接口时，可以设置 `providers.openai.apiType`。其他 provider 会拒绝 `apiType`；在 `providers.openai` 之外请保持未设置。请将模型替换为你的 OpenAI 账户可用的模型 ID。直接 OpenAI Responses、OpenAI Codex、Azure OpenAI Responses 以及符合条件的 GitHub Copilot 模型共享[不透明的 Responses 状态保留](configuration-zh.md#responses-state-and-compaction)；仅当后端支持时才启用原生压缩。WebUI 为 OpenAI web search、Codex Fast mode、DeepSeek web search 和 Grok X Search 提供原生 provider 开关。这些开关会将相应的原始 provider 请求字段写入 `extraBody`。

DeepSeek 是 OpenAI 兼容 provider 中的模型级例外：`deepseek-v4-flash` 会自动使用 DeepSeek 原生 Responses API，而 `deepseek-v4-pro` 仍使用 Chat Completions。其原生 `web_search` tool 默认启用，并会在 WebUI 聊天活动中显示其生命周期；将 `providers.deepseek.extraBody.tools` 设置为 `[]` 可将其禁用。
### 自定义 OpenAI-Compatible Endpoint

`custom` provider 适用于一个未由命名 provider 表示的 OpenAI-compatible endpoint。

```json
{
  "providers": {
    "custom": {
      "apiKey": "${CUSTOM_API_KEY}",
      "apiBase": "https://example.com/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "custom",
      "model": "provider-model-name",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

`custom` 不会推断默认 base URL。请设置 `apiBase`。

如果你有多个自定义 OpenAI-compatible endpoint，请在 `providers` 下为每个 endpoint 指定各自的 provider key，并在 model preset 中使用相同的 key。该 key 可以是适合你环境的名称，例如 `companyProxy`、`tenant-a` 或 `dev-local`。

```json
{
  "providers": {
    "companyProxy": {
      "apiKey": "${COMPANY_PROXY_API_KEY}",
      "apiBase": "https://llm-proxy.example.com/v1"
    },
    "tenant-a": {
      "apiBase": "https://tenant-a.example.com/v1"
    }
  },
  "modelPresets": {
    "company": {
      "provider": "companyProxy",
      "model": "gpt-4o-mini",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    },
    "tenantA": {
      "provider": "tenant-a",
      "model": "served-model-name",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "company"
    }
  }
}
```

自定义 provider key 会被视为直接 OpenAI-compatible provider。由于 nanobot 无法得知 endpoint URL，因此必须提供 `apiBase`。对于不需要 API key 的本地 server 或私有 proxy，`apiKey` 是可选的。选择一个不会与内置 provider 名称或别名冲突的名称，例如 `openai`、`openai-codex`、`github-copilot` 或 `lm-studio`。不要在自定义 provider key 上设置 `apiType`；`apiType` 仅适用于 `providers.openai`。

如果自定义 endpoint 的文档中说明了非标准的 thinking 开关，请将 `providers.<name>.thinkingStyle` 设置为 `thinking_type`、`enable_thinking` 或 `reasoning_split`；nanobot 随后会将 `reasoningEffort` 映射到该 provider 特有的 request body。对于普通 OpenAI-compatible endpoint，请保持未设置。

此命名自定义 provider 路径不适用于 Anthropic-compatible endpoint。对于 Anthropic-compatible proxy，请使用 `providers.anthropic.apiBase` 并将 preset provider 设置为 `anthropic`。

### ModelScope

ModelScope（魔搭社区）提供 OpenAI-compatible LLM endpoint，以及单独的异步图像生成 API。两者均由内置 `modelscope` provider 覆盖。

创建一个 ModelScope [access token](https://modelscope.cn/my/myaccesstoken)，然后选择其页面提供 API-Inference 的 model。以下示例使用 [`Qwen/Qwen3-32B`](https://modelscope.cn/models/Qwen/Qwen3-32B)；托管可用性和配额由 ModelScope 控制。有关当前服务详情，请参阅官方 [API-Inference 指南](https://modelscope.cn/docs/model-service/API-Inference/intro)。

```json
{
  "providers": {
    "modelscope": {
      "apiKey": "${MODELSCOPE_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "modelscope",
      "model": "Qwen/Qwen3-32B",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

请严格使用 ModelScope 发布的、启用 inference 的 model ID（通常为 `Namespace/model-name`）。默认 base URL 为 `https://api-inference.modelscope.cn/v1`；仅当你的账户通过不同 host 路由时，才覆盖 `providers.modelscope.apiBase`。Chat model ID 可选地使用 `modelscope/` 前缀；nanobot 会在发送 request 前去除该路由前缀。

ModelScope 图像生成复用同一 provider key，但应在 `tools.imageGeneration` 下配置，而不是在 model preset 中：

```json
{
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "modelscope",
      "model": "Qwen/Qwen-Image-2512"
    }
  }
}
```

请使用图像 model 的精确 ModelScope ID，且不要带有前导 `modelscope/`；图像 client 会原样发送此值，并处理 ModelScope 的异步提交/轮询流程。该示例使用 [`Qwen/Qwen-Image-2512`](https://modelscope.cn/models/Qwen/Qwen-Image-2512)。有关支持的尺寸、宽高比及完整 provider 配置，请参阅[图像生成](image-generation-zh.md#modelscope)。

### Ollama

单独启动 Ollama，然后将 nanobot 指向 OpenAI-compatible endpoint。

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 4096,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

大多数 Ollama 设置不需要 API key。

Ollama 会通过每个 model 的 chat
template 渲染 OpenAI-compatible messages 和 tools。如果普通 model 响应很快，但使用 tool 的轮次显示较低的 prompt
cache 复用率，请在更改 nanobot 的 context 或
memory 设置前诊断渲染后的 template。
[Ollama prompt-cache 指南](guides/configure-ollama-prompt-cache-zh.md)说明了
log 模式以及经过测试的 `llama3.1:8b` 解决方法。

### vLLM 或其他本地 OpenAI-Compatible Server

```json
{
  "providers": {
    "vllm": {
      "apiBase": "http://127.0.0.1:8000/v1",
      "apiKey": "EMPTY"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "vllm",
      "model": "served-model-name",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

一些 OpenAI-compatible 本地 server 即使不验证 API key，也要求提供任意非空的 API key。

### LM Studio

```json
{
  "providers": {
    "lmStudio": {
      "apiBase": "http://localhost:1234/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "lm_studio",
      "model": "local-model",
      "maxTokens": 4096,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

配置 key 可以使用 camelCase 或 snake_case。model preset 中的 provider 名称应使用 registry 名称，例如 `lm_studio`。

### AWS Bedrock

Bedrock 可根据你的 AWS 设置使用 AWS credential chain、profile、region 或 Bedrock bearer token。

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1",
      "profile": "default"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "bedrock",
      "model": "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0",
      "maxTokens": 8192,
      "contextWindowTokens": 200000
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

请参阅 [`configuration.md#providers`](configuration-zh.md#providers)，了解 Bedrock 特有说明。

### OAuth Providers

一些 provider 不会在 `config.json` 中使用 API key。

对于 OpenAI Codex：

```bash
nanobot provider login openai-codex --set-main
```

对于符合资格的 X Premium / Grok subscription：

```bash
nanobot provider login xai-grok --set-main
```

这会选择 `xai-grok/grok-4.5`。该 provider 会读取 xAI 的 model catalog，并且
仅在所选 model 声明 `supportsBackendSearch` 时公开托管的 `x_search`
tool；否则，model 将在不使用托管 X Search 的情况下运行。
启用后，Grok 可以搜索当前 X 帖子并返回内联 source link，
而无需调用本地 nanobot tool。credentials 存储在
活动 instance 的 `auth/xai.json` 下（通常为 `~/.nanobot/auth/xai.json`），而不是
`config.json` 中，也不在 Grok Build 的 credential file 中。
托管 X Search 默认保持启用状态，可通过 WebUI
开关或 `providers.xaiGrok.extraBody.tools: []` 禁用。

此登录为 xAI subscription OAuth，而非 X Developer OAuth。它遵循
由 [Grok Build](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/02-authentication.md)
文档化和实现的 public client contract；
xAI 可以独立于 nanobot 更改该上游 contract。

对于 GitHub Copilot：

```bash
nanobot provider login github-copilot --set-main
```

每个 command 都会验证所选 provider，并使其当前默认 model 生效。OpenAI Codex 和符合资格的 GitHub Copilot model 会参与 [Responses 状态保留](configuration-zh.md#responses-state-and-compaction)，而 native compaction 仍取决于 provider capability。OAuth provider 不能用作有效的自动 fallback。有关 proxy、headless-login、model-name 和 config-key 错误，请参阅 [`troubleshooting.md`](troubleshooting-zh.md#provider-and-model-problems)。

## Provider 解析

推荐路径是由 `agents.defaults.modelPreset` 选择的命名 preset。有效 model 参数来自：

1. 由 `agents.defaults.modelPreset` 引用的命名 `modelPresets` 条目；
2. 否则，来自根据 `agents.defaults.model`、`provider`、`maxTokens`、`contextWindowTokens`、`temperature` 和相关字段构建的隐式 `default` preset。

provider 选择遵循以下实用规则：

- 活动 preset 或隐式默认配置中的显式 `provider` 优先。
- `provider: "auto"` 会尝试 model-name keyword、已配置 key、本地 base URL 和 gateway provider。
- OpenRouter 和 AiHubMix 等 gateway provider 可以路由许多 model family，因此 model name 必须对该 gateway 有效。
- 本地 provider 通常应显式指定，因为 `llama3.2` 等通用本地 model 名称并不总是包含 provider keyword。

### Model Name 前缀

`family/model-name` 不一定会选择 provider `family`。只有当活动 provider 为 `"auto"` 时，才会运行基于前缀的 provider 推断。

- 显式 provider 优先：`provider: "openrouter"` 与 `model: "anthropic/claude-sonnet-4.5"` 会调用 OpenRouter，而不是 Anthropic。
- 使用 `provider: "auto"` 时，匹配已配置内置 provider 或命名自定义 provider 的前缀可以选择该 provider。命名自定义前缀会在 request 前去除，因此 `companyProxy/gpt-4o-mini` 会作为 `gpt-4o-mini` 发送至上游。
- 使用显式命名自定义 provider 时，model 会按原样发送；`provider: "companyProxy"` 与 `model: "openai/gpt-4o-mini"` 会将 `openai/gpt-4o-mini` 发送到 `companyProxy`。

当使用 `anthropic/claude-sonnet-4.5` 等 gateway catalog ID 时，请在 preset 中固定 `provider`。

## Model Presets

model preset 是推荐的 model 配置入口。当你需要命名 model 选项、运行时 `/model` 切换或可复用的 fallback target 时，请使用它们。

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
      "model": "claude-opus-4-5",
      "maxTokens": 8192,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast"
    }
  }
}
```

preset 名称 `default` 保留给隐式 `agents.defaults` 设置。不要定义 `modelPresets.default`；在较旧的配置中，使用 `/model default` 返回直接使用 `agents.defaults.*` 字段。
## 后备 model

后备方案适用于短暂的 provider 故障、速率限制或 model 可用性问题。请确保后备方案与任务规模和 tool 使用相兼容。优先使用后备预设，以便每个候选项都有名称以及完整的 provider、model、生成和上下文窗口配置。

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
      "model": "claude-opus-4-5",
      "maxTokens": 8192,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    },
    "localSmall": {
      "label": "Local Small",
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 4096,
      "contextWindowTokens": 32768,
      "temperature": 0.2
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": ["deep", "localSmall"]
    }
  }
}
```

`fallbackModels` 中的字符串条目是预设名称，而不是原始 model 名称。nanobot 会在活动预设之后按顺序尝试它们。每个后备预设都使用自己的 `provider`、`model`、`maxTokens`、`contextWindowTokens`、`temperature` 和可选的 `reasoningEffort`。

仅当某个 model 不值得命名为预设时，才使用内联后备对象：

```json
{
  "modelPresets": {
    "fast": {
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": [
        {
          "provider": "deepseek",
          "model": "deepseek-v4-pro",
          "maxTokens": 4096,
          "contextWindowTokens": 262144
        }
      ]
    }
  }
}
```

`fallbackModels` 应位于 `agents.defaults` 下，而不是每个预设内部。如果后备候选项使用较小的上下文窗口，nanobot 会使用活动链中最小的窗口构建上下文，以便每个候选项都能接收相同的提示。有关失败条件，请参阅 [`configuration.md#model-fallbacks`](configuration-zh.md#model-fallbacks)。

## 快速检查

在调试聊天应用之前运行以下命令：

```bash
nanobot status
nanobot agent -m "Hello!"
```

如果 `nanobot agent -m "Hello!"` 失败：

| 症状 | 可能原因 |
|---|---|
| 401、未授权、无效 API key | key 缺失、已过期、复制时包含空白字符，或存储在错误的 provider 下 |
| 未找到 model | 所选 provider 或 gateway 不存在该 Model ID |
| 连接被拒绝 | 本地 provider server 未运行，或 `apiBase` 指向错误的端口 |
| 未找到 provider | 活动预设使用了拼写错误的 provider；请使用注册表名称，如 `openrouter`、`anthropic`、`ollama`、`vllm`、`lm_studio` |
| 在 CLI 中可用，但聊天应用中不可用 | provider 正常；请在 [`chat-apps.md`](chat-apps-zh.md) 或 [`troubleshooting.md`](troubleshooting-zh.md) 中调试 gateway/channel 设置 |

有关完整的 provider 表和高级 provider 专用说明，请参阅 [`configuration.md#providers`](configuration-zh.md#providers)。
