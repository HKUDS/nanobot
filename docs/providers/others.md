# Other cloud providers

This page covers additional cloud LLM providers supported by nanobot, including mainland China-compatible services, European models, and high-throughput inference platforms.

---

## DeepSeek

DeepSeek offers high-quality open-source models (DeepSeek-V3, DeepSeek-R1) with strong code generation and reasoning power, priced significantly below GPT-4.

### Get an API key

Visit the DeepSeek Platform (platform.deepseek.com) **API Keys** page to request one.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "deepseek-chat"
    }
  },
  "providers": {
    "deepseek": {
      "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Key models

| Model ID | Description |
|--------|------|
| `deepseek-chat` | DeepSeek V3 general-purpose flagship |
| `deepseek-reasoner` | DeepSeek R1 reasoning model (similar to o1) |

> **Model detection:** Models containing `deepseek` automatically use this provider.

---

## Google Gemini

Google’s Gemini models are known for extremely long context windows (1M+ tokens) and multimodal capabilities.

### Get an API key

Request one on the Google AI Studio (aistudio.google.com) **Get API Key** page.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "gemini-2.0-flash"
    }
  },
  "providers": {
    "gemini": {
      "api_key": "AIzaSy-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Key models

| Model ID | Description |
|--------|------|
| `gemini-2.0-flash` | Fast day-to-day usage |
| `gemini-2.0-flash-thinking-exp` | Experimental reasoning build |
| `gemini-2.5-pro-preview` | Top Gemini with extremely long context |
| `gemini-1.5-pro` | Stable flagship with 1M token context |

> **Model detection:** Models containing `gemini` automatically select this provider.

---

## Zhipu AI (GLM)

Zhipu provides the GLM series, widely used in China for code generation and long-form text.

### Get an API key

Request one at the Zhipu Open Platform (open.bigmodel.cn) **API Keys** page.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "glm-4-plus"
    }
  },
  "providers": {
    "zhipu": {
      "api_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.xxxxxxxxxxxxxxxx"
    }
  }
}
```

### Key models

| Model ID | Description |
|--------|------|
| `glm-4-plus` | GLM-4 flagship |
| `glm-4-flash` | Fast version with free quota |
| `glm-z1-flash` | Z1 reasoning fast tier |
| `glm-z1-air` | Lightweight Z1 reasoning |

> **Model detection:** Names containing `zhipu`, `glm`, or `zai` automatically use this provider.

---

## DashScope / Qwen (Alibaba Cloud)

DashScope hosts the Qwen series on Alibaba Cloud, accessible from mainland China with low latency.

### Get an API key

Request it through the DashScope or Alibaba BaiLian console’s **API-Key Management** page.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "qwen-max"
    }
  },
  "providers": {
    "dashscope": {
      "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Key models

| Model ID | Description |
|--------|------|
| `qwen-max` | Qwen flagship |
| `qwen-plus` | Balanced version |
| `qwen-turbo` | Fast, high-value version |
| `qwen3-235b-a22b` | Qwen3 MoE flagship |
| `qwen3-30b-a3b` | Lightweight MoE |
| `qwen-coder-plus` | Code-specialized |

> **Model detection:** Names containing `qwen` or `dashscope` automatically route here.

---

## Moonshot / Kimi

Moonshot AI’s Kimi models offer long context (128K+) and strong Chinese understanding.

### Get an API key

Request one at the Moonshot Open Platform (platform.moonshot.cn) **API Keys** page.

### Configuration examples

**International endpoint (default):**

```json
{
  "agents": {
    "defaults": {
      "model": "kimi-k2.5"
    }
  },
  "providers": {
    "moonshot": {
      "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

**Mainland China endpoint:**

```json
{
  "providers": {
    "moonshot": {
      "api_key": "sk-...",
      "api_base": "https://api.moonshot.cn/v1"
    }
  }
}
```

### Key models

| Model ID | Description |
|--------|------|
| `kimi-k2.5` | Flagship with reasoning (temperature locked at 1.0) |
| `moonshot-v1-8k` | Standard 8K context |
| `moonshot-v1-32k` | 32K context |
| `moonshot-v1-128k` | Ultra-long context |

> **NOTE:** Kimi K2.5 APIs require `temperature >= 1.0`. The registry auto-applies `model_overrides` to set `temperature` to 1.0 when you choose this model.

> **Model detection:** Names with `moonshot` or `kimi` route to this provider.

---

## MiniMax

MiniMax offers the MiniMax-M2.1 model through an OpenAI-compatible API.

### Get an API key

Request one at platform.minimaxi.com’s **API Keys** page.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "MiniMax-M2.1"
    }
  },
  "providers": {
    "minimax": {
      "api_key": "eyJhbGciOiJSUzI1NiIsInR..."
    }
  }
}
```

### Key models

| Model ID | Description |
|--------|------|
| `MiniMax-M2.1` | Latest flagship |
| `MiniMax-Text-01` | General text generation |

> **Model detection:** Names with `minimax` route here. The default endpoint is `https://api.minimax.io/v1`.

