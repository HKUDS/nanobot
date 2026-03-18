# 其他雲端提供商

本頁涵蓋 nanobot 支援的其他雲端 LLM 服務，包括中國大陸可直連的國內提供商、歐洲模型、以及高速推理服務。

---

## DeepSeek

DeepSeek 提供高品質的開源模型（DeepSeek-V3、DeepSeek-R1），具備強大的程式碼和推理能力，定價遠低於 GPT-4。

### 取得 API 金鑰

前往 DeepSeek Platform（platform.deepseek.com）的 **API Keys** 頁面申請。

### 設定範例

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

### 主要模型

| 模型 ID | 說明 |
|--------|------|
| `deepseek-chat` | DeepSeek-V3，通用旗艦 |
| `deepseek-reasoner` | DeepSeek-R1，推理模型（類 o1） |

> **模型偵測：** 模型名稱包含 `deepseek` 時自動選用此提供商。LiteLLM 路由前綴為 `deepseek/`（例如 `deepseek/deepseek-chat`）。

---

## Google Gemini

Google 的 Gemini 系列模型以超長上下文（100 萬+ tokens）和多模態能力著稱。

### 取得 API 金鑰

前往 Google AI Studio（aistudio.google.com）的 **Get API Key** 頁面申請。

### 設定範例

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

### 主要模型

| 模型 ID | 說明 |
|--------|------|
| `gemini-2.0-flash` | 速度快，適合日常任務 |
| `gemini-2.0-flash-thinking-exp` | 實驗性推理版本 |
| `gemini-2.5-pro-preview` | 最強 Gemini，超長上下文 |
| `gemini-1.5-pro` | 穩定版旗艦，100 萬 token 上下文 |

> **模型偵測：** 模型名稱包含 `gemini` 時自動選用，LiteLLM 前綴為 `gemini/`。

---

## 智譜 AI（Zhipu）

智譜 AI 提供 GLM 系列模型，是國內代碼生成和長文本處理的主流選擇。

### 取得 API 金鑰

前往智譜 AI 開放平台（open.bigmodel.cn）的 **API Keys** 頁面申請。

### 設定範例

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

### 主要模型

| 模型 ID | 說明 |
|--------|------|
| `glm-4-plus` | GLM-4 旗艦版 |
| `glm-4-flash` | 快速版，免費額度 |
| `glm-z1-flash` | Z1 推理模型，快速版 |
| `glm-z1-air` | Z1 輕量推理 |

> **模型偵測：** 模型名稱包含 `zhipu`、`glm` 或 `zai` 時自動選用，LiteLLM 前綴為 `zai/`。同時會設定環境變數 `ZHIPUAI_API_KEY`（部分 LiteLLM 路徑需要）。

---

## DashScope / Qwen（阿里雲）

DashScope 是阿里雲的大模型服務平台，提供通義千問（Qwen）系列模型，國內可直連，速度快。

### 取得 API 金鑰

前往阿里雲百鍊平台（bailian.aliyun.com）或 DashScope 控制台的 **API-KEY 管理**頁面申請。

### 設定範例

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

### 主要模型

| 模型 ID | 說明 |
|--------|------|
| `qwen-max` | 通義千問旗艦 |
| `qwen-plus` | 平衡版 |
| `qwen-turbo` | 快速版，高性價比 |
| `qwen3-235b-a22b` | Qwen3 MoE 旗艦 |
| `qwen3-30b-a3b` | Qwen3 輕量 MoE |
| `qwen-coder-plus` | 程式碼專用 |

> **模型偵測：** 模型名稱包含 `qwen` 或 `dashscope` 時自動選用，LiteLLM 前綴為 `dashscope/`。

---

## Moonshot / Kimi

Moonshot AI 提供 Kimi 系列模型，以長上下文（128K+）和中文理解著稱。

### 取得 API 金鑰

前往 Moonshot AI 開放平台（platform.moonshot.cn）的 **API Keys** 頁面申請。

### 設定範例

**國際端點（默認）：**
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

**中國大陸端點：**
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

### 主要模型

| 模型 ID | 說明 |
|--------|------|
| `kimi-k2.5` | K2.5 旗艦，強推理（temperature 固定 1.0） |
| `moonshot-v1-8k` | 標準版，8K 上下文 |
| `moonshot-v1-32k` | 32K 上下文 |
| `moonshot-v1-128k` | 超長上下文 |

> **注意：** Kimi K2.5 API 強制要求 `temperature >= 1.0`。nanobot 在 registry 中設定了 `model_overrides`，呼叫此模型時自動覆寫 temperature 為 1.0。

> **模型偵測：** 模型名稱包含 `moonshot` 或 `kimi` 時自動選用，LiteLLM 前綴為 `moonshot/`。

---

## MiniMax

MiniMax 提供 MiniMax-M2.1 大模型，使用 OpenAI 相容 API。

### 取得 API 金鑰

前往 MiniMax 開放平台（platform.minimaxi.com）的 **API Keys** 頁面申請。

### 設定範例

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

### 主要模型

| 模型 ID | 說明 |
|--------|------|
| `MiniMax-M2.1` | MiniMax 最新旗艦模型 |
| `MiniMax-Text-01` | 文字生成通用版 |

> **模型偵測：** 模型名稱包含 `minimax` 時自動選用，LiteLLM 前綴為 `minimax/`，預設端點為 `https://api.minimax.io/v1`。

---

## Mistral

Mistral AI 是歐洲頂尖的 LLM 公司，提供高效的開放及閉源模型，特別適合對資料主權有要求的場景（歐盟伺服器）。

