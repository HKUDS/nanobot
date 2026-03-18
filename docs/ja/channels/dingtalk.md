# DingTalk / 釘釘

nanobot は DingTalk の **Stream Mode** で接続してメッセージを受信するため、公開 IP や Webhook は不要です。1:1/グループ、画像、ファイルなどのマルチメディアメッセージに対応します。

---

## 前提条件

- DingTalk アカウント
- アプリ作成権限がある DingTalk の企業アカウント

---

## ステップ 1: DingTalk アプリを作成する

1. [DingTalk 開放プラットフォーム](https://open-dev.dingtalk.com/) にアクセスする
2. ログイン後、**アプリ開発** → **企業内部アプリ** を開く
3. **アプリを作成** をクリックし、**DingTalk アプリ** を選ぶ
4. アプリ名と説明を入力して作成する

---

## ステップ 2: ボット機能を追加する

1. アプリ設定で **アプリ機能を追加** → **ボット** を開く
2. **追加を確認** をクリックする
3. ボット設定で次を確認する:
   - **Stream Mode**：**Stream モード**（Webhook URL 不要。WebSocket 受信）を選択していること
   - ボット名と説明を入力する

---

## ステップ 3: 権限を設定する

**権限管理** で、用途に応じて次の権限を申請します。

- `qyapi_chat_group` — グループメッセージ関連（グループで使う場合）
- インタラクティブカード送信の権限（リッチメディア返信が必要な場合）

---

## ステップ 4: Client ID と Client Secret を取得する

1. **アプリ資格情報** ページを開く
2. **AppKey**（Client ID）をコピーする
3. **AppSecret**（Client Secret）をコピーする

---

## ステップ 5: アプリを公開する

**バージョン管理** → バージョン作成 → 審査提出または公開（企業内部アプリは通常そのまま公開できます）。

---

## ステップ 6: config.json を設定する

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

### 完全な設定オプション

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `clientId` | `""` | DingTalk アプリの AppKey（Client ID） |
| `clientSecret` | `""` | DingTalk アプリの AppSecret（Client Secret） |
| `allowFrom` | `[]` | 対話を許可する従業員 Staff ID のリスト |

---

## ステップ 7: 起動する

```bash
nanobot gateway
```

---

## 自分の Staff ID を取得する

`allowFrom` には DingTalk の従業員 Staff ID（staffId）を指定します。形式は `user_abc123` のようになります。

**取得方法:**

1. まず `allowFrom` を `["*"]` にして全員許可にする
2. nanobot を起動して Bot にメッセージを送る
3. nanobot のログに Staff ID が表示される
4. `allowFrom` を更新する

---

## マルチメディア対応

DingTalk チャンネルは次のメディアタイプに対応します。

- **画像**：自動でダウンロードし、AI に渡して処理
- **ファイル**：自動ダウンロード後に処理
- **リッチテキスト（RichText）**：テキストと画像を解析

---

## よくある質問

**Stream Mode とは？**

- Stream Mode は WebSocket 接続を使い、nanobot 側から DingTalk サーバーへ接続します
- HTTP コールバック方式と異なり、公開 IP やリバースプロキシが不要です

**Bot がメッセージを受信できない？**

- **Stream モード**（HTTP コールバックではない）を選んでいるか確認する
- アプリが公開されているか確認する

**グループで Bot が反応しない？**

- DingTalk のグループでは @ボットでのみ反応します
- ボットがグループに招待されているか確認する
