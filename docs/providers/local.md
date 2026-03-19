# Local / self-hosted models

Nanobot supports running LLMs on your local machine or private servers so that data never leaves your environment. This page covers Ollama, vLLM, and custom OpenAI-compatible endpoints.

---

## Ollama

Ollama is the simplest local LLM runtime with cross-platform installers. It supports dozens of open-source models such as Llama, Qwen, Mistral, and Gemma.

Nanobot auto-detects Ollama running on `localhost:11434` by looking for `11434` in the `api_base` URL.

### Install Ollama

**macOS / Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows:**
Download the installer from ollama.com.

After installation, the service listens on `http://localhost:11434`.

### Pull models

```bash
# Pull Llama 3.2 3B (lightweight)
ollama pull llama3.2

# Pull Qwen 2.5 7B (strong Chinese support)
ollama pull qwen2.5

# Pull Mistral 7B
ollama pull mistral

# Pull Gemma 2 9B
ollama pull gemma2

# List downloaded models
ollama list
```

### Nanobot configuration examples

**Minimal setup (auto-detection):**
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

**Explicit provider selection (avoid name collisions):**
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

**Non-default port or remote Ollama server:**
```json
{
  "providers": {
    "ollama": {
      "api_base": "http://192.168.1.100:11434"
    }
  }
}
```

> **API key:** Ollama’s local server does not require one. Omit `api_key` or leave it empty.

### Popular Ollama models

| Model ID | Parameters | Notes | VRAM |
|--------|--------|------|----------|
| `llama3.2` | 3B | Lightweight general-purpose | ~2GB |
| `llama3.2:1b` | 1B | Tiny footprint | ~1GB |
| `llama3.1:8b` | 8B | Balanced | ~5GB |
| `llama3.1:70b` | 70B | High quality | ~40GB |
| `qwen2.5:7b` | 7B | Strong Chinese | ~5GB |
| `qwen2.5:14b` | 14B | Chinese flagship | ~9GB |
| `mistral` | 7B | European model | ~5GB |
| `gemma2:9b` | 9B | Google open-source | ~6GB |
| `deepseek-r1:8b` | 8B | Reasoning model | ~5GB |
| `phi4` | 14B | Microsoft lightweight flagship | ~9GB |

> See the Ollama Library (ollama.com/library) for the complete catalog.

### Detection logic

Nanobot recognizes Ollama when:
1. `api_base` contains `11434` (default port)
2. Model names include `ollama` or `nemotron`
3. `provider: "ollama"` is explicitly set

LiteLLM automatically handles the `ollama_chat/` prefix (e.g., `ollama_chat/llama3.2`).

---

## vLLM

vLLM is a high-performance inference engine ideal for GPU servers. It exposes an OpenAI-compatible API and scales better than Ollama for production workloads and batch inference.

### When to use vLLM

- You own an NVIDIA GPU server (A100, H100, RTX 4090, etc.)
- You need high throughput for concurrent users
- You want to deploy 70B+ models
- You require fine-grained quantization control (AWQ, GPTQ)

### Start a vLLM server

```bash
# Install vLLM
pip install vllm

# Launch an OpenAI-compatible server (example: Llama 3.1 8B)
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --port 8000

# Quantized variant saves VRAM
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-72B-Instruct-AWQ \
  --quantization awq \
  --port 8000
```

### Nanobot configuration

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

**Remote vLLM server:**
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

> **API key:** vLLM defaults to no authentication, but you can set `--api-key`. If it is unset, supply any non-empty string (e.g., `"EMPTY"`).

### Model names

Use whatever you started the server with:

```json
{
  "agents": {
    "defaults": {
      "model": "Qwen/Qwen2.5-72B-Instruct"
    }
  }
}
```

> **Detection logic:** When the provider key is `vllm`, nanobot routes through `hosted_vllm/` LiteLLM prefix. vLLM does not set a `default_api_base`, so you must specify the server address explicitly.

---

## Custom (OpenAI-compatible endpoints)

The `custom` provider works with any OpenAI-compatible API endpoint (LM Studio, LocalAI, private deployments, or any service exposing `/v1/chat/completions`).

### When to use custom

- Your service isn’t one of the built-in providers
- You need to call a specific HTTP endpoint without LiteLLM routing
- You have custom authentication headers

> The `custom` provider sets `is_direct=True`, bypassing LiteLLM and calling the OpenAI SDK directly. This maximizes compatibility but skips features like automatic retries or fallback routing.

### Configuration examples

**LM Studio (default port 1234):**
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

**LocalAI:**
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

**Private enterprise service with custom headers:**
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

## Local model recommendations

| Hardware | Recommended deployment | Suggested models |
|---------|---------|---------|
| MacBook Air (8GB RAM) | Ollama | `llama3.2:3b`, `qwen2.5:3b` |
| MacBook Pro M3 (16GB RAM) | Ollama | `llama3.1:8b`, `qwen2.5:7b` |
| MacBook Pro M3 Max (32GB RAM) | Ollama | `llama3.1:70b` (quantized), `qwen2.5:14b` |
| RTX 4090 (24GB VRAM) | Ollama or vLLM | `llama3.1:70b` (Q4), `qwen2.5:72b` (AWQ) |
| A100 (80GB VRAM) | vLLM | Any 70B full-precision model |
| Multi-GPU server | vLLM | 100B+ models with tensor parallelism |

---

## FAQ

**Q: Can Ollama and vLLM be configured at the same time?**
Yes. Use different `api_base` values and set `provider` explicitly when needed.

**Q: How does local performance compare to cloud?**
On consumer GPUs (RTX 4090), 7B models reach 40–80 tokens/sec, rivaling cloud APIs. 70B models are around 10–20 tokens/sec.

**Q: How do I keep an Ollama model loaded?**
Ollama unloads models after five minutes of idle time by default. Set `OLLAMA_KEEP_ALIVE=-1` to keep them resident.

**Q: Can vLLM serve licensed Hugging Face models (e.g., Llama 3)?**
Yes. Run `huggingface-cli login` before starting vLLM to grant access.

---

## Further reading

- Provider overview: [providers/index.md](./index.md)
- Other cloud providers: [providers/others.md](./others.md)
- Official docs:
  - Ollama (ollama.com)
  - vLLM (docs.vllm.ai)
  - LM Studio (lmstudio.ai)
