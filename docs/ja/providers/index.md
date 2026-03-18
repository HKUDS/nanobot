# LLM プロバイダ概要

このページでは、nanobot の Provider（プロバイダ）機構について説明します。プロバイダとは何か、自動検出の仕組み、そして用途に合った選び方をまとめます。

---

## プロバイダとは？

**プロバイダ（Provider）** は、nanobot と各 LLM（大規模言語モデル）サービスの間にあるブリッジ層です。各プロバイダは次の情報をカプセル化します。

- API キーとエンドポイント URL
- LiteLLM のルーティング接頭辞（例: `deepseek/deepseek-chat`）
- モデル名キーワード（自動検出用）
- ゲートウェイ型か、ローカル運用か
- 特殊なパラメータ上書き（例: Kimi は temperature >= 1.0 を要求）

プロバイダ定義は `nanobot/providers/registry.py` に集約されており、単一の事実ソース（single source of truth）です。

---

## 自動検出の仕組み

nanobot は次の優先順位で、どのプロバイダを使うべきかを検出します。

### 1. API キー接頭辞による検出

一部のプロバイダは API キーに固有の接頭辞があり、自動で識別できます。

| キー接頭辞 | 対応プロバイダ |
|---------|-----------|
| `sk-or-v1-...` | OpenRouter |

### 2. API Base URL のキーワード検出

カスタム `api_base` を設定している場合、URL 内のキーワードで判定します。

| URL キーワード | 対応プロバイダ |
|-----------|-----------|
| `openrouter` | OpenRouter |
| `aihubmix` | AiHubMix |
| `siliconflow` | SiliconFlow（硅基流动） |
| `volces` | VolcEngine（火山引擎） |
| `bytepluses` | BytePlus |
| `11434` | Ollama（ローカル） |

### 3. モデル名キーワード検出

上の 2 つで決まらない場合、モデル名のキーワードを解析します。

| モデル名に含まれる | 対応プロバイダ |
|------------|-----------|
| `anthropic` / `claude` | Anthropic |
| `openai` / `gpt` | OpenAI |
| `deepseek` | DeepSeek |
| `gemini` | Google Gemini |
| `zhipu` / `glm` / `zai` | Zhipu（智譜 AI） |
| `qwen` / `dashscope` | DashScope（Alibaba Cloud） |
| `moonshot` / `kimi` | Moonshot |
| `minimax` | MiniMax |
| `mistral` | Mistral |
| `groq` | Groq |
| `ollama` / `nemotron` | Ollama |
| `vllm` | vLLM（ローカル） |

> **注意:** ゲートウェイ型プロバイダとローカルプロバイダはモデル名マッチングに参加しません。API キー接頭辞または URL でのみ検出されます。

---

## 対応プロバイダ一覧

nanobot は 28+ のプロバイダに対応しており、タイプ別に次のカテゴリに分かれます。

### ゲートウェイ型（Gateway）— 任意モデルをルーティング

ゲートウェイ型は集約サービスで、1 つの API キーで複数ベンダーのモデルへアクセスできます。柔軟な課金や冗長性のメリットがあります。

| プロバイダ | 説明 | 推奨度 |
|-------|------|---------|
| **OpenRouter** | 世界最大級のモデルゲートウェイ（300+ モデル） | ⭐⭐⭐⭐⭐ 最優先 |
| **AiHubMix** | OpenAI 互換インターフェースで複数モデル | ⭐⭐⭐⭐ |
| **SiliconFlow（硅基流动）** | 中国向け無料枠あり、OSS モデル対応 | ⭐⭐⭐⭐ |
| **VolcEngine（火山引擎）** | ByteDance のクラウド（従量課金） | ⭐⭐⭐ |
| **VolcEngine Coding Plan** | VolcEngine のコード特化プラン | ⭐⭐⭐ |
| **BytePlus** | VolcEngine の国際版 | ⭐⭐⭐ |
| **BytePlus Coding Plan** | BytePlus のコード特化プラン | ⭐⭐⭐ |

### 標準クラウドプロバイダ

各社の公式 API を直接利用します。

