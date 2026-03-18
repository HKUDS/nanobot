# クイックスタート

5 分で nanobot のセットアップを完了し、AI アシスタントと最初の会話を始めましょう。

---

## ステップ 1: nanobot をインストール

=== "uv（推奨）"

    ```bash
    uv tool install nanobot-ai
    ```

=== "pip"

    ```bash
    pip install nanobot-ai
    ```

インストールに成功したか確認します。

```bash
nanobot --version
```

!!! tip "uv が未インストールですか？"
    先に [インストールガイド](installation.md) を参照して uv と nanobot をインストールしてください。

---

## ステップ 2: Onboarding ウィザードを実行

```bash
nanobot onboard
```

ウィザードが初期設定を案内し、`~/.nanobot/` に次のファイルを作成します。

```
~/.nanobot/
├── config.json          # メイン設定ファイル
└── workspace/
    ├── AGENTS.md        # エージェントの行動ガイド
    ├── USER.md          # ユーザープロファイル
    ├── SOUL.md          # エージェントの個性定義
    ├── TOOLS.md         # ツール利用の設定
    └── HEARTBEAT.md     # 定期タスク設定
```

!!! note "既に設定がありますか？"
    `nanobot onboard` を繰り返し実行しても既存の設定は上書きされず、不足分のみが補完されます。

---

## ステップ 3: API キーとモデルを設定

`~/.nanobot/config.json` を開き、LLM の API キーとモデル設定を追加します。

```bash
# 任意のエディタで開く
vim ~/.nanobot/config.json
# または
nano ~/.nanobot/config.json
# または
code ~/.nanobot/config.json
```

### API キーを設定

例として [OpenRouter](https://openrouter.ai/keys)（グローバル利用者に推奨）:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  }
}
```

よく使う他のプロバイダ:

=== "Anthropic（Claude）"

    ```json
    {
      "providers": {
        "anthropic": {
          "apiKey": "sk-ant-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "OpenAI（GPT）"

    ```json
    {
      "providers": {
        "openai": {
          "apiKey": "sk-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "DeepSeek"

    ```json
    {
      "providers": {
        "deepseek": {
          "apiKey": "sk-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "Ollama（ローカル）"

    ```json
    {
      "providers": {
        "ollama": {
          "apiBase": "http://localhost:11434"
        }
      },
      "agents": {
        "defaults": {
          "provider": "ollama",
          "model": "llama3.2"
        }
      }
    }
    ```

### モデルを設定（任意）

デフォルトモデルを明示的に指定できます。未設定の場合、nanobot は設定済み API キーから自動検出します。

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5",
      "provider": "openrouter"
    }
  }
}
```

### 最小構成の完全例

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

!!! warning "API キーを保護してください"
    `config.json` には機密性の高い API キーが含まれます。このファイルをバージョン管理（git）にコミットしないでください。

---

## ステップ 4: CLI で対話

設定ができたら、すぐに会話を始められます。

```bash
nanobot agent
```

対話用のインターフェースが表示されます。

```
nanobot> こんにちは！何を手伝えますか？
```

nanobot は複数の実行方法をサポートします。

```bash
# 対話モード（デフォルト）
nanobot agent

# 単発メッセージ（非対話）
nanobot agent -m "今日の天気は？"

# プレーンテキストで表示（Markdown をレンダリングしない）
nanobot agent --no-markdown

# 実行ログを表示
nanobot agent --logs
```

対話モードを終了するには、`exit` / `quit` を入力するか `Ctrl+D` を押します。

!!! tip "おめでとうございます！"
    基本セットアップは完了です。以降は nanobot を Telegram に接続して、スマホからいつでも AI アシスタントと会話できるようにする手順です。

---

## ステップ 5: Telegram に接続（任意）

Telegram は最も設定が簡単なチャットプラットフォームで、初めての方におすすめです。

### Telegram Bot を作成

1. Telegram を開き、**@BotFather** を検索
2. `/newbot` を送信
3. 指示に沿って Bot 名（表示名。例: `My Nanobot`）を入力
4. Bot のユーザー名（末尾が `bot` の必要あり。例: `my_nanobot_bot`）を入力
5. BotFather が **Bot Token** を返します（例: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`）

### Telegram の User ID を取得

User ID は Telegram の設定に表示され、形式は `@yourUserId` です。コピーする際は **`@` を除いて**ください。

または、Bot に何かメッセージを送って nanobot の実行ログを確認すると、送信者の User ID が表示されます。

### 設定ファイルを更新

次を `~/.nanobot/config.json` にマージします。

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
      "allowFrom": ["your_telegram_user_id"]
    }
  }
}
```

| フィールド | 説明 |
|------|------|
| `token` | @BotFather から取得した Bot Token |
| `allowFrom` | bot との対話を許可する User ID のリスト（空なら全員拒否） |

!!! warning "セキュリティ上の注意"
    `allowFrom` は bot を利用できるユーザーを制御します。
    `["*"]` を使うと全員許可できますが、API クレジットの濫用を避けるため慎重に使用してください。

---

## ステップ 6: Gateway を起動

```bash
nanobot gateway
```

Gateway の起動後、次のような出力が表示されます。

```
[nanobot] Gateway starting on port 18790
[nanobot] Telegram channel connected
[nanobot] Ready to receive messages
```

Telegram を開き、Bot にメッセージを送ってみてください。

!!! note "Gateway と CLI の違い"
    - `nanobot agent`: ローカル CLI の対話モード（ターミナル上で会話）
    - `nanobot gateway`: サーバーを起動して、チャットプラットフォームからのメッセージを継続的に待ち受け

---

## 完全な設定例

Telegram チャンネルを含む最小構成の例です。

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    }
  }
}
```

---

## 次のステップ

- **Onboarding ウィザードを理解する**: [Onboarding ウィザード詳細](onboarding.md)
- **他のチャットプラットフォームに接続する**: [チャンネル設定ガイド](../channels/index.md)
- **より多くの LLM プロバイダを設定する**: [Providers ドキュメント](../providers/index.md)
- **ツールとスキルを探索する**: [ツールとスキル](../tools-skills/index.md)
