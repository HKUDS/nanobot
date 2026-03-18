# Linux systemd サービスガイド

このガイドでは、nanobot Gateway を systemd のユーザーサービスとして設定し、起動時の自動起動、クラッシュ時の自動再起動、そして `journalctl` によるログ統合を実現する方法を説明します。

## なぜ systemd？

- **自動起動**: ログイン後に Gateway が自動起動
- **自動再起動**: 異常終了時にサービスが自動再起動
- **ログ統合**: `journalctl` でログを集約
- **標準的な運用**: 使い慣れた `systemctl` コマンドで管理

## 事前手順

### nanobot がインストールされていることを確認

```bash
which nanobot
# 例: /home/user/.local/bin/nanobot
```

見つからない場合はインストールしてください。

```bash
pip install nanobot-ai
# または uv
uv pip install nanobot-ai
```

### 初期セットアップを完了

```bash
nanobot onboard
# 指示に従って API キーとチャンネル設定を入力
```

## systemd ユーザーサービスを作成

### 1. nanobot のパスを確認

```bash
which nanobot
# 例: /home/user/.local/bin/nanobot
```

### 2. サービスファイル用ディレクトリを作成

```bash
mkdir -p ~/.config/systemd/user
```

### 3. サービスファイルを作成

`~/.config/systemd/user/nanobot-gateway.service` に次を書きます（`nanobot` が `~/.local/bin/` にない場合は `ExecStart` を調整してください）。

```ini
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

> **補足:** `%h` は systemd の展開で、ユーザーのホームディレクトリ（`$HOME`）を指します。

### 4. 有効化して起動

```bash
# systemd 設定を再読み込み
systemctl --user daemon-reload

# 有効化して即時起動
systemctl --user enable --now nanobot-gateway
```

## 日常の管理コマンド

```bash
# 状態を確認
systemctl --user status nanobot-gateway

# 起動
systemctl --user start nanobot-gateway

# 停止
systemctl --user stop nanobot-gateway

# 再起動（設定変更後）
systemctl --user restart nanobot-gateway

# 自動起動を無効化（現在の実行は止めない）
systemctl --user disable nanobot-gateway
```

## ログを見る

```bash
# ライブログ
journalctl --user -u nanobot-gateway -f

# 直近 100 行
journalctl --user -u nanobot-gateway -n 100

# 今日のログ
journalctl --user -u nanobot-gateway --since today

# 期間指定
journalctl --user -u nanobot-gateway --since "2026-01-01 09:00" --until "2026-01-01 18:00"

# JSON 出力（ログ解析向け）
journalctl --user -u nanobot-gateway -o json
```

## サービスファイルを変更する

ポートや設定ファイルパスを変えるなど、サービスファイルを編集した場合は再読み込みが必要です。

```bash
# サービスファイルを編集
vim ~/.config/systemd/user/nanobot-gateway.service

# 再読み込み（必須）
systemctl --user daemon-reload

# 再起動して反映
systemctl --user restart nanobot-gateway
```

## ログアウト後も動かす

デフォルトではユーザーサービスはログイン中のみ動きます。ログアウト後も稼働させたい場合（サーバー用途など）は **lingering** を有効化します。

```bash
loginctl enable-linger $USER
```

有効化確認:

```bash
loginctl show-user $USER | grep Linger
# Linger=yes
```

## 複数インスタンス運用

複数の nanobot インスタンスを同時に動かしたい場合（チャンネルを分離するなど）は、サービスファイルを複数作成します。

### Telegram インスタンス

```ini
# ~/.config/systemd/user/nanobot-telegram.service
[Unit]
Description=Nanobot Gateway (Telegram)
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway --config %h/.nanobot-telegram/config.json
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

### Discord インスタンス

```ini
# ~/.config/systemd/user/nanobot-discord.service
[Unit]
Description=Nanobot Gateway (Discord)
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway --config %h/.nanobot-discord/config.json --port 18791
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

すべてのインスタンスを有効化:

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-telegram
systemctl --user enable --now nanobot-discord
```

## 完全なサービスファイル例（環境変数あり）

環境変数を含むサービスファイル例です。

```ini
[Unit]
Description=Nanobot Gateway
Documentation=https://github.com/HKUDS/nanobot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

# nanobot 実行パス（実際のインストール先に合わせて調整）
ExecStart=%h/.local/bin/nanobot gateway

# 環境変数（任意。config.json に書いてもよい）
# Environment=ANTHROPIC_API_KEY=sk-ant-xxx
# Environment=TELEGRAM_BOT_TOKEN=xxx

# 再起動ポリシー
Restart=always
RestartSec=10

# セキュリティ制限
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

# ログ設定
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

## 環境変数を設定する

環境変数を設定する方法は 2 つあります。

**方法 1: config.json に直接書く（推奨）**

```bash
vim ~/.nanobot/config.json
# 設定ファイルに API キーを書き込む
```

**方法 2: EnvironmentFile を使う**

```ini
[Service]
EnvironmentFile=%h/.nanobot/nanobot.env
ExecStart=%h/.local/bin/nanobot gateway
```

```bash
# ~/.nanobot/nanobot.env
ANTHROPIC_API_KEY=sk-ant-xxx
TELEGRAM_BOT_TOKEN=xxx
```

## トラブルシュート

**サービスが起動しない**

```bash
# 詳細エラーを見る
journalctl --user -u nanobot-gateway -n 50

# 起動コマンドを手動で試す
/home/user/.local/bin/nanobot gateway
```

**サービスが再起動を繰り返す**

```bash
# 再起動理由を確認
systemctl --user status nanobot-gateway
journalctl --user -u nanobot-gateway --since "5 minutes ago"
```

**nanobot が見つからない**

```bash
# インストールパスを確認
which nanobot
pip show nanobot-ai | grep Location

# フルパスを使う
ExecStart=/full/path/to/nanobot gateway
```
