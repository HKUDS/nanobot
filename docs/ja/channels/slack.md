# Slack

nanobot は Slack **Socket Mode** で接続するため、公開 URL や Webhook は不要です。チャンネルでの Thread 返信、ファイルアップロード、絵文字リアクション（reaction）に対応します。

---

## 前提条件

- Slack アカウント
- App をインストールできる権限がある Slack Workspace

---

## ステップ 1: Slack App を作成する

1. [Slack API](https://api.slack.com/apps) にアクセスする
2. **Create New App** → **From scratch** を選ぶ
3. App 名を入力し、対象 Workspace を選ぶ
4. **Create App** をクリックする

---

## ステップ 2: Socket Mode を有効化し App Token を取得する

1. 左メニューの **Socket Mode** をクリックする
2. Socket Mode を **Toggle ON** にする
3. **Generate an app-level token** をクリックする
4. Token 名（例: `nanobot-socket`）を入力する
5. **Add Scope** → `connections:write` を選ぶ
6. **Generate** をクリックし、**App-Level Token**（形式: `xapp-1-...`）をコピーする

---

## ステップ 3: OAuth 権限と Bot Token を設定する

1. 左メニューの **OAuth & Permissions** をクリックする
2. **Bot Token Scopes** に次の Scope を追加する:
   - `chat:write` — メッセージ送信
   - `reactions:write` — リアクション追加
   - `app_mentions:read` — @メンションの読み取り
   - `files:write` — （任意）ファイルアップロード
3. 画面上部の **Install to Workspace** → 承認
4. **Bot User OAuth Token**（形式: `xoxb-...`）をコピーする

---

## ステップ 4: イベントを購読する

1. 左メニューの **Event Subscriptions** をクリックする
2. **Enable Events** を Toggle ON にする
3. **Subscribe to bot events** に次を追加する:
   - `message.im` — DM を受信
   - `message.channels` — チャンネルメッセージを受信
   - `app_mention` — @メンションを受信
4. **Save Changes** をクリックする

---

## ステップ 5: Messages Tab を有効化する

1. 左メニューの **App Home** をクリックする
2. **Show Tabs** セクションで **Messages Tab** を有効化する
3. **Allow users to send Slash commands and messages from the messages tab** にチェックする

---

## ステップ 6: 自分の Slack ユーザー ID を取得する

1. Slack で自分のプロフィールを開く
2. **...** → **メンバー ID をコピー**

形式は次のようになります: `U0123456789`

---

## ステップ 7: config.json を設定する

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-1-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### 完全な設定オプション

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "mode": "socket",
      "botToken": "xoxb-...",
      "appToken": "xapp-1-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention",
      "groupAllowFrom": [],
      "replyInThread": true,
      "reactEmoji": "eyes",
      "doneEmoji": "white_check_mark",
      "dm": {
        "enabled": true,
        "policy": "open",
        "allowFrom": []
      }
    }
  }
}
```

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `mode` | `"socket"` | 接続モード（現在は `"socket"` のみ対応） |
| `botToken` | `""` | Bot User OAuth Token（`xoxb-...`） |
| `appToken` | `""` | App-Level Token（`xapp-...`） |
| `allowFrom` | `[]` | 対話を許可するユーザー ID のリスト |
| `groupPolicy` | `"mention"` | チャンネルメッセージの処理ポリシー（下を参照） |
| `groupAllowFrom` | `[]` | `groupPolicy` が `"allowlist"` のときに許可するチャンネル ID |
| `replyInThread` | `true` | Thread で返信するか |
| `reactEmoji` | `"eyes"` | 受信時に付ける reaction |
| `doneEmoji` | `"white_check_mark"` | 完了時に付ける reaction |
| `dm.enabled` | `true` | DM を受け付けるか |
| `dm.policy` | `"open"` | DM ポリシー |

### `groupPolicy` の説明

| 値 | 動作 |
|----|------|
| `"mention"`（デフォルト） | チャンネル内で @メンションされたときのみ返信 |
| `"open"` | チャンネル内のすべてのメッセージに返信 |
| `"allowlist"` | `groupAllowFrom` に含まれるチャンネルのみ返信 |

---

## ステップ 8: 起動する

```bash
nanobot gateway
```

Bot に DM を送るか、チャンネルで @メンションすると対話を開始できます。

---

## Thread 対応

`replyInThread` はデフォルトで `true` です。Bot の返信は元メッセージの Thread に表示され、チャンネルを見やすく保てます。

Thread 返信を無効化するには:

```json
{
  "channels": {
    "slack": {
      "replyInThread": false
    }
  }
}
```

!!! note "DM では Thread を使いません"
    DM（ダイレクトメッセージ）では `replyInThread` が `true` でも Thread は使われません。

---

## DM を無効化する

Bot をチャンネル専用にしたい場合は DM を無効にできます。

```json
{
  "channels": {
    "slack": {
      "dm": {
        "enabled": false
      }
    }
  }
}
```

---

## よくある質問

**Bot が DM を受け取らない？**

- App Home で Messages Tab を有効化したか確認する
- `message.im` イベントを購読しているか確認する

**チャンネルで Bot が反応しない？**

- `message.channels` と `app_mention` を購読しているか確認する
- `groupPolicy` が `"mention"` の場合、@メンションが必要です

**`xapp` Token とは？**

- App-Level Token で、Bot Token（`xoxb`）とは別物です
- **Socket Mode** 設定で生成し、WebSocket 接続の確立に使います

**インストール後に再承認が必要？**

- Bot Scopes を変更するたびに、**Install to Workspace** を再度クリックして再承認が必要です
