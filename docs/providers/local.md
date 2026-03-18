# 本地/自託管模型

nanobot 支援在本機或私有伺服器上執行 LLM，資料完全不離開你的環境。本頁涵蓋 Ollama、vLLM 和自訂 OpenAI 相容端點三種方式。

---

## Ollama

Ollama 是最簡單的本地 LLM 執行方案，提供跨平台的一鍵安裝，支援 Llama、Qwen、Mistral、Gemma 等數十種開源模型。

nanobot 會自動偵測執行在 `localhost:11434` 的 Ollama 服務（透過 `api_base` URL 中含有 `11434` 來識別）。

### 安裝 Ollama

**macOS / Linux：**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows：**
前往 Ollama 官方網站（ollama.com）下載安裝程式。

安裝完成後，Ollama 服務自動在 `http://localhost:11434` 啟動。

### 拉取模型

```bash
# 拉取 Llama 3.2 3B（輕量，適合一般硬體）
ollama pull llama3.2

# 拉取 Qwen 2.5 7B（中文支援較好）
ollama pull qwen2.5

# 拉取 Mistral 7B
ollama pull mistral

# 拉取 Gemma 2 9B
ollama pull gemma2

# 查看已下載的模型
ollama list
```

### nanobot 設定範例

**最簡設定（自動偵測）：**
```json
{
  "agents": {
    "defaults": {
      "model": "llama3.2"
    }
  },
  "providers": {
    "ollama": {
      "api_base": "http://localhost:11434"
    }
  }
}
```

**明確指定提供商（避免模型名稱歧義）：**
```json
{
  "agents": {
    "defaults": {
      "model": "qwen2.5:7b",
      "provider": "ollama"
    }
  },
  "providers": {
    "ollama": {
      "api_base": "http://localhost:11434"
    }
  }
}
```

**使用非預設端口或遠端 Ollama 伺服器：**
```json
{
  "providers": {
    "ollama": {
      "api_base": "http://192.168.1.100:11434"
    }
  }
}
```

> **API 金鑰：** Ollama 本地服務預設不需要 API 金鑰。`api_key` 可留空或省略。

### 常用 Ollama 模型

| 模型 ID | 參數量 | 特點 | VRAM 需求 |
|--------|--------|------|----------|
| `llama3.2` | 3B | 輕量通用 | ~2GB |
| `llama3.2:1b` | 1B | 極輕量 | ~1GB |
| `llama3.1:8b` | 8B | 平衡版 | ~5GB |
| `llama3.1:70b` | 70B | 高品質 | ~40GB |
| `qwen2.5:7b` | 7B | 中文較佳 | ~5GB |
| `qwen2.5:14b` | 14B | 中文旗艦 | ~9GB |
| `mistral` | 7B | 歐洲模型 | ~5GB |
| `gemma2:9b` | 9B | Google 開源 | ~6GB |
| `deepseek-r1:8b` | 8B | 推理模型 | ~5GB |
| `phi4` | 14B | Microsoft 輕量旗艦 | ~9GB |

> 完整模型庫請至 Ollama Library（ollama.com/library）查詢。

### 偵測邏輯

nanobot 識別 Ollama 的條件：
1. `api_base` URL 中含有 `11434`（預設 Ollama 端口）
2. 模型名稱包含 `ollama` 或 `nemotron`
3. 明確設定 `provider: "ollama"`

LiteLLM 前綴為 `ollama_chat/`（例如 `ollama_chat/llama3.2`），nanobot 自動處理，無需手動設定。

---

## vLLM

vLLM 是高效能的 LLM 推理引擎，適合在 GPU 伺服器上部署，提供 OpenAI 相容 API。與 Ollama 相比，vLLM 更適合生產環境和批量推理。

### 何時使用 vLLM？

- 你有 NVIDIA GPU 伺服器（A100、H100、RTX 4090 等）
- 需要高吞吐量推理（多用戶並發）
- 想部署 70B+ 的大型模型
- 需要更精細的量化控制（AWQ、GPTQ）

### 啟動 vLLM 伺服器

```bash
# 安裝 vLLM
pip install vllm

# 啟動 OpenAI 相容伺服器（以 Llama 3.1 8B 為例）
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --port 8000

# 使用量化版（節省 VRAM）
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-72B-Instruct-AWQ \
  --quantization awq \
  --port 8000
```

### nanobot 設定範例

```json
{
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct",
      "provider": "vllm"
    }
  },
  "providers": {
    "vllm": {
      "api_key": "EMPTY",
      "api_base": "http://localhost:8000/v1"
    }
  }
}
```

