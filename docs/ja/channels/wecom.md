# WeCom / 企業微信

nanobot は 企業微信 AI Bot の **WebSocket 長期接続**でメッセージを受信するため、公開 IP や Webhook は不要です。テキスト、画像、音声、ファイルなどのマルチメディアメッセージに対応します。

---

## 前提条件

- 企業微信の管理者アカウント
- 企業側で AI Bot 機能が有効になっていること

> nanobot はコミュニティ製 Python SDK [wecom-aibot-sdk-python](https://github.com/chengyongru/wecom_aibot_sdk) を使用します。これは公式の [@wecom/aibot-node-sdk](https://www.npmjs.com/package/@wecom/aibot-node-sdk) の Python 版です。

---

## ステップ 1: 任意依存をインストールする

企業微信チャンネルは追加 SDK が必要です。

```bash
pip install nanobot-ai[wecom]
```

`uv` を使う場合:

```bash
uv pip install nanobot-ai[wecom]
```

---

## ステップ 2: 企業微信 AI Bot を作成する

1. [企業微信 管理コンソール](https://work.weixin.qq.com/wework_admin/frame) にログインする
2. **アプリ管理** → **インテリジェントロボット** → **ロボット作成**
3. **API モード** を選び、接続方式は **長期接続**（WebSocket）を選ぶ
4. 作成後、**Bot ID** と **Secret** をコピーする

!!! tip "長期接続モード"
    長期接続（WebSocket）を選ぶと、nanobot が企業微信サーバーへ能動的に接続するため、公開 IP は不要です。

---

## ステップ 3: config.json を設定する

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "botId": "your_bot_id",
      "secret": "your_bot_secret",
      "allowFrom": ["your_user_id"]
    }
  }
}
```

### 完全な設定オプション

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "botId": "your_bot_id",
      "secret": "your_bot_secret",
      "allowFrom": ["your_user_id"],
      "welcomeMessage": ""
    }
  }
}
```

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `botId` | `""` | 企業微信 AI Bot の Bot ID |
| `secret` | `""` | 企業微信 AI Bot の Secret |
| `allowFrom` | `[]` | 対話を許可するユーザー ID のリスト |
| `welcomeMessage` | `""` | 初回対話時に送るウェルカムメッセージ（空なら送信しない） |

---

## ステップ 4: 起動する

```bash
nanobot gateway
```

---

## 自分のユーザー ID を取得する

`allowFrom` に指定するのは企業微信のユーザー ID（userid）です。

**取得方法:**

1. まず `allowFrom` を `["*"]` にして全員許可にする
2. nanobot を起動して Bot にメッセージを送る
3. nanobot のログにユーザー ID が表示される
4. `allowFrom` を更新する

---

## マルチメディア対応

企業微信チャンネルは次のメディアタイプに対応します。

| メッセージ種別 | 処理 |
|----------|----------|
| テキスト | そのまま AI に渡す |
| 画像 | ダウンロードして視覚モデルへ渡す |
| 音声 | Groq を設定している場合は自動文字起こし |
| ファイル | ダウンロードして AI に渡す |
| 混在コンテンツ | すべてのパーツを解析 |

---

## よくある質問

**`nanobot-ai[wecom]` を入れたのに未インストール扱いになる？**

- 正しい Python 環境にインストールされているか確認する
- `uv sync` または `pip install nanobot-ai[wecom]` を再実行する

**Bot が接続できない？**

- Bot ID と Secret が正しいか確認する
- 作成した Bot が「長期接続」モードの API Bot か確認する
- nanobot のログに出るエラー内容を確認する

**ウェルカムメッセージはどう設定する？**

- `welcomeMessage` に任意の文字列を設定すると、初回対話時に自動送信されます
- 空文字の場合は送信されません
