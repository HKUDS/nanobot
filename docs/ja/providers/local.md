# ローカル/セルフホストモデル

nanobot はローカル PC やプライベートサーバー上で LLM を動かすことができ、データを環境の外へ出さずに運用できます。このページでは Ollama、vLLM、そして任意の OpenAI 互換エンドポイント（custom）の 3 つを扱います。

---

## Ollama

Ollama は最も手軽なローカル LLM 実行手段で、クロスプラットフォームで簡単に導入できます。Llama、Qwen、Mistral、Gemma など多くの OSS モデルに対応します。

nanobot は `localhost:11434` で動く Ollama を自動検出します（`api_base` の URL に `11434` を含むことで識別）。

### Ollama をインストールする

**macOS / Linux：**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows：**
Ollama 公式サイト（ollama.com）からインストーラをダウンロードしてください。

インストール後、Ollama は `http://localhost:11434` で自動起動します。

### モデルを取得する

```bash
# Llama 3.2 3B（軽量。一般的なハードウェア向け）
ollama pull llama3.2

# Qwen 2.5 7B（中国語が得意）
ollama pull qwen2.5

# Mistral 7B
ollama pull mistral

# Gemma 2 9B
ollama pull gemma2

# 取得済みモデル一覧
ollama list
```

### nanobot の設定例

**最小構成（自動検出）：**
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

**プロバイダを明示（モデル名の曖昧さを避ける）：**
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

**デフォルト以外のポートやリモート Ollama：**
```json
{
  "providers": {
    "ollama": {
      "api_base": "http://192.168.1.100:11434"
    }
  }
}
```

> **API キー：** Ollama のローカルサービスは通常 API キー不要です。`api_key` は空でも省略でも構いません。

### よく使う Ollama モデル

| モデル ID | パラメータ数 | 特徴 | VRAM 目安 |
|--------|--------|------|----------|
| `llama3.2` | 3B | 軽量汎用 | ~2GB |
| `llama3.2:1b` | 1B | 超軽量 | ~1GB |
| `llama3.1:8b` | 8B | バランス | ~5GB |
| `llama3.1:70b` | 70B | 高品質 | ~40GB |
| `qwen2.5:7b` | 7B | 中国語が得意 | ~5GB |
| `qwen2.5:14b` | 14B | 中国語旗艦 | ~9GB |
| `mistral` | 7B | 欧州モデル | ~5GB |
| `gemma2:9b` | 9B | Google OSS | ~6GB |
| `deepseek-r1:8b` | 8B | 推論モデル | ~5GB |
| `phi4` | 14B | Microsoft 軽量旗艦 | ~9GB |

> 完全なモデル一覧は Ollama Library（ollama.com/library）を参照してください。

### 検出ロジック

nanobot が Ollama を判定する条件:

1. `api_base` URL に `11434`（Ollama のデフォルトポート）を含む
2. モデル名に `ollama` または `nemotron` を含む
3. `provider: "ollama"` を明示

LiteLLM のルーティング接頭辞は `ollama_chat/`（例: `ollama_chat/llama3.2`）で、nanobot が自動処理します。

---

## vLLM

vLLM は高性能な LLM 推論エンジンで、GPU サーバー上のデプロイに向き、OpenAI 互換 API を提供します。Ollama よりも本番運用やバッチ推論に適しています。

### vLLM を使うべきタイミング

- NVIDIA GPU サーバー（A100、H100、RTX 4090 など）がある
- 高スループット推論（複数ユーザーの同時利用）が必要
- 70B+ の大規模モデルを動かしたい
- 量子化（AWQ、GPTQ）などの制御を細かくしたい

### vLLM サーバーを起動する

```bash
# vLLM をインストール
pip install vllm

# OpenAI 互換サーバーを起動（例: Llama 3.1 8B）
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --port 8000

# 量子化版（VRAM 節約）
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-72B-Instruct-AWQ \
  --quantization awq \
  --port 8000
```

### nanobot の設定例

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

**リモート vLLM サーバー：**
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

> **API キー：** vLLM はデフォルトでキー検証しませんが、起動時に `--api-key` を設定できます。未設定の場合は `"EMPTY"` のような任意文字列で構いません。

### モデル名

vLLM 起動時に `--model` で指定した名前をそのまま `model` に使います。

```json
{
  "agents": {
    "defaults": {
      "model": "Qwen/Qwen2.5-72B-Instruct"
    }
  }
}
```

> **検出ロジック：** `providers.vllm` を設定すると、nanobot は自動的に `hosted_vllm/` の LiteLLM 接頭辞でルーティングします。vLLM の `default_api_base` は空のため、**`api_base` にサーバー URL を必ず設定してください**。

---

## Custom（任意の OpenAI 互換エンドポイント）

`custom` プロバイダは、次のような任意の OpenAI 互換 API に対応します。

- LM Studio（ローカル GUI 推論）
- LocalAI（Docker で動くローカルサービス）
- 企業内のプライベート LLM デプロイ
- `/v1/chat/completions` を提供する任意サービス

### custom を使うべきタイミング

- nanobot に内蔵されていない提供元を使いたい
- LiteLLM を介さずに HTTP エンドポイントを直接指定したい
- 特殊な認証（カスタムヘッダ）が必要

> `custom` は `is_direct=True` を使い、**LiteLLM をバイパス**して OpenAI SDK 互換形式で直接呼び出します。互換性は最大ですが、LiteLLM の機能（自動リトライ、フェイルオーバーなど）は適用されません。

### 設定例

**LM Studio（デフォルトポート 1234）：**
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

**企業内サービス（認証ヘッダ付き）：**
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

## ローカルモデル選定の目安

| ハードウェア | 推奨方式 | 推奨モデル |
|---------|---------|---------|
| MacBook Air（8GB RAM） | Ollama | `llama3.2:3b`、`qwen2.5:3b` |
| MacBook Pro M3（16GB RAM） | Ollama | `llama3.1:8b`、`qwen2.5:7b` |
| MacBook Pro M3 Max（32GB RAM） | Ollama | `llama3.1:70b`（量子化）、`qwen2.5:14b` |
| RTX 4090（24GB VRAM） | Ollama または vLLM | `llama3.1:70b`（Q4）、`qwen2.5:72b`（AWQ） |
| A100（80GB VRAM） | vLLM | 任意の 70B 全精度モデル |
| マルチ GPU サーバー | vLLM | 100B+ モデル（tensor parallelism） |

---

## よくある質問

**Q：Ollama と vLLM は同時に設定できますか？**
できます。`api_base` のポート/URL を分け、必要に応じて `provider` で明示してください。

**Q：ローカルモデルの速度はクラウドと比べてどうですか？**
一般的な GPU（RTX 4090）では 7B モデルは 40〜80 tokens/sec 程度で、クラウド API に近い速度になります。70B モデルは 10〜20 tokens/sec 程度です。

**Q：Ollama でモデルを常駐させるには？**
デフォルトではアイドル 5 分でモデルをアンロードします。環境変数 `OLLAMA_KEEP_ALIVE=-1` を設定すると常駐します。

**Q：vLLM でライセンス同意が必要な Hugging Face モデル（例: Llama 3）を使えますか？**
使えます。先に `huggingface-cli login` で認可し、その後 vLLM を起動してください。

---

## 関連リンク

- プロバイダ概要：[providers/index.md](./index.md)
- その他クラウドプロバイダ：[providers/others.md](./others.md)
- 公式ドキュメント：
  - Ollama 公式（ollama.com）
  - vLLM 公式（docs.vllm.ai）
  - LM Studio 公式（lmstudio.ai）
