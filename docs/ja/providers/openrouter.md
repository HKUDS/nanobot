# OpenRouter（推奨のデフォルトプロバイダ）

OpenRouter は nanobot の最もおすすめの入門プロバイダです。API キー 1 つで Anthropic、OpenAI、Google、Meta、Mistral など数十社の 300+ モデルにアクセスできます。

---

## OpenRouter とは？なぜおすすめ？

OpenRouter は LLM のモデルゲートウェイ（Gateway）で、統一された OpenAI 互換 API を提供し、バックエンドで各モデル提供元へルーティングします。

**おすすめの理由：**

- **キー 1 つで完結** — Anthropic、OpenAI、Google など各社へ個別登録する必要がありません
- **従量課金** — モデルごとに課金され、価格の高いモデルも低コストで試せます
- **無料モデル** — Llama / Qwen など一部モデルは無料枠があります
- **自動フェイルオーバー** — 同一モデルの複数提供元で Provider Fallback を設定できます
- **最適ルーティング** — レイテンシやコストで最適な提供元を選べます
- **Prompt Caching 対応** — nanobot は OpenRouter の prompt caching を有効化しています

---

## API キーを取得する

1. OpenRouter 公式サイト（openrouter.ai）へ
2. 「Sign In」または「Get Started」から Google / GitHub でログイン
3. **Keys** ページ（Settings → Keys）へ
4. 「Create Key」をクリック
5. キーをコピー（形式: `sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）

> **重要：** nanobot はキー接頭辞 `sk-or-` で OpenRouter を自動検出します。`api_base` の追加設定は不要です。

---

## 設定例

### 最小構成（デフォルトモデルを使う）

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### 完全な設定

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "api_base": "https://openrouter.ai/api/v1"
    }
  }
}
```

> `api_base` は任意です。`sk-or-` キーを設定している場合、システムは自動的に `https://openrouter.ai/api/v1` を使用します。

---

## OpenRouter で特定モデルを選ぶ

OpenRouter のモデル名は `{プロバイダ}/{モデル名}` 形式です。例:

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

### よく使うモデル一覧

OpenRouter でよく使われるモデル ID（`provider/model` 形式で `model` に設定）:

**Anthropic Claude 系**

| モデル ID | 説明 |
|--------|------|
| `anthropic/claude-opus-4-5` | Claude Opus（最強推論） |
| `anthropic/claude-sonnet-4-5` | Claude Sonnet（性能とコストのバランス） |
| `anthropic/claude-haiku-3-5` | Claude Haiku（最速・最安） |

**OpenAI GPT 系**

| モデル ID | 説明 |
|--------|------|
| `openai/gpt-4o` | GPT-4o（マルチモーダル旗艦） |
| `openai/gpt-4o-mini` | GPT-4o Mini（高コスパ） |
| `openai/o3` | o3 推論モデル |

**Google Gemini 系**

| モデル ID | 説明 |
|--------|------|
| `google/gemini-2.0-flash-001` | Gemini 2.0 Flash（高速） |
| `google/gemini-2.5-pro-preview` | Gemini 2.5 Pro（長コンテキスト） |

**オープンソースモデル（無料枠があることが多い）**

| モデル ID | 説明 |
|--------|------|
| `meta-llama/llama-3.3-70b-instruct` | Meta Llama 3.3 70B |
| `qwen/qwen-2.5-72b-instruct` | Alibaba Qwen 2.5 72B |
| `deepseek/deepseek-chat` | DeepSeek V3 |
| `deepseek/deepseek-r1` | DeepSeek R1 推論モデル |
| `mistralai/mistral-large-2411` | Mistral Large |

> モデル一覧は OpenRouter の Models ページで確認できます（用途、コスト、コンテキスト長などでフィルタ可能）。

---

## コスト最適化のヒント

### 1. 無料モデルを活用する

OpenRouter 上の多くの OSS モデルには無料枠があり、軽量な日常タスクに向いています。

- `meta-llama/llama-3.3-70b-instruct:free`
- `google/gemini-2.0-flash-exp:free`

モデル ID の末尾に `:free` を付けると無料レイヤを強制できます（レート制限あり）。

### 2. タスクに合わせてモデルを選ぶ

- **高速 QA** — `claude-haiku` や `gpt-4o-mini` を使うとコストを 10〜20 倍削減
- **コード生成** — `claude-sonnet` や `deepseek-chat` は品質とコストのバランスが良い
- **難しい推論** — 必要なときだけ `claude-opus` や `o3` を使う

### 3. Prompt Caching を使う

nanobot は OpenRouter の prompt caching（プロンプトのキャッシュ）を有効化しています。繰り返し送るシステムプロンプトやツール定義の入力が重複課金されにくくなり、対応モデルでは入力 Token コストを 50〜90% 節約できます。

### 4. 上限を設定する

OpenRouter の Billing ページで日次/月次の上限を設定し、意図しない超過を防げます。

---

## レート制限

OpenRouter のレート制限はアカウント状態とモデルによって異なります。

| アカウント状態 | 制限 |
|---------|------|
| 未チャージ | 1 日 50 リクエスト（無料モデル） |
| チャージ済み | 各モデル提供元の制限に依存（通常は緩い） |
| 企業プラン | OpenRouter 営業へ問い合わせ |

`429 Too Many Requests` が出る場合:

1. OpenRouter でモデルごとの制限を確認する
2. OpenRouter 側で Provider Fallback を有効化する
3. nanobot の並列リクエスト数を下げる

---

## よくある質問

**Q：OpenRouter はストリーミング出力に対応していますか？**
はい。nanobot はデフォルトでストリーミングを使い、OpenRouter も対応しています。

**Q：商用利用の同意が必要なモデルにアクセスできますか？**
一部モデルは利用規約の同意が必要です。各モデルページの説明を確認してください。

**Q：OpenRouter の価格は公式と同じですか？**
通常は少し上乗せ（約 0.5〜1x）がありますが、利便性の対価です。提供元の補助で公式より安いモデルもあります。

---

## 関連リンク

- プロバイダ概要：[providers/index.md](./index.md)
- Anthropic 直結：[providers/anthropic.md](./anthropic.md)
- OpenAI 直結：[providers/openai.md](./openai.md)