**遠端 vLLM 伺服器：**
```json
{
  "providers": {
    "vllm": {
      "api_key": "your-vllm-api-key",
      "api_base": "http://gpu-server.internal:8000/v1"
    }
  }
}
```

> **API 金鑰：** vLLM 預設不驗證金鑰，但可在啟動時設定 `--api-key`。若未設定，填入任意字串（如 `"EMPTY"`）即可。

### 模型名稱

使用你在 vLLM 啟動時指定的 `--model` 名稱：

```json
{
  "agents": {
    "defaults": {
      "model": "Qwen/Qwen2.5-72B-Instruct"
    }
  }
}
```

> **偵測邏輯：** 設定 key 為 `vllm` 時（即 `providers.vllm`），nanobot 自動識別並使用 `hosted_vllm/` LiteLLM 前綴路由。vLLM 的 `default_api_base` 為空，**必須在 `api_base` 中明確填入伺服器地址**。

---

## Custom（自訂 OpenAI 相容端點）

`custom` 提供商適用於任何 OpenAI 相容的 API 服務，例如：

- LM Studio（本地 GUI 推理工具）
- LocalAI（Docker 部署的本地服務）
- 企業私有 LLM 部署
- 任何提供 `/v1/chat/completions` 端點的服務

### 何時使用 custom？

- 你的服務不屬於 nanobot 內建的任何提供商
- 你想直接指定 HTTP 端點而不經由 LiteLLM 路由
- 你的服務有特殊的認證方式（自訂標頭）

> `custom` 提供商使用 `is_direct=True`，**繞過 LiteLLM**，直接以 OpenAI SDK 格式呼叫。這提供了最大的相容性，但也意味著一些 LiteLLM 的特性（如自動重試、備援）不適用。

### 設定範例

**LM Studio（默認端口 1234）：**
```json
{
  "agents": {
    "defaults": {
      "model": "lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF",
      "provider": "custom"
    }
  },
  "providers": {
    "custom": {
      "api_key": "lm-studio",
      "api_base": "http://localhost:1234/v1"
    }
  }
}
```

**LocalAI：**
```json
{
  "providers": {
    "custom": {
      "api_key": "any-key",
      "api_base": "http://localhost:8080/v1"
    }
  }
}
```

**企業私有服務（帶認證標頭）：**
```json
{
  "providers": {
    "custom": {
      "api_key": "internal-service-key",
      "api_base": "https://llm.internal.company.com/v1",
      "extra_headers": {
        "X-Team-ID": "engineering",
        "X-Service-Version": "v2"
      }
    }
  }
}
```

---

## 本地模型選用建議

| 硬體配置 | 推薦方案 | 推薦模型 |
|---------|---------|---------|
| MacBook Air（8GB RAM） | Ollama | `llama3.2:3b`、`qwen2.5:3b` |
| MacBook Pro M3（16GB RAM） | Ollama | `llama3.1:8b`、`qwen2.5:7b` |
| MacBook Pro M3 Max（32GB RAM） | Ollama | `llama3.1:70b`（量化）、`qwen2.5:14b` |
| RTX 4090（24GB VRAM） | Ollama 或 vLLM | `llama3.1:70b`（Q4）、`qwen2.5:72b`（AWQ） |
| A100（80GB VRAM） | vLLM | 任意 70B 全精度模型 |
| 多 GPU 伺服器 | vLLM | 100B+ 模型，tensor parallelism |

---

## 常見問題

**Q：Ollama 和 vLLM 可以同時設定嗎？**
可以。設定不同的 `api_base` 端口，並在需要時以 `provider` 明確指定。

**Q：本地模型的速度與雲端相比如何？**
在消費者 GPU（RTX 4090）上，7B 模型通常達到 40-80 tokens/sec，接近雲端 API 的速度。70B 模型則在 10-20 tokens/sec 左右。

**Q：如何在 Ollama 中保持模型常駐記憶體？**
預設 Ollama 在閒置 5 分鐘後卸載模型。可設定環境變數 `OLLAMA_KEEP_ALIVE=-1` 讓模型永久駐留。

**Q：vLLM 能部署需要授權的 Hugging Face 模型（如 Llama 3）嗎？**
可以。先執行 `huggingface-cli login` 授權，再啟動 vLLM 即可。

---

## 延伸閱讀

- 提供商總覽：[providers/index.md](./index.md)
- 其他雲端提供商：[providers/others.md](./others.md)
- 官方文件：
  - Ollama 官方網站（ollama.com）
  - vLLM 官方文件（docs.vllm.ai）
  - LM Studio 官方網站（lmstudio.ai）
