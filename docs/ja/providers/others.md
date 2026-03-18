# その他のクラウドプロバイダ

このページでは、nanobot が対応するその他のクラウド LLM サービスをまとめます。中国本土から直接アクセスしやすい国内系、欧州系モデル、高速推論サービスなどを含みます。

---

## DeepSeek

DeepSeek は高品質な OSS モデル（DeepSeek-V3、DeepSeek-R1）を提供しており、コード生成と推論が強力です。価格は GPT-4 より大幅に低い傾向があります。

### API キーを取得する

DeepSeek Platform（platform.deepseek.com）の **API Keys** ページで発行します。

### 設定例

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

### 主要モデル

| モデル ID | 説明 |
|--------|------|
| `deepseek-chat` | DeepSeek-V3（汎用旗艦） |
| `deepseek-reasoner` | DeepSeek-R1（推論モデル。o1 系に近い） |

> **モデル検出：** モデル名に `deepseek` を含む場合、自動的にこのプロバイダを使用します。LiteLLM の接頭辞は `deepseek/`（例: `deepseek/deepseek-chat`）。

---

## Google Gemini

Google の Gemini 系モデルは超長コンテキスト（100 万+ tokens）とマルチモーダル能力で知られています。

### API キーを取得する

Google AI Studio（aistudio.google.com）の **Get API Key** から発行します。

### 設定例

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

### 主要モデル

| モデル ID | 説明 |
|--------|------|
| `gemini-2.0-flash` | 高速。日常タスク向け |
| `gemini-2.0-flash-thinking-exp` | 実験的な推論バリアント |
| `gemini-2.5-pro-preview` | 最強 Gemini。超長コンテキスト |
| `gemini-1.5-pro` | 安定版旗艦。100 万 token コンテキスト |

> **モデル検出：** モデル名に `gemini` を含む場合に自動選択され、LiteLLM 接頭辞は `gemini/`。

---

## 智譜 AI（Zhipu）

智譜 AI は GLM 系モデルを提供しており、コード生成や長文処理で国内の定番選択肢です。

### API キーを取得する

智譜 AI 開放プラットフォーム（open.bigmodel.cn）の **API Keys** ページで発行します。

### 設定例

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

### 主要モデル

| モデル ID | 説明 |
|--------|------|
| `glm-4-plus` | GLM-4 旗艦 |
| `glm-4-flash` | 高速。無料枠あり |
| `glm-z1-flash` | Z1 推論モデル（高速版） |
| `glm-z1-air` | Z1 軽量推論 |

> **モデル検出：** モデル名に `zhipu` / `glm` / `zai` を含む場合に自動選択され、LiteLLM 接頭辞は `zai/`。あわせて環境変数 `ZHIPUAI_API_KEY` も設定されます（LiteLLM の一部経路で必要）。

---

## DashScope / Qwen（Alibaba Cloud）

DashScope は Alibaba Cloud の大規模モデルサービスで、通義千問（Qwen）モデルを提供します。中国本土から直接アクセスしやすく、高速です。

### API キーを取得する

阿里雲 百鍊（bailian.aliyun.com）または DashScope コンソールの **API-KEY 管理**から発行します。

### 設定例

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

### 主要モデル

| モデル ID | 説明 |
|--------|------|
| `qwen-max` | 通義千問 旗艦 |
| `qwen-plus` | バランス版 |
| `qwen-turbo` | 高速・高コスパ |
| `qwen3-235b-a22b` | Qwen3 MoE 旗艦 |
| `qwen3-30b-a3b` | Qwen3 軽量 MoE |
| `qwen-coder-plus` | コード専用 |

> **モデル検出：** モデル名に `qwen` または `dashscope` を含む場合に自動選択され、LiteLLM 接頭辞は `dashscope/`。

---

## Moonshot / Kimi

Moonshot AI は Kimi 系モデルを提供しており、長コンテキスト（128K+）と中国語理解が特徴です。

### API キーを取得する

Moonshot AI 開放プラットフォーム（platform.moonshot.cn）の **API Keys** ページで発行します。

### 設定例

**国際エンドポイント（デフォルト）：**
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

**中国本土エンドポイント：**
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

### 主要モデル

| モデル ID | 説明 |
|--------|------|
| `kimi-k2.5` | K2.5 旗艦。強推論（temperature が 1.0 固定） |
| `moonshot-v1-8k` | 標準。8K コンテキスト |
| `moonshot-v1-32k` | 32K コンテキスト |
| `moonshot-v1-128k` | 超長コンテキスト |

> **注意：** Kimi K2.5 API は `temperature >= 1.0` を強制します。nanobot は registry の `model_overrides` により、このモデル呼び出し時に temperature を自動的に 1.0 へ上書きします。

> **モデル検出：** モデル名に `moonshot` または `kimi` を含む場合に自動選択され、LiteLLM 接頭辞は `moonshot/`。

---

## MiniMax

MiniMax は MiniMax-M2.1 大規模モデルを提供し、OpenAI 互換 API を利用します。

### API キーを取得する

MiniMax 開放プラットフォーム（platform.minimaxi.com）の **API Keys** ページで発行します。

### 設定例

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

### 主要モデル

| モデル ID | 説明 |
|--------|------|
| `MiniMax-M2.1` | MiniMax 最新旗艦 |
| `MiniMax-Text-01` | テキスト生成の汎用版 |

> **モデル検出：** モデル名に `minimax` を含む場合に自動選択され、LiteLLM 接頭辞は `minimax/`。デフォルトエンドポイントは `https://api.minimax.io/v1`。

---

## Mistral

