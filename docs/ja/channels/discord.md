# Discord

nanobot は Discord Gateway WebSocket で接続するため、公開 IP や Webhook は不要です。Thread 返信、ファイル添付のアップロード、グループ内の @メンション制御に対応します。

---

## 前提条件

- Discord アカウント
- Discord サーバー（テスト用）を 1 つ持っていること

---

## ステップ 1: Discord アプリと Bot を作成する

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセスする
2. 右上の **New Application** をクリックし、名前を入力して作成する
3. 左メニューの **Bot** をクリックする
4. **Add Bot**（または **Reset Token**）→ 確認
5. **Copy** をクリックして **Bot Token** をコピーする

!!! warning "Token の安全性"
    Bot Token はパスワード同等です。バージョン管理へコミットしたり第三者へ共有しないでください。漏洩した場合はこのページで直ちに再生成してください。

---

## ステップ 2: Message Content Intent を有効化する

Bot 設定ページを下にスクロールし、**Privileged Gateway Intents** を設定します。

- **MESSAGE CONTENT INTENT** にチェックする ← **必須（有効化しないとメッセージ本文を読めません）**
- （任意）**SERVER MEMBERS INTENT** にチェック（メンバー情報に基づく許可リスト制御をしたい場合）

最後に **Save Changes** をクリックします。

---

## ステップ 3: 自分のユーザー ID を取得する

1. Discord の設定 → **詳細設定（Advanced）**
2. **開発者モード（Developer Mode）** を有効化
3. 自分のアバターを右クリック → **ユーザー ID をコピー**

取得した数値 ID は次のような形式です: `123456789012345678`

---

## ステップ 4: Bot をサーバーに招待する

1. Developer Portal 左メニューの **OAuth2** → **URL Generator** を開く
2. **Scopes** で `bot` にチェック
3. **Bot Permissions** で次をチェック:
   - `Send Messages`
   - `Read Message History`
   - （任意）`Attach Files`（Bot にファイル送信させたい場合）
4. 生成された URL をコピーし、ブラウザで開いてサーバーを選び承認する

---

## ステップ 5: config.json を設定する

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### 完全な設定オプション

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "gatewayUrl": "wss://gateway.discord.gg/?v=10&encoding=json",
      "intents": 37377,
      "groupPolicy": "mention"
    }
  }
}
```

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `token` | `""` | Discord Bot Token |
| `allowFrom` | `[]` | 対話を許可するユーザーの数値 ID リスト |
| `gatewayUrl` | Discord のデフォルト | Gateway WebSocket URL（通常は変更不要） |
| `intents` | `37377` | Gateway Intents ビットマスク（通常は変更不要） |
| `groupPolicy` | `"mention"` | グループチャンネルメッセージの処理ポリシー（下を参照） |

### `groupPolicy` の説明

| 値 | 動作 |
|----|------|
| `"mention"`（デフォルト） | チャンネル内で @メンションされたときのみ返信 |
| `"open"` | チャンネル内のすべてのメッセージに返信 |

DM（ダイレクトメッセージ）は常に返信し、`groupPolicy` の影響を受けません。

---

## ステップ 6: 起動する

```bash
nanobot gateway
```

---

## Thread 対応

nanobot は Discord のチャンネルで返信するとき、同じスレッド（Thread）内で会話を継続します。各ユーザーの会話コンテキストは独立して管理されます。

---

## 添付ファイル対応

nanobot は Discord の添付を受信/送信できます。

- **受信**：画像やファイルなどの添付はダウンロードされ、AI に渡して処理されます
- **送信**：AI が生成したファイル（コード、画像など）を添付としてアップロードします
- 添付 1 件あたりの上限は **20MB**（Discord 無料プランの制限）

---

## よくある質問

**チャンネルで Bot がメッセージを見られない？**

- **MESSAGE CONTENT INTENT** を有効化しているか確認してください（最も多い原因です）
- Intent がないとイベントは届いても本文を読めません

**サーバーへ招待できているのに反応しない？**

- `allowFrom` に自分のユーザー ID が入っているか確認する
- `groupPolicy` が `"mention"` の場合、メッセージで @bot する必要があります

**Bot Token が間違っている？**

- Token が Bot Token であり、OAuth Client Secret ではないか確認する
- Bot Token は通常 `MT` や `NT` などで始まり、長さは約 70 文字です

**Rate Limit の警告が出る？**

- Discord には API 速度制限があります。nanobot は自動でリトライします
- 頻繁に出る場合は同時リクエスト数を減らすことを検討してください
