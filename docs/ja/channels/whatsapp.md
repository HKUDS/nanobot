# WhatsApp

nanobot は Node.js Bridge を介して WhatsApp Web プロトコルに接続し、[@whiskeysockets/baileys](https://github.com/WhiskeySockets/Baileys) ライブラリを利用します。Bridge と nanobot の Python プロセスは WebSocket で通信します。

---

## 前提条件

- **Node.js ≥ 18**（必須）
- WhatsApp アカウント（スマホがオンラインであること）

---

## ステップ 1: Node.js バージョンを確認する

```bash
node --version
# v18.0.0 以上が表示されるはずです
```

未インストールの場合は [nodejs.org](https://nodejs.org) からインストールしてください。

---

## ステップ 2: デバイスをリンクする（QR コードをスキャン）

```bash
nanobot channels login
```

実行すると QR コードが表示されます。スマホの WhatsApp で:

1. **設定（Settings）** → **リンク済みデバイス（Linked Devices）**
2. **デバイスをリンク（Link a Device）**
3. ターミナルに表示された QR コードをスキャン

リンクが成功すると Bridge は session 情報を保存するため、以後の再起動で再スキャンは不要です。

!!! tip "初回利用"
    `nanobot channels login` は Node.js Bridge を自動でダウンロード・ビルドします（保存先: `~/.nanobot/bridge/`）。初回は少し時間がかかります。

---

## ステップ 3: config.json を設定する

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+886912345678"]
    }
  }
}
```

### 完全な設定オプション

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "bridgeToken": "",
      "allowFrom": ["+886912345678"]
    }
  }
}
```

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `bridgeUrl` | `"ws://localhost:3001"` | Node.js Bridge の WebSocket URL |
| `bridgeToken` | `""` | Bridge の認証 Token（任意。通常は不要） |
| `allowFrom` | `[]` | 対話を許可する WhatsApp 番号のリスト（国番号付き。例: `+886912345678`） |

---

## ステップ 4: 起動する

ターミナルを 2 つ開きます。

```bash
# ターミナル 1: WhatsApp Bridge を起動
nanobot channels login

# ターミナル 2: nanobot gateway を起動
nanobot gateway
```

!!! note "起動順"
    先に Bridge（`channels login`）を起動し、その後 gateway を起動するのがおすすめです。Bridge は WhatsApp 接続を維持するためバックグラウンドで動作し続けます。

---

## Bridge アーキテクチャ

```
WhatsApp App（スマホ）
    ↕ WhatsApp Web プロトコル
Node.js Bridge（~/.nanobot/bridge/）
    ↕ WebSocket（ws://localhost:3001）
nanobot Python（gateway）
    ↕ メッセージバス
AI Agent
```

Bridge は WhatsApp の低レベルプロトコルを処理し、nanobot はシンプルな WebSocket メッセージ形式で Bridge と通信します。

---

## Bridge を更新する

nanobot をアップグレード後、Bridge 側にも更新がある場合は再ビルドが必要です。

```bash
rm -rf ~/.nanobot/bridge && nanobot channels login
```

!!! warning "手動で再ビルド"
    Bridge の更新は既存インストールに自動適用されません。nanobot のアップグレード後は上記コマンドで手動再ビルドしてください。

---

## よくある質問

**QR コードをスキャンしてもすぐ失効する？**

- WhatsApp の QR コードには有効期限があります。できるだけ早くスキャンしてください
- 失敗した場合は `nanobot channels login` を再実行して新しい QR コードを取得します

**再起動後に再スキャンが必要？**

- 通常は不要です。session 情報は `~/.nanobot/bridge/` に保存されています
- リセットしたい場合はこのディレクトリを削除して `nanobot channels login` を再実行します

**接続が切れたあと自動再接続できない？**

- nanobot は自動で再試行します
- 長時間切断が続く場合、スマホ側でリンクが解除されていることがあり、その場合は再スキャンが必要です

**`allowFrom` の形式は？**

- `+` と国番号を含む国際形式の電話番号を指定します
- 例（台湾の携帯）：`"+886912345678"`
- もしくは `["*"]` で全連絡先を許可します
