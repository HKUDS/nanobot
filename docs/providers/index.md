# LLM 提供商總覽

本文說明 nanobot 的提供商（Provider）機制，包括什麼是提供商、如何自動偵測、以及如何選擇適合的服務。

---

## 什麼是提供商？

**提供商（Provider）** 是 nanobot 與各家大型語言模型（LLM）服務之間的橋接層。每個提供商封裝了以下資訊：

- API 金鑰與端點 URL
- LiteLLM 路由前綴（例如 `deepseek/deepseek-chat`）
- 模型名稱關鍵字（用於自動偵測）
- 是否為閘道（Gateway）或本地部署
- 特殊參數覆寫（例如 Kimi 要求 temperature >= 1.0）

所有提供商的定義集中在 `nanobot/providers/registry.py`，是單一事實來源（single source of truth）。

---

## 自動偵測機制

nanobot 使用三層優先順序來偵測應使用哪個提供商：

### 1. API 金鑰前綴偵測

某些提供商的 API 金鑰有特殊前綴，系統會自動識別：

| 金鑰前綴 | 對應提供商 |
|---------|-----------|
| `sk-or-v1-...` | OpenRouter |

### 2. API Base URL 關鍵字偵測

若設定了自訂 `api_base`，系統會比對 URL 中的關鍵字：

| URL 關鍵字 | 對應提供商 |
|-----------|-----------|
| `openrouter` | OpenRouter |
| `aihubmix` | AiHubMix |
| `siliconflow` | SiliconFlow（硅基流動） |
| `volces` | VolcEngine（火山引擎） |
| `bytepluses` | BytePlus |
| `11434` | Ollama（本地） |

### 3. 模型名稱關鍵字偵測

若前兩種方式均未命中，系統會解析模型名稱中的關鍵字：

| 模型名稱包含 | 對應提供商 |
|------------|-----------|
| `anthropic`、`claude` | Anthropic |
| `openai`、`gpt` | OpenAI |
| `deepseek` | DeepSeek |
| `gemini` | Google Gemini |
| `zhipu`、`glm`、`zai` | 智譜 AI |
| `qwen`、`dashscope` | DashScope（阿里雲） |
| `moonshot`、`kimi` | Moonshot |
| `minimax` | MiniMax |
| `mistral` | Mistral |
| `groq` | Groq |
| `ollama`、`nemotron` | Ollama |
| `vllm` | vLLM / 本地 |

> **注意：** 閘道（Gateway）和本地提供商不參與模型名稱比對，它們只透過 API 金鑰前綴或 URL 偵測。

---

## 支援的提供商列表

nanobot 支援 28+ 個提供商，依類型分為以下幾類：

### 閘道型（Gateway）— 可路由任意模型

閘道型提供商是聚合服務，一個 API 金鑰即可存取來自多家廠商的模型，通常有計費彈性與備援優勢。

| 提供商 | 說明 | 推薦指數 |
|-------|------|---------|
| **OpenRouter** | 全球最大模型閘道，支援 300+ 模型 | ⭐⭐⭐⭐⭐ 首選 |
| **AiHubMix** | OpenAI 相容介面，支援多家模型 | ⭐⭐⭐⭐ |
| **SiliconFlow（硅基流動）** | 國內免費額度，支援開源模型 | ⭐⭐⭐⭐ |
| **VolcEngine（火山引擎）** | 位元組跳動雲端，按量付費 | ⭐⭐⭐ |
| **VolcEngine Coding Plan** | 火山引擎程式碼專用計畫 | ⭐⭐⭐ |
| **BytePlus** | 火山引擎國際版 | ⭐⭐⭐ |
| **BytePlus Coding Plan** | BytePlus 程式碼專用計畫 | ⭐⭐⭐ |

### 標準雲端提供商

直接對接各廠商官方 API：

| 提供商 | 主要模型 | 地區 |
|-------|---------|------|
| **Anthropic** | Claude Opus/Sonnet/Haiku | 全球 |
| **OpenAI** | GPT-4o、GPT-4 Turbo、o1/o3 | 全球 |
| **DeepSeek** | DeepSeek-V3、DeepSeek-R1 | 全球/中國 |
| **Google Gemini** | Gemini 2.0 Flash/Pro | 全球 |
| **智譜 AI（Zhipu）** | GLM-4、GLM-Z1 | 中國 |
| **DashScope（阿里雲）** | Qwen 系列 | 中國/全球 |
| **Moonshot（Kimi）** | Kimi K2.5、moonshot-v1 | 中國/全球 |
| **MiniMax** | MiniMax-M2.1 | 中國 |
| **Mistral** | Mistral Large、Codestral | 全球（歐洲） |
| **Groq** | Llama、Mixtral（超快推理）+ Whisper 語音 | 全球 |

