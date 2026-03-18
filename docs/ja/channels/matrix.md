# Matrix / Element

nanobot は Matrix の分散型通信プロトコルに対応しており、matrix.org を含む任意の Matrix homeserver で動作します。エンドツーエンド暗号化（E2EE）、メディア添付、柔軟なグループアクセス制御に対応します。

---

## 前提条件

- Matrix アカウント（[matrix.org](https://matrix.org) で無料作成するか、自前の homeserver を利用）
- Element などの Matrix クライアントにログインできること

---

## ステップ 1: Matrix 依存関係をインストールする

Matrix チャンネルは追加依存が必要です。

```bash
pip install nanobot-ai[matrix]
```

`uv` を使う場合:

```bash
uv pip install nanobot-ai[matrix]
```

---

## ステップ 2: Matrix アカウントを作成/選択する

nanobot 用に専用アカウントを作るのがおすすめです。

1. [app.element.io](https://app.element.io) → **アカウント作成**
2. homeserver を選ぶ（デフォルトは `matrix.org`。自前 homeserver の URL を入力してもよい）
3. 作成後、正常にログインできることを確認する

---

## ステップ 3: アクセス資格情報を取得する

次の 3 つの資格情報が必要です。

- **userId**：例 `@nanobot:matrix.org`
- **accessToken**：ログイン用アクセストークン
- **deviceId**：（推奨）デバイス ID。再起動を跨いで暗号化状態を復元するために使います

### Access Token の取得方法

**方法 1: Element クライアントから取得**

1. Element にログインする
2. 左上の自分のアバター → **設定（Settings）**
3. **Help & About** タブへ
4. 下にスクロールし、**Access Token** の横の **Click to reveal** をクリック

**方法 2: API から取得**

```bash
curl -X POST "https://matrix.org/_matrix/client/v3/login" \
  -H "Content-Type: application/json" \
  -d '{"type":"m.login.password","user":"nanobot","password":"YOUR_PASSWORD"}'
```

レスポンスの `access_token` と `device_id` が必要な値です。

---

## ステップ 4: config.json を設定する

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@nanobot:matrix.org",
      "accessToken": "syt_xxx",
      "deviceId": "NANOBOT01",
      "allowFrom": ["@your_user:matrix.org"]
    }
  }
}
```

### 完全な設定オプション

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@nanobot:matrix.org",
      "accessToken": "syt_xxx",
      "deviceId": "NANOBOT01",
      "e2eeEnabled": true,
      "allowFrom": ["@your_user:matrix.org"],
      "groupPolicy": "open",
      "groupAllowFrom": [],
      "allowRoomMentions": false,
      "maxMediaBytes": 20971520,
      "syncStopGraceSeconds": 2
    }
  }
}
```

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `homeserver` | `"https://matrix.org"` | Matrix homeserver URL |
| `userId` | `""` | Bot の Matrix ユーザー ID（`@name:server`） |
| `accessToken` | `""` | ログイン用 Access Token |
| `deviceId` | `""` | デバイス ID（暗号化状態維持のため設定推奨） |
| `e2eeEnabled` | `true` | E2EE（エンドツーエンド暗号化）を有効にするか |
| `allowFrom` | `[]` | 対話を許可するユーザー Matrix ID のリスト |
| `groupPolicy` | `"open"` | ルーム（グループ）メッセージの処理ポリシー（下を参照） |
| `groupAllowFrom` | `[]` | `groupPolicy` が `"allowlist"` のときに許可するルーム ID |
| `allowRoomMentions` | `false` | `@room` メンションに反応するか |
| `maxMediaBytes` | `20971520`（20MB） | 添付の最大バイト数（`0` でメディア無効化） |
| `syncStopGraceSeconds` | `2` | 停止時に同期完了を待つ秒数 |

### `groupPolicy` の説明

| 値 | 動作 |
|----|------|
| `"open"`（デフォルト） | ルーム内のすべてのメッセージに返信 |
| `"mention"` | @メンションされたときのみ返信 |
| `"allowlist"` | `groupAllowFrom` に含まれるルームのみ返信 |

---

## ステップ 5: 起動する

```bash
nanobot gateway
```

---

## エンドツーエンド暗号化（E2EE）

Matrix チャンネルはデフォルトで E2EE が有効です。つまり:

- Bot とユーザー間のメッセージは暗号化されます
- 暗号鍵はローカルの `matrix-store` ディレクトリに保存されます

!!! warning "deviceId を固定する"
    `deviceId` は固定し、`matrix-store` ディレクトリを削除しないでください。これらが変わると暗号化セッション状態が失われ、Bot が新しいメッセージを復号できなくなる可能性があります。

E2EE が不要な場合:

```json
{
  "channels": {
    "matrix": {
      "e2eeEnabled": false
    }
  }
}
```

---

## メディア添付対応

Matrix チャンネルはメディア添付を受信/送信できます。

- **受信**：画像、音声、動画、ファイル（暗号化メディアを含む）
- **送信**：AI が生成したファイルを homeserver へアップロード
- `maxMediaBytes` で添付サイズ上限を設定可能

---

## よくある質問

**暗号化ルームで Bot がメッセージを見られない？**

- `e2eeEnabled` が `true` か確認する
- `deviceId` を固定し、`matrix-store` が削除されていないか確認する
- 初回起動時はデバイス検証が必要です

**Access Token が失効する？**

- Matrix の Access Token は通常長期間有効ですが、全デバイスからログアウトすると失効します
- 再ログインして新しい Access Token と Device ID を取得してください

**ルーム（グループ）で Bot が返信しない？**

- デフォルトの `groupPolicy` は `"open"` なので通常は全員に返信します
- Bot がルームに招待され参加しているか確認する
- 権限問題がないかログを確認する

**自前 homeserver の場合は？**

- `homeserver` を自分の URL（例: `"https://matrix.example.com"`）に変更する
- それ以外の設定は同じです
