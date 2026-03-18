# チャンネル概要

**チャンネル（Channel）** は nanobot と各チャットプラットフォームをつなぐブリッジです。各チャンネルは特定のメッセージングプラットフォームへ接続し、ユーザーのメッセージを nanobot のメッセージバスへ流し、AI の返答をプラットフォームへ返します。

---

## 対応チャンネル一覧

nanobot は現在、次の 12 プラットフォームに対応しています。

| チャンネル | 説明 | 接続方式 |
|------|------|----------|
| [Telegram](telegram.md) | 最もおすすめの入門プラットフォーム。設定が簡単で安定 | Long Polling |
| [Discord](discord.md) | コミュニティサーバーと DM。添付アップロード対応 | Gateway WebSocket |
| [Slack](slack.md) | 企業向けチャット。スレッド返信対応 | Socket Mode |
| [Feishu](feishu.md) | 企業向けコミュニケーション。マルチモーダル入力対応 | WebSocket 長期接続 |
| [DingTalk](dingtalk.md) | Alibaba 系の企業向けチャット | Stream Mode |
| [WeCom](wecom.md) | Tencent の企業向けプラットフォーム | WebSocket 長期接続 |
| [QQ](qq.md) | QQ 公式 Bot。DM とグループに対応 | WebSocket |
| [Email](email.md) | IMAP 受信 + SMTP 返信。非同期向き | IMAP Polling |
| [Matrix](matrix.md) | 分散型プロトコル。E2EE 対応 | Matrix Sync |
| [WhatsApp](whatsapp.md) | Node.js ブリッジ経由で接続 | WebSocket Bridge |
| [Mochat](mochat.md) | Claw IM オープンプラットフォーム | Socket.IO |

---

## 複数チャンネルを有効化する

`~/.nanobot/config.json` の `channels` で複数チャンネルを `"enabled": true` にすると、nanobot 起動後に有効化されたチャンネルを同時に待ち受けできます。

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    },
    "discord": {
      "enabled": true,
      "token": "YOUR_DISCORD_BOT_TOKEN",
      "allowFrom": ["YOUR_DISCORD_USER_ID"]
    }
  }
}
```

起動:

```bash
nanobot gateway
```

有効化されたチャンネルは、同一の gateway プロセス内で同時に動作します。

---

## チャンネル固有設定とグローバル設定

**グローバル設定** は `channels` オブジェクト直下に置き、すべてのチャンネルに適用されます。

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `sendProgress` | `true` | 生成中のストリーミング進捗メッセージを送信する |
| `sendToolHints` | `false` | ツール呼び出しのヒント（例: `read_file("…")`）をユーザーに表示する |

**チャンネル固有設定** は各チャンネルの子オブジェクトに置きます。グローバルとチャンネルを同時に設定する例:

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

---

## `sendProgress` と `sendToolHints`

### `sendProgress`（デフォルト: `true`）

有効にすると、nanobot は返答生成中の中間テキストを段階的にチャンネルへ送信します。ユーザーは処理中であることを把握でき、完成まで待たずに出力を確認できます。

```json
{
  "channels": {
    "sendProgress": true
  }
}
```

### `sendToolHints`（デフォルト: `false`）

有効にすると、nanobot がツール（ウェブ検索、シェル実行など）を呼ぶ際に、短いヒントメッセージを先に送ります。例:

```
🔧 web_search("nanobot documentation")
```

AI が何をしているか分かりやすくなりますが、静かな運用にしたい場合は無効化がおすすめです。

```json
{
  "channels": {
    "sendToolHints": true
  }
}
```

---

## `allowFrom` アクセス制御

各チャンネルには `allowFrom` があり、どのユーザーが bot を利用できるかを制御します。

| 設定 | 効果 |
|------|------|
| `[]`（空配列）| 全員拒否（デフォルト。設定前は利用不可） |
| `["USER_ID_1", "USER_ID_2"]` | 指定ユーザーのみ許可 |
| `["*"]` | 全員許可（公開モード。慎重に使用） |

!!! warning "セキュリティ上の注意"
    `allowFrom` が空配列の場合、すべてのメッセージは拒否されます。起動前に必ず自分のユーザー ID を設定してください。

---

## 複数インスタンス運用

チャンネルごとに独立した設定ファイルを用意し、各 bot に専用 workspace を割り当てることもできます。

```bash
# チャンネルごとに onboard
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace

# それぞれ gateway を起動
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json
```

詳細は各チャンネルのドキュメントを参照してください。