| プロバイダ | 主なモデル | 地域 |
|-------|---------|------|
| **Anthropic** | Claude Opus/Sonnet/Haiku | グローバル |
| **OpenAI** | GPT-4o、GPT-4 Turbo、o1/o3 | グローバル |
| **DeepSeek** | DeepSeek-V3、DeepSeek-R1 | グローバル/中国 |
| **Google Gemini** | Gemini 2.0 Flash/Pro | グローバル |
| **Zhipu（智譜 AI）** | GLM-4、GLM-Z1 | 中国 |
| **DashScope（阿里雲）** | Qwen 系列 | 中国/グローバル |
| **Moonshot（Kimi）** | Kimi K2.5、moonshot-v1 | 中国/グローバル |
| **MiniMax** | MiniMax-M2.1 | 中国 |
| **Mistral** | Mistral Large、Codestral | グローバル（EU） |
| **Groq** | Llama、Mixtral（超高速推論）+ Whisper 音声 | グローバル |

### OAuth 認証（API キー不要）

| プロバイダ | 認証方式 | 要件 |
|-------|---------|------|
| **OpenAI Codex** | OAuth | ChatGPT Plus/Pro サブスク |
| **GitHub Copilot** | OAuth | GitHub Copilot サブスク |

### 直接エンドポイント（Direct API）

| プロバイダ | 説明 |
|-------|------|
| **Azure OpenAI** | Azure デプロイを直接呼び出し（LiteLLM を介さない） |
| **Custom（カスタム）** | 任意の OpenAI 互換エンドポイント |

### ローカル運用

| プロバイダ | 説明 |
|-------|------|
| **Ollama** | localhost:11434 を自動検出 |
| **vLLM** | 任意の OpenAI 互換ローカルサーバー |

---

## プロバイダの選び方

### 初めてで、まず動かしたい

**OpenRouter** を使ってください。1 つのキーでほぼすべての主要モデルへアクセスでき、複数ベンダーに個別登録する必要がありません。詳細は [OpenRouter 設定ガイド](./openrouter.md)。

### Claude を直接使いたい

**Anthropic** の公式 API を使います。Prompt Caching によりコスト削減でき、Thinking（推論努力度）も設定できます。詳細は [Anthropic 設定ガイド](./anthropic.md)。

### GPT 系を使いたい

**OpenAI** の公式 API、または OpenAI Codex OAuth（ChatGPT Plus/Pro が必要）を利用します。詳細は [OpenAI 設定ガイド](./openai.md)。

### 中国本土で国内サービスを使いたい

次がおすすめです。

- **SiliconFlow（硅基流动）** — 無料枠があり、Qwen/DeepSeek など OSS モデル対応
- **DashScope** — Alibaba Cloud 公式で Qwen が安定
- **Moonshot** — Kimi K2.5 は `api.moonshot.cn` を利用
- **Zhipu（智譜 AI）** — GLM 系

詳細は [その他クラウドプロバイダ](./others.md)。

### ローカルで動かしてクラウドへ送信したくない

**Ollama** または **vLLM** を使います。詳細は [ローカル/セルフホストモデル](./local.md)。

### GitHub Copilot または ChatGPT Plus の契約がある

OAuth 認証を使えば API クレジットを追加購入せずに利用できます。詳細は [OpenAI 設定ガイド](./openai.md)。

---

## プロバイダ設定フォーマット

すべてのプロバイダ設定は `providers` 配下に置き、共通の構造を使います。

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

| フィールド | 必須 | 説明 |
|------|------|------|
| `api_key` | はい（OAuth を除く） | サービスの API キー |
| `api_base` | いいえ | デフォルトのエンドポイント URL を上書き |
| `extra_headers` | いいえ | 追加の HTTP リクエストヘッダ |

---

## フェイルオーバーとルーティング

### 複数プロバイダを同時に設定

`providers` 配下に複数プロバイダを同時に設定できます。nanobot はモデル名に基づいて最適なものを自動選択します。

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

上の例では、モデル名 `claude-opus-4-5` に `claude` が含まれるため、システムは自動的に `anthropic` を選びます。

### プロバイダを強制指定

モデル名に関係なく特定プロバイダを使う場合は、`agents.defaults.provider` を指定します。

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

### ゲートウェイ型プロバイダの優先度

ゲートウェイ型プロバイダ（OpenRouter / AiHubMix など）は `registry.py` で先頭に並んでいるため、ゲートウェイを設定してキーが有効な場合はゲートウェイが優先されます。標準プロバイダ（Anthropic / OpenAI など）は、モデル名キーワードマッチによりゲートウェイの後に評価されます。

---

## 参考

- [OpenRouter（推奨入口）](./openrouter.md)
- [Anthropic / Claude](./anthropic.md)
- [OpenAI / GPT](./openai.md)
- [その他クラウドプロバイダ](./others.md)
- [ローカル/セルフホストモデル](./local.md)