Mistral AI は欧州の有力 LLM 企業で、効率的な OSS/クローズドモデルを提供します。データ主権（EU 内サーバー）要件があるケースに向きます。

### API キーを取得する

Mistral AI Console（console.mistral.ai）の **API Keys** ページで発行します。

### 設定例

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

### 主要モデル

| モデル ID | 説明 |
|--------|------|
| `mistral-large-latest` | Mistral Large 最新 |
| `mistral-small-latest` | 軽量・高コスパ |
| `codestral-latest` | コード専用 |
| `pixtral-large-latest` | マルチモーダル |
| `mistral-nemo` | 無料 OSS（12B） |

> **モデル検出：** モデル名に `mistral` を含む場合に自動選択され、LiteLLM 接頭辞は `mistral/`。

---

## Groq（+ Whisper 音声文字起こし）

Groq は独自 LPU チップによる超高速推論で知られ、nanobot では **Whisper 音声文字起こし**にも利用されます。

### API キーを取得する

Groq Console（console.groq.com）の **API Keys** ページで発行します（無料枠あり）。

### 設定例

**LLM として使う：**
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

**音声文字起こし（STT）として使う：**
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

### 主要モデル

**LLM モデル：**

| モデル ID | 説明 |
|--------|------|
| `llama-3.3-70b-versatile` | Meta Llama 3.3 70B（汎用） |
| `llama-3.1-8b-instant` | 8B（超高速） |
| `mixtral-8x7b-32768` | Mistral Mixtral MoE |
| `gemma2-9b-it` | Google Gemma 2 9B |

**Whisper 音声モデル：**

| モデル ID | 説明 |
|--------|------|
| `whisper-large-v3-turbo` | 高速かつ高精度（推奨） |
| `whisper-large-v3` | 最高精度 |

> **注意：** Groq は registry で補助プロバイダ扱いで末尾に置かれています。明示指定しない限りデフォルトのフェイルオーバー候補にはなりません。モデル名に `groq` を含む場合に自動選択され、LiteLLM 接頭辞は `groq/`。

---

## AiHubMix

AiHubMix は OpenAI 互換インターフェースのゲートウェイで、複数のモデル提供元に対応します。中国本土ユーザーに向くことがあります。

### API キーを取得する

AiHubMix 公式サイト（aihubmix.com）の **API Keys** ページで発行します。

### 設定例

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

**APP-Code ヘッダを使う（プランによって必要）：**
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

> **注意：** AiHubMix は OpenAI 互換のため `strip_model_prefix=True` を使い、`anthropic/claude-3` のような提供元プレフィックスを剥がしてから `openai/` 接頭辞でルーティングします。`api_base` URL に `aihubmix` を含む場合に自動検出されます。

---

## SiliconFlow（硅基流動）

SiliconFlow は国内推論サービスで、Qwen、DeepSeek、Llama などの OSS モデルに対応します。新規アカウントには無料枠があります。

### API キーを取得する

SiliconFlow 公式（siliconflow.cn）の **API Keys** ページで発行します。

### 設定例

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

### 主要モデル（モデル名は機構プレフィックスを保持）

| モデル ID | 説明 |
|--------|------|
| `Qwen/Qwen2.5-72B-Instruct` | 通義千問 2.5 72B |
| `deepseek-ai/DeepSeek-V3` | DeepSeek V3 |
| `deepseek-ai/DeepSeek-R1` | DeepSeek R1 推論版 |
| `meta-llama/Meta-Llama-3.1-405B-Instruct` | Meta Llama 3.1 405B |
| `THUDM/glm-4-9b-chat` | 智譜 GLM-4 9B |

> **検出：** `api_base` URL に `siliconflow` を含む場合に自動検出され、LiteLLM 接頭辞は `openai/`。

---

## VolcEngine（火山引擎）

VolcEngine は ByteDance のクラウドで、Doubao（豆包）などのモデルを提供します。従量課金で、中国本土から直接アクセスしやすいです。

### API キーを取得する

VolcEngine Ark コンソール（console.volcengine.com/ark）の **API Key 管理**から発行します。

### 設定例

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

**VolcEngine Coding Plan（コード専用）：**
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

> **検出：** モデル名に `volcengine` / `volces` / `ark` を含む場合、または `api_base` に `volces` を含む場合に自動選択されます。Coding Plan は専用エンドポイント `https://ark.cn-beijing.volces.com/api/coding/v3` を利用します。

---

## BytePlus

BytePlus は VolcEngine の国際版で、エンドポイントは東南アジアにあります。中国本土以外で ByteDance 系モデルを使いたい場合に向きます。

### 設定例

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

> **検出：** モデル名に `byteplus` を含む場合、または `api_base` に `bytepluses` を含む場合に自動選択されます。デフォルトエンドポイントは `https://ark.ap-southeast.bytepluses.com/api/v3`。

---

## Azure OpenAI（Direct API）

nanobot は Azure OpenAI を直接呼び出すことができ、API バージョン `2024-10-21` を使用します。LiteLLM を経由しない（`is_direct=True`）ため、Azure のデプロイへ直接アクセスします。

### 設定例

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

> **注意：** Azure OpenAI では `model` フィールドは **デプロイ名（Deployment Name）**に対応します。`api_base` は Azure OpenAI リソースのエンドポイントです。

> **検出：** モデル名に `azure` / `azure-openai` を含む場合、または `provider: "azure_openai"` を明示した場合にこのプロバイダを使用します。

---

## 関連リンク

- プロバイダ概要：[providers/index.md](./index.md)
- OpenRouter（統一ゲートウェイ。多くのモデルをカバー）：[providers/openrouter.md](./openrouter.md)
- ローカル運用：[providers/local.md](./local.md)
