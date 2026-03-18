# Anthropic（Claude モデル）

Anthropic は Claude モデルファミリーの開発元で、公式 API を直接提供しています。OpenRouter 経由と比べて、Anthropic 直結は低レイテンシになりやすく、より安定した Prompt Caching や Thinking（推論努力度）などの高度機能を利用できます。

---

## API キーを取得する

1. Anthropic Console（console.anthropic.com）へ
2. Google アカウントまたは Email で登録する
3. **API Keys** ページを開く
4. 「Create Key」をクリックし、名前を入力して作成する
5. キーをコピー（形式: `sk-ant-api03-xxxxxxxx...`）

> Anthropic はクレジット（残高）方式です。新規アカウントは無料試用枠が付くことが多く、継続利用にはチャージまたはサブスクが必要です。

---

## 利用可能なモデル

Anthropic は用途に応じて 3 つのモデル階層を提供しています。

### Claude Opus — 最強推論

| モデル ID | 特徴 |
|--------|------|
| `claude-opus-4-5` | 最新 Opus。最高の推論能力。Thinking 対応 |

向いている用途：複雑な分析、コードのアーキテクチャ設計、長文執筆

### Claude Sonnet — バランス型

| モデル ID | 特徴 |
|--------|------|
| `claude-sonnet-4-5` | 最新 Sonnet。高性能かつコストバランス良好 |
| `claude-sonnet-3-7` | 強化版 Extended Thinking に対応 |
| `claude-sonnet-3-5` | 安定成熟。広く利用される |

向いている用途：一般タスク、コード生成、QA

### Claude Haiku — 速度優先

| モデル ID | 特徴 |
|--------|------|
| `claude-haiku-3-5` | 最新 Haiku。最速・最安 |

向いている用途：即時応答、バッチ処理、軽量タスク

---

## 設定例

### 基本設定

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5"
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Prompt Caching を有効化する

nanobot は Anthropic 直結で `cache_control` をサポートします。Prompt Caching はシステムプロンプトとツール定義に自動適用されるため、追加設定は不要です。明示的に確認したい場合は `agents.defaults` に設定できます。

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5",
      "prompt_caching": true
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

長いシステムプロンプト（1024 tokens 超）では効果が大きく、キャッシュヒット時に入力コストを 50〜90% 節約できます。

> **注意：** Prompt Caching は Anthropic 直結と OpenRouter ルーティングでのみ有効です。他のゲートウェイでは `cache_control` ヘッダをサポートしない場合があります。

### Thinking（推論努力度）を設定する

Claude Opus と一部 Sonnet は Extended Thinking をサポートし、複雑推論タスクの品質を上げられます。

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5",
      "thinking": {
        "type": "enabled",
        "budget_tokens": 10000
      }
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

| パラメータ | 説明 |
|------|------|
| `type` | `"enabled"` で有効化、`"disabled"` で無効化 |
| `budget_tokens` | 思考プロセスに使える最大 tokens（推奨: 1000〜32000） |

> **注意：** Thinking モードでは `temperature` を 1 にする必要があります（Anthropic の要件）。nanobot はバックエンドで自動処理します。

### 完全な設定例

```json
{
  "agents": {
    "defaults": {
      "model": "claude-sonnet-4-5",
      "max_tokens": 8192,
      "temperature": 0.7
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

---

## モデル自動検出

nanobot は次のキーワードで Anthropic モデルを自動判定します（`provider` を明示しなくても動作）。

- モデル名に `anthropic` または `claude` を含む

たとえば `model: "claude-haiku-3-5"` は自動的に `anthropic` プロバイダ設定を使用します。

---

## Prompt Caching による節約の仕組み

Anthropic の Prompt Caching は、同一内容（システムプロンプト、ツール定義、長文ドキュメントなど）を繰り返し送る場合にキャッシュ読み取り割引を適用します。キャッシュヒット時の入力レートは通常の入力 Token 料金より約 90% 安くなります。

nanobot は次のケースで自動的にキャッシュを活用します。

- 会話ごとに固定のシステムプロンプト
- MCP ツール定義リスト（長くなりがち）
- 長いメモリ要約（memory consolidation の出力）

高頻度運用や長い会話では、Prompt Caching により総コストを大きく削減できます。

---

## よくある質問

**Q：Anthropic と OpenRouter は同時に設定できますか？**
できます。モデル名に基づいて自動選択されます。両方を設定し `provider` を明示しない場合、モデル名の `anthropic` / `claude` キーワードにより Anthropic 直結へ自動ルーティングされます。

**Q：Anthropic API は中国本土から使えますか？**
Anthropic のエンドポイント（`api.anthropic.com`）は中国本土では VPN が必要です。ネットワーク制限がある場合は OpenRouter や SiliconFlow の利用を検討してください。

**Q：API 利用状況はどこで確認できますか？**
Anthropic Console の **Usage** ページで Token 使用量、費用内訳、モデル別統計を確認できます。

---

## 関連リンク

- プロバイダ概要：[providers/index.md](./index.md)
- OpenRouter（代替）：[providers/openrouter.md](./openrouter.md)
- 公式ドキュメント：Anthropic 公式サイトの API Reference / Models