---

## Mistral

Mistral AI provides efficient open and closed source models hosted in Europe, ideal for data sovereignty use cases.

### Get an API key

Request one at console.mistral.ai **API Keys**.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "mistral-large-latest"
    }
  },
  "providers": {
    "mistral": {
      "api_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Key models

| Model ID | Description |
|--------|------|
| `mistral-large-latest` | Latest Mistral Large |
| `mistral-small-latest` | Lightweight, cost-effective |
| `codestral-latest` | Code-specialized model |
| `pixtral-large-latest` | Multimodal version |
| `mistral-nemo` | Free open-source 12B model |

> **Model detection:** Names containing `mistral` route here.

---

## Groq (+ Whisper transcription)

Groq delivers blazing inference speed with its LPU chips and also powers Whisper-based speech-to-text for nanobot.

### Get an API key

Request one on the Groq Console (console.groq.com). Free quota is available.

### Configuration examples

**As an LLM:**

```json
{
  "agents": {
    "defaults": {
      "model": "llama-3.3-70b-versatile"
    }
  },
  "providers": {
    "groq": {
      "api_key": "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

**As speech transcription (STT):**

```json
{
  "providers": {
    "groq": {
      "api_key": "gsk_..."
    }
  },
  "skills": {
    "voice": {
      "stt_provider": "groq",
      "stt_model": "whisper-large-v3-turbo"
    }
  }
}
```

### Key models

**LLM models**

| Model ID | Description |
|--------|------|
| `llama-3.3-70b-versatile` | Meta Llama 3.3 70B general-purpose |
| `llama-3.1-8b-instant` | 8B instant model |
| `mixtral-8x7b-32768` | Mistral Mixtral MoE |
| `gemma2-9b-it` | Google Gemma 2 9B |

**Whisper speech models**

| Model ID | Description |
|--------|------|
| `whisper-large-v3-turbo` | Fast and accurate (recommended) |
| `whisper-large-v3` | Maximum accuracy |

> **Note:** Groq is marked as a secondary provider and only used when explicitly requested. Models containing `groq` route here.

---

## AiHubMix

AiHubMix is an OpenAI-compatible gateway that aggregates multiple providers, ideal for mainland China users.

### Get an API key

Request one on aihubmix.com’s **API Keys** page.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5"
    }
  },
  "providers": {
    "aihubmix": {
      "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

**Use the APP-Code header (required by some plans):**

```json
{
  "providers": {
    "aihubmix": {
      "api_key": "sk-...",
      "extra_headers": {
        "APP-Code": "your-app-code"
      }
    }
  }
}
```

> **Note:** AiHubMix strips provider prefixes (`strip_model_prefix=True`). For example, `anthropic/claude-3` is transformed to `openai/claude-3` before routing. Detection is automatic when `api_base` contains `aihubmix`.

---

## SiliconFlow

SiliconFlow is a mainland China inference platform offering Qwen, DeepSeek, Llama, and more. New accounts receive free credits.

### Get an API key

Request one at siliconflow.cn’s **API Keys** page.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "Qwen/Qwen2.5-72B-Instruct"
    }
  },
  "providers": {
    "siliconflow": {
      "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Key models (prefix includes the organization)

| Model ID | Description |
|--------|------|
| `Qwen/Qwen2.5-72B-Instruct` | Qwen 2.5 72B |
| `deepseek-ai/DeepSeek-V3` | DeepSeek V3 |
| `deepseek-ai/DeepSeek-R1` | DeepSeek R1 reasoning |
| `meta-llama/Meta-Llama-3.1-405B-Instruct` | Meta Llama 3.1 405B |
| `THUDM/glm-4-9b-chat` | Zhipu GLM-4 9B |

> **Model detection:** Any `api_base` containing `siliconflow` triggers this provider with the `openai/` prefix.

---

## VolcEngine (ByteDance)

VolcEngine (ByteDance) offers Doubao models through pay-as-you-go billing and is accessible within China.

### Get an API key

Request one through the VolcEngine Ark console (console.volcengine.com/ark) **API Key Management** page.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "doubao-pro-32k"
    }
  },
  "providers": {
    "volcengine": {
      "api_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

**VolcEngine Coding Plan (code-specialized):**

```json
{
  "agents": {
    "defaults": {
      "model": "volcengine-plan/your-endpoint-id",
      "provider": "volcengine_coding_plan"
    }
  },
  "providers": {
    "volcengine_coding_plan": {
      "api_key": "your-volcengine-api-key"
    }
  }
}
```

> **Model detection:** Names containing `volcengine`, `volces`, or `ark` route to VolcEngine. Coding Plan uses the `https://ark.cn-beijing.volces.com/api/coding/v3` endpoint.

---

## BytePlus (international VolcEngine)

BytePlus is the international arm of VolcEngine, hosted in Southeast Asia for global access to ByteDance models.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "byteplus/your-endpoint-id",
      "provider": "byteplus"
    }
  },
  "providers": {
    "byteplus": {
      "api_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

**BytePlus Coding Plan:**

```json
{
  "providers": {
    "byteplus_coding_plan": {
      "api_key": "your-byteplus-api-key"
    }
  }
}
```

> **Model detection:** Names containing `byteplus` or `api_base` containing `bytepluses` route here. Default endpoint: `https://ark.ap-southeast.bytepluses.com/api/v3`.

---

## Azure OpenAI (direct API)

Nanobot can call Azure OpenAI directly using API version 2024-10-21.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "gpt-4o",
      "provider": "azure_openai"
    }
  },
  "providers": {
    "azure_openai": {
      "api_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "api_base": "https://your-resource.openai.azure.com/openai/deployments/your-deployment"
    }
  }
}
```

> **Note:** `model` corresponds to your deployment name; `api_base` is the endpoint for your Azure OpenAI resource.

> **Model detection:** Names containing `azure` or `azure-openai`, or explicitly setting `provider: "azure_openai"`, select this provider.

---

## Step Fun (阶跃星辰)

Step Fun offers OpenAI-compatible API access to their models.

### Get an API key

Request one at the Step Fun developer platform.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "step-2-chat"
    }
  },
  "providers": {
    "stepfun": {
      "api_key": "your-stepfun-api-key"
    }
  }
}
```

### Key models

| Model ID | Description |
|--------|------|
| `step-2-chat` | Latest Step 2 chat model |
| `step-2-thinking` | Step 2 reasoning model |

> **Model detection:** Names containing `stepfun` or `step` route to this provider.

---

## Further reading

- Provider overview: [providers/index.md](./index.md)
- OpenRouter (gateway covering many of the models above): [providers/openrouter.md](./openrouter.md)
- Local deployment: [providers/local.md](./local.md)