### OAuth 認證（無需 API 金鑰）

| 提供商 | 認證方式 | 需求 |
|-------|---------|------|
| **OpenAI Codex** | OAuth 授權 | ChatGPT Plus/Pro 訂閱 |
| **GitHub Copilot** | OAuth 授權 | GitHub Copilot 訂閱 |

### 直接端點（Direct API）

| 提供商 | 說明 |
|-------|------|
| **Azure OpenAI** | 直接呼叫 Azure 部署，不經 LiteLLM |
| **Custom（自訂）** | 任何 OpenAI 相容端點 |

### 本地部署

| 提供商 | 說明 |
|-------|------|
| **Ollama** | 在 localhost:11434 自動偵測 |
| **vLLM** | 任何 OpenAI 相容本地伺服器 |

---

## 如何選擇提供商

### 我是新用戶，想快速上手

使用 **OpenRouter**。一個金鑰可以存取幾乎所有主流模型，不需要分別申請多家帳號。詳見 [OpenRouter 設定指南](./openrouter.md)。

### 我想直接使用 Claude

使用 **Anthropic** 官方 API，支援 Prompt Caching 節省費用，並可設定 Thinking（推理努力度）。詳見 [Anthropic 設定指南](./anthropic.md)。

### 我想使用 GPT 系列

使用 **OpenAI** 官方 API，或透過 OpenAI Codex OAuth（需要 ChatGPT Plus/Pro）。詳見 [OpenAI 設定指南](./openai.md)。

### 我在中國大陸，想用國內服務

推薦以下選項：
- **SiliconFlow（硅基流動）** — 有免費額度，支援 Qwen、DeepSeek 等開源模型
- **DashScope** — 阿里雲官方，Qwen 系列最穩定
- **Moonshot** — Kimi K2.5 使用 `api.moonshot.cn`
- **智譜 AI** — GLM 系列模型

詳見 [其他雲端提供商](./others.md)。

### 我想在本機跑模型，不傳資料到雲端

使用 **Ollama** 或 **vLLM**。詳見 [本地/自託管模型](./local.md)。

### 我有 GitHub Copilot 或 ChatGPT Plus 訂閱

可使用 OAuth 認證，無需另購 API 額度。詳見 [OpenAI 設定指南](./openai.md)。

---

## 提供商設定格式

所有提供商的設定都放在 `providers` 節點下，使用相同的結構：

```json
{
  "providers": {
    "<provider_name>": {
      "api_key": "your-api-key",
      "api_base": "https://custom-endpoint.example.com/v1",
      "extra_headers": {
        "X-Custom-Header": "value"
      }
    }
  }
}
```

| 欄位 | 必填 | 說明 |
|------|------|------|
| `api_key` | 是（OAuth 提供商除外） | 服務的 API 金鑰 |
| `api_base` | 否 | 覆寫預設端點 URL |
| `extra_headers` | 否 | 額外的 HTTP 請求標頭 |

---

## 提供商備援與路由

### 多提供商同時設定

可以在 `providers` 下同時設定多個提供商。nanobot 會根據模型名稱自動選擇最合適的那個。

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5"
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-..."
    },
    "openai": {
      "api_key": "sk-..."
    },
    "deepseek": {
      "api_key": "sk-..."
    }
  }
}
```

上例中，模型名稱 `claude-opus-4-5` 含有關鍵字 `claude`，系統自動選用 `anthropic` 提供商。

### 強制指定提供商

若要強制使用特定提供商（無論模型名稱為何），在 `agents.defaults.provider` 中指定：

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-..."
    }
  }
}
```

### 閘道型提供商的優先順序

閘道型提供商（OpenRouter、AiHubMix 等）在 `registry.py` 中排在最前面，因此在設定了閘道且金鑰有效的情況下，系統優先使用閘道。標準提供商（Anthropic、OpenAI 等）以模型名稱關鍵字比對，排在閘道之後。

---

## 延伸閱讀

- [OpenRouter（推薦入口）](./openrouter.md)
- [Anthropic / Claude 模型](./anthropic.md)
- [OpenAI / GPT 模型](./openai.md)
- [其他雲端提供商](./others.md)
- [本地/自託管模型](./local.md)
