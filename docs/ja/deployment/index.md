# デプロイ概要

このセクションでは、さまざまな環境で nanobot をデプロイする方法を説明し、用途に合った方式を選べるようにします。

## デプロイ方式の比較

| 方式 | コマンド | 想定シーン | 永続性 |
|------|------|----------|--------|
| **CLI エージェント** | `nanobot agent` | 単発の対話、テスト、スクリプト | なし（実行後に終了） |
| **Gateway サービス** | `nanobot gateway` | 長時間稼働、チャットプラットフォーム接続 | 手動またはサービス化で常駐させる |
| **Docker** | `docker compose up -d` | コンテナ環境、CI/CD、分離デプロイ | `restart: unless-stopped` で永続化 |
| **systemd サービス** | `systemctl --user start nanobot-gateway` | Linux サーバー、起動時自動開始 | システムレベルで永続、自動再起動対応 |

## 各方式の説明

### CLI エージェント（`nanobot agent`）

単発の対話や素早いテストに向きます。1 回の対話で終了し、接続は保持しません。

```bash
nanobot agent -m "今日の天気は？"
```

> **注意:** `nanobot agent` はローカル CLI エージェントを起動します。既に動いている `nanobot gateway` プロセスに接続するものではなく、両者は独立しています。

### Gateway サービス（`nanobot gateway`）

Gateway は nanobot の中核サービスで、有効化されたチャットチャンネル（Telegram / Discord / Slack など）へ接続し、メッセージを継続的に待ち受けてエージェントループで処理します。

詳細: [Gateway サービスガイド](./gateway.md)

### Docker

環境の分離や迅速なデプロイ、または Python を直接インストールできないホストでの実行に向きます。

詳細: [Docker デプロイガイド](./docker.md)

### Linux systemd サービス

Linux サーバーで安定して長期運用する場合に適しています。起動時の自動開始、クラッシュ時の自動再起動、システムログ統合が可能です。

詳細: [Linux サービスガイド](./linux-service.md)

## 本番環境 vs 開発環境

### 開発環境の推奨

- `nanobot agent` で素早く機能を試す
- `nanobot gateway` をフォアグラウンドで起動してログを直接見る
- デバッグしやすいよう `"restrictToWorkspace": false` を設定

```bash
# 開発時はフォアグラウンドで起動するとログを直接確認できます
nanobot gateway
```

### 本番環境の推奨

- Docker Compose または systemd サービスで常駐運用する
- `"restrictToWorkspace": true` を有効化して workspace 範囲に制限する
- `journalctl` や `docker compose logs` でログを集約する
- 自動再起動ポリシー（`Restart=always` / `restart: unless-stopped`）を設定する

```bash
# 本番推奨: Docker Compose
docker compose up -d nanobot-gateway

# または systemd（Linux）
systemctl --user enable --now nanobot-gateway
```

## 設定ファイルの場所

どのデプロイ方式でも同じ設定ファイルを使います。

```
~/.nanobot/config.json             # メイン設定
~/.nanobot/workspace/              # workspace ディレクトリ
~/.nanobot/workspace/HEARTBEAT.md  # ハートビートタスク定義
```

初回は対話式セットアップを実行してください。

```bash
nanobot onboard
```

## 参考

- [Gateway サービスガイド](./gateway.md)
- [Docker デプロイガイド](./docker.md)
- [Linux サービスガイド](./linux-service.md)
- [アーキテクチャ](../development/architecture.md)
