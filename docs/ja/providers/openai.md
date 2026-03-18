# OpenAI（GPT モデル）

nanobot は OpenAI モデルを 3 つの方法で利用できます。API キーによる公式 API 直結、OpenAI Codex OAuth（ChatGPT Plus/Pro）、GitHub Copilot OAuth です。

---

## 方法 1: OpenAI 公式 API（API キー）

### API キーを取得する

1. OpenAI Platform（platform.openai.com）へ
2. ログイン後、**API Keys** ページを開く
3. 「Create new secret key」をクリック
4. キーをコピー（形式: `sk-proj-xxxxxxxx...`。旧形式 `sk-xxxxxxxx...` の場合もあります）

> OpenAI API はプリペイド（前払い）方式です。Billing ページで入金しないと API が利用できません。

### 利用可能なモデル

**GPT-4o 系**

| モデル ID | 特徴 |
|--------|------|
| `gpt-4o` | マルチモーダル旗艦。画像入力に対応 |
| `gpt-4o-mini` | 高コスパ。高速 |
| `gpt-4o-audio-preview` | 音声入力/出力に対応 |

**o 系 推論モデル**

| モデル ID | 特徴 |
|--------|------|
| `o3` | 最新の推論旗艦 |
| `o3-mini` | 軽量推論モデル |
| `o4-mini` | 高速推論・高コスパ |
| `o1` | 第 1 世代推論モデル |

**GPT-4 Turbo**

| モデル ID | 特徴 |
|--------|------|
| `gpt-4-turbo` | 128K コンテキスト。視覚対応 |
| `gpt-4` | 標準 GPT-4 |

> 完全なモデル一覧は OpenAI Platform の Models ページを参照してください。

### 設定例

```json
{
  "agents": {
    "defaults": {
      "model": "gpt-4o"
    }
  },
  "providers": {
    "openai": {
      "api_key": "sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### カスタム API Base を使う（プロキシサーバーなど）

```json
{
  "providers": {
    "openai": {
      "api_key": "sk-proj-...",
      "api_base": "https://your-proxy.example.com/v1"
    }
  }
}
```

---

## 方法 2: OpenAI Codex OAuth（ChatGPT Plus/Pro）

OpenAI Codex プロバイダは **ChatGPT Plus または Pro の購読**があるユーザーが OAuth でモデルを利用できるようにします。追加の API クレジットは不要です。

> **重要：** この方式は ChatGPT の Web バックエンドを利用します。挙動は公式 API と完全一致しない可能性があり、ChatGPT の利用規約に従います。

### 前提条件

- 有効な ChatGPT Plus または Pro の購読
- ブラウザで ChatGPT（chatgpt.com）にログイン済み

### 設定手順

1. 設定ファイルで `openai_codex` プロバイダを有効化します（`api_key` は不要）。

```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/auto",
      "provider": "openai_codex"
    }
  },
  "providers": {
    "openai_codex": {}
  }
}
```

2. nanobot を起動すると OAuth 認可フローへ案内されます（ブラウザが開き、ChatGPT ログインが必要）。
3. 認可が完了すると OAuth token はローカルにキャッシュされ、次回起動では再認可が不要になります。

### モデル自動検出

nanobot は `api_base` に `codex` キーワードを含む場合、またはモデル名に `openai-codex` を含む場合にこのプロバイダを判定します。

```json
{
  "providers": {
    "openai_codex": {
      "api_base": "https://chatgpt.com/backend-api"
    }
  }
}
```

> **制約：** OAuth プロバイダはフェイルオーバー候補にできません。`provider: "openai_codex"` を明示するか、`openai-codex/` のモデル接頭辞を使ってください。

---

## 方法 3: GitHub Copilot OAuth

GitHub Copilot プロバイダは **GitHub Copilot の購読**があるユーザーが OAuth でモデルを利用できるようにします。

### 前提条件

- GitHub Copilot Individual / Business / Enterprise の有効な購読
- GitHub CLI（`gh`）または GitHub Desktop をインストール済みでログイン済み

### 設定例

```json
{
  "agents": {
    "defaults": {
      "model": "github_copilot/claude-sonnet-4-5",
      "provider": "github_copilot"
    }
  },
  "providers": {
    "github_copilot": {}
  }
}
```

モデル名は `github_copilot/{model}` 形式です。例:

- `github_copilot/claude-sonnet-4-5`
- `github_copilot/gpt-4o`
- `github_copilot/o3-mini`

### 認可フロー

起動後、nanobot が OAuth 認可を案内します。GitHub アカウントでログインしてください。token がキャッシュされるため、次回以降は繰り返し操作が不要です。

### モデル自動検出

nanobot は次の条件で GitHub Copilot を判定します。

- モデル名に `github_copilot` または `copilot` を含む
- `provider: "github_copilot"` を明示している

`skip_prefixes` により、`github_copilot/claude-sonnet-4-5` は OpenAI Codex と誤判定されません。

---

## 3 方式の比較

| | 公式 API | Codex OAuth | Copilot OAuth |
|--|---------|-------------|---------------|
| **API キーが必要** | はい | いいえ | いいえ |
| **購読が必要** | いいえ（従量課金） | ChatGPT Plus/Pro | GitHub Copilot |
| **モデル選択** | すべての OpenAI モデル | ChatGPT で利用可能なモデルに限定 | Copilot が対応するモデル |
| **コスト** | token 課金 | 購読に含まれる | 購読に含まれる |
| **安定性** | 最も安定 | ChatGPT の品質/混雑に依存 | GitHub の品質/混雑に依存 |
| **おすすめ** | 一般開発者 | ChatGPT 購読ユーザー | Copilot 購読ユーザー |

---

## よくある質問

**Q：`gpt-4o` と `gpt-4o-mini` の違いは？**
`gpt-4o` は旗艦で推論能力が高い分コストも高めです。`gpt-4o-mini` は日常タスクでは十分な性能で、コストはおおむね 15 倍安いです。

**Q：o 系推論モデルはストリーミング出力に対応しますか？**
はい。nanobot は o 系のストリーミングに対応しています。ただし o 系モデルは `temperature` など一部パラメータに対応しないため、nanobot は不適合パラメータを自動的にスキップします。

**Q：ChatGPT Plus から OpenAI API アカウントへ移行するには？**
別体系のアカウントです。API を使うには platform.openai.com 側で別途アカウントを作成し、入金が必要です。Codex OAuth 方式を使えば、既存の ChatGPT Plus 購読を使って追加費用なしで利用できます。

---

## 関連リンク

- プロバイダ概要：[providers/index.md](./index.md)
- OpenRouter（統一ゲートウェイ）：[providers/openrouter.md](./openrouter.md)
- 公式ドキュメント：OpenAI Platform の API Reference / Models
