# Telegram

Telegram は nanobot を始めるのに最もおすすめの入門チャンネルです。設定が簡単で接続も安定しており、公開 IP や Webhook は不要です。

---

## 前提条件

- Telegram アカウント
- `@BotFather` で Bot を作成できること

---

## ステップ 1: Bot を作成する

1. Telegram で **`@BotFather`** を検索して開く
2. `/newbot` を送信する
3. 指示に従って Bot 名（表示名。例: `My Nanobot`）を入力する
4. Bot のユーザー名（`bot` で終わる必要があります。例: `my_nanobot_bot`）を入力する
5. BotFather から **Bot Token** が返ってきます（例）:

```
123456789:ABCdefGhIJKlmNoPQRstuVWXyz
```

この Token は安全に保管してください。

---

## ステップ 2: 自分のユーザー ID を取得する

bot と対話するには、自分の Telegram ユーザー ID を `allowFrom` の許可リストに追加する必要があります。

**方法:**

1. Telegram の設定 → プロフィールでユーザー名（`@yourUsername`）を確認する
2. もしくは Bot にメッセージを送ると、nanobot のログに数値 ID が表示されます

!!! tip "ユーザー名 vs 数値 ID"
    `allowFrom` には数値 ID（例: `"123456789"`）またはユーザー名（例: `"yourUsername"`。`@` なし）のどちらでも指定できます。

---

## ステップ 3: config.json を設定する

`~/.nanobot/config.json` を編集し、次を追加します。

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456789:ABCdefGhIJKlmNoPQRstuVWXyz",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

### 完全な設定オプション

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "proxy": null,
      "replyToMessage": false,
      "groupPolicy": "mention"
    }
  }
}
```

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `token` | `""` | BotFather が発行した Bot Token |
| `allowFrom` | `[]` | 対話を許可するユーザー ID またはユーザー名のリスト |
| `proxy` | `null` | HTTP/SOCKS プロキシ（例: `"http://127.0.0.1:1080"`） |
| `replyToMessage` | `false` | Bot の返信でユーザーの元メッセージを引用するか |
| `groupPolicy` | `"mention"` | グループメッセージの処理ポリシー（下を参照） |

### `groupPolicy` の説明

| 値 | 動作 |
|----|------|
| `"mention"`（デフォルト） | グループ内で @メンションされたときのみ返信 |
| `"open"` | グループ内のすべてのメッセージに返信 |

DM（ダイレクトメッセージ）は常に返信し、`groupPolicy` の影響を受けません。

---

## ステップ 4: 起動する

```bash
nanobot gateway
```

起動後、Telegram で bot に `/start` または任意のメッセージを送ると対話を開始できます。

---

## 利用可能なコマンド

Bot は Telegram のコマンドメニューに次のコマンドを表示します。

| コマンド | 説明 |
|------|------|
| `/start` | bot を起動 |
| `/new` | 新しい会話を開始（コンテキストをクリア） |
| `/stop` | 現在のタスクを停止 |
| `/help` | 利用可能なコマンドを表示 |
| `/restart` | bot を再起動 |

---

## 音声メッセージの文字起こし

Groq API Key を設定している場合、Telegram の音声メッセージは Whisper で自動的に文字起こしされます。

```json
{
  "providers": {
    "groq": {
      "apiKey": "YOUR_GROQ_API_KEY"
    }
  }
}
```

!!! tip "無料の音声文字起こし"
    Groq は Whisper の無料文字起こし枠を提供しており、個人利用に向いています。

---

## プロキシを使う

中国本土など Telegram が制限される環境では、プロキシ経由で接続できます。

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

`http://`、`https://`、`socks5://` 形式をサポートします。

---

## よくある質問

**Bot がメッセージに反応しない？**

- `allowFrom` に自分のユーザー ID が入っているか確認する
- 空の `allowFrom` は全員拒否です
- nanobot のログを確認し、`Access denied` エラーが出ていないか見る

**Token が無効になる？**

- BotFather からコピーした Token が正しいか（途中に空白がないか）確認する
- Token が漏洩した場合は、BotFather の `/revoke` で再生成できます

**グループで bot が反応しない？**

- `groupPolicy` が `"mention"` の場合、メッセージ内で @bot する必要があります
- bot がグループに追加され、発言権限があるか確認する

**グループでメッセージは届くのに知らない人には返信しない？**

- グループ参加者も `allowFrom` に含める必要があります
- もしくは `allowFrom` を `["*"]` にして全員許可します