### 取得 API 金鑰

前往 Mistral AI Console（console.mistral.ai）的 **API Keys** 頁面申請。

### 設定範例

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

### 主要模型

| 模型 ID | 說明 |
|--------|------|
| `mistral-large-latest` | Mistral Large 最新版 |
| `mistral-small-latest` | 輕量版，高性價比 |
| `codestral-latest` | 程式碼專用模型 |
| `pixtral-large-latest` | 多模態版本 |
| `mistral-nemo` | 免費開源版（12B） |

> **模型偵測：** 模型名稱包含 `mistral` 時自動選用，LiteLLM 前綴為 `mistral/`。

---

## Groq（+ Whisper 語音轉錄）

Groq 以超快推理速度著稱（使用專屬 LPU 晶片），在 nanobot 中也用於 **Whisper 語音轉錄**。

### 取得 API 金鑰

前往 Groq Console（console.groq.com）的 **API Keys** 頁面申請（有免費額度）。

### 設定範例

**作為 LLM 使用：**
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

**作為語音轉錄（STT）使用：**
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

### 主要模型

**LLM 模型：**

| 模型 ID | 說明 |
|--------|------|
| `llama-3.3-70b-versatile` | Meta Llama 3.3 70B，通用 |
| `llama-3.1-8b-instant` | 8B 模型，極速 |
| `mixtral-8x7b-32768` | Mistral Mixtral MoE |
| `gemma2-9b-it` | Google Gemma 2 9B |

**Whisper 語音模型：**

| 模型 ID | 說明 |
|--------|------|
| `whisper-large-v3-turbo` | 速度快，準確率高（推薦） |
| `whisper-large-v3` | 最高準確率 |

> **注意：** Groq 在 registry 中被標記為輔助提供商，排在最後。除非明確指定，不作為預設備援。模型名稱包含 `groq` 時自動選用，LiteLLM 前綴為 `groq/`。

---

## AiHubMix

AiHubMix 是 OpenAI 相容介面的閘道服務，支援多家模型提供商，適合中國大陸使用者。

### 取得 API 金鑰

前往 AiHubMix 官方網站（aihubmix.com）的 **API Keys** 頁面申請。

### 設定範例

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

**使用 APP-Code 標頭（部分方案需要）：**
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

> **注意：** AiHubMix 使用 `strip_model_prefix=True`，會將 `anthropic/claude-3` 中的提供商前綴剝除後再以 `openai/` 前綴路由，因為 AiHubMix 採用 OpenAI 相容介面。`api_base` URL 包含 `aihubmix` 時自動偵測。

---

## SiliconFlow（硅基流動）

SiliconFlow 是國內 AI 推理服務平台，提供 Qwen、DeepSeek、Llama 等開源模型，新帳號有免費額度。

### 取得 API 金鑰

前往硅基流動官方網站（siliconflow.cn）的 **API Keys** 頁面申請。

### 設定範例

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

### 主要模型（模型名稱保留機構前綴）

| 模型 ID | 說明 |
|--------|------|
| `Qwen/Qwen2.5-72B-Instruct` | 通義千問 2.5 72B |
| `deepseek-ai/DeepSeek-V3` | DeepSeek V3 |
| `deepseek-ai/DeepSeek-R1` | DeepSeek R1 推理版 |
| `meta-llama/Meta-Llama-3.1-405B-Instruct` | Meta Llama 3.1 405B |
| `THUDM/glm-4-9b-chat` | 智譜 GLM-4 9B |

> **偵測：** `api_base` URL 包含 `siliconflow` 時自動偵測，使用 `openai/` LiteLLM 前綴。

---

## VolcEngine（火山引擎）

火山引擎是位元組跳動的雲端服務，提供豆包（Doubao）等系列模型，按量付費，國內可直連。

### 取得 API 金鑰

前往火山引擎方舟控制台（console.volcengine.com/ark）的 **API Key 管理**頁面申請。

### 設定範例

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

**VolcEngine Coding Plan（程式碼專用）：**
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

> **偵測：** 模型名稱包含 `volcengine`、`volces` 或 `ark` 時，或 `api_base` 含 `volces` 時自動選用。Coding Plan 使用獨立端點 `https://ark.cn-beijing.volces.com/api/coding/v3`。

---

## BytePlus

BytePlus 是火山引擎的國際版，端點位於東南亞，適合中國大陸以外的用戶使用字節系模型。

### 設定範例

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

**BytePlus Coding Plan：**
```json
{
  "providers": {
    "byteplus_coding_plan": {
      "api_key": "your-byteplus-api-key"
    }
  }
}
```

> **偵測：** 模型名稱包含 `byteplus` 或 `api_base` 含 `bytepluses` 時自動選用。預設端點：`https://ark.ap-southeast.bytepluses.com/api/v3`。

---

## Azure OpenAI（直接 API）

nanobot 支援直接呼叫 Azure OpenAI，使用 API 版本 `2024-10-21`，不經由 LiteLLM 路由（`is_direct=True`）。

### 設定範例

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

> **注意：** Azure OpenAI 中，`model` 欄位對應你的**部署名稱（Deployment Name）**，`api_base` 為你的 Azure OpenAI 資源端點。

> **偵測：** 模型名稱包含 `azure` 或 `azure-openai` 時，或明確指定 `provider: "azure_openai"` 時選用此提供商。

---

## 延伸閱讀

- 提供商總覽：[providers/index.md](./index.md)
- OpenRouter（統一閘道，支援以上多數模型）：[providers/openrouter.md](./openrouter.md)
- 本地部署：[providers/local.md](./local.md)
