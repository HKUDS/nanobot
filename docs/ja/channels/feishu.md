# Feishu / 飛書

nanobot は Feishu の **WebSocket 長期接続**でイベントを受信するため、公開 IP や Webhook は不要です。マルチモーダル入力（画像・ファイル）、グループでの @メンション制御、引用返信に対応します。

---

## 前提条件

- Feishu アカウント
- アプリを作成できる権限がある Feishu の企業/チーム

---

## ステップ 1: Feishu アプリを作成する

1. [Feishu 開放プラットフォーム](https://open.feishu.cn/app) にアクセスする
2. **企業自建アプリを作成** をクリックし、名前と説明を入力する
3. アプリ設定で左メニュー **機能** → **ボット** を見つけ、ボット機能を有効化する

---

## ステップ 2: 権限を設定する

左メニュー **開発設定** → **権限管理** で検索し、次の権限を追加します。

- `im:message` — 1:1/グループのメッセージ取得と送信
- `im:message.p2p_msg:readonly` — 1:1 メッセージ受信
- （任意）`im:message.group_at_msg:readonly` — グループで @ボットされたメッセージ受信

---

## ステップ 3: イベントを購読し長期接続モードを選ぶ

1. 左メニュー **開発設定** → **イベント購読** を開く
2. イベント `im.message.receive_v1`（メッセージ受信）を追加する
3. **接続方式は「長期接続でイベントを受信」**（Long Connection）を選ぶ

!!! tip "公開 IP は不要"
    長期接続モードでは nanobot が Feishu サーバーへ能動的に接続するため、Webhook URL や公開 IP は不要です。

---

## ステップ 4: App ID と App Secret を取得する

1. 左メニュー **資格情報と基本情報** を開く
2. **App ID**（形式: `cli_xxx`）をコピーする
3. **App Secret** をコピーする

---

## ステップ 5: アプリを公開する

**バージョン管理と公開** → バージョン作成 → 公開申請（企業アプリの場合は管理者承認が必要な場合があります）。

!!! note "開発テスト"
    開発/テスト段階では公開せずに「オンラインテスト」で機能確認できます。

---

## ステップ 6: config.json を設定する

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "YOUR_APP_SECRET",
      "allowFrom": ["ou_YOUR_OPEN_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### 完全な設定オプション

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "YOUR_APP_SECRET",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": ["ou_YOUR_OPEN_ID"],
      "reactEmoji": "THUMBSUP",
      "groupPolicy": "mention",
      "replyToMessage": false
    }
  }
}
```

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `appId` | `""` | Feishu アプリの App ID |
| `appSecret` | `""` | Feishu アプリの App Secret |
| `encryptKey` | `""` | メッセージ暗号化キー（長期接続では空で可） |
| `verificationToken` | `""` | イベント検証 Token（長期接続では空で可） |
| `allowFrom` | `[]` | 対話を許可するユーザー Open ID のリスト |
| `reactEmoji` | `"THUMBSUP"` | 受信時に付ける emoji reaction |
| `groupPolicy` | `"mention"` | グループメッセージの処理ポリシー（下を参照） |
| `replyToMessage` | `false` | Bot の返信でユーザーの元メッセージを引用するか |

### `groupPolicy` の説明

| 値 | 動作 |
|----|------|
| `"mention"`（デフォルト） | グループ内で @メンションされたときのみ返信 |
| `"open"` | グループ内のすべてのメッセージに返信 |

1:1 チャットは常に返信し、`groupPolicy` の影響を受けません。

---

## ステップ 7: 起動する

```bash
nanobot gateway
```

---

## 自分の Open ID を取得する

`allowFrom` には Feishu ユーザーの Open ID（形式: `ou_xxxxxxxx`）を指定します。

**取得方法:**

1. まず `allowFrom` を `["*"]` にして全員許可にする
2. nanobot を起動し、Bot にメッセージを送る
3. nanobot のログに Open ID が表示される
4. `allowFrom` を `["ou_xxxxxxxx"]` に戻す

---

## マルチモーダル対応

Feishu チャンネルは次のメディアを受信できます。

- **画像**：そのまま AI に渡して処理（視覚モデル対応）
- **音声**：Groq API Key を設定している場合、自動的に文字起こし
- **ファイル**：ダウンロードして AI に渡す
- **スタンプ**：`[sticker]` として表示

---

## よくある質問

**Bot がメッセージを受信できない？**

- アプリが公開され、ボット機能が有効になっているか確認する
- `im.message.receive_v1` を購読しているか確認する
- 受信方式として「長期接続」を選んでいるか確認する

**グループで Bot が反応しない？**

- `groupPolicy` が `"mention"` の場合、@Bot が必要です
- Bot がグループに招待されているか確認する

**`encryptKey` は必要？**

- 長期接続モードでは `encryptKey` と `verificationToken` は空で構いません
- HTTP コールバック方式を使う場合のみ必要です
