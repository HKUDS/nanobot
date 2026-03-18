# CLI コマンドリファレンス

このドキュメントは、nanobot のすべての CLI コマンドを網羅的に説明します。

## クイック参照

| コマンド | 説明 |
|------|------|
| `nanobot --version` | バージョン番号を表示 |
| `nanobot --help` | ヘルプを表示 |
| `nanobot onboard` | 対話式で設定と workspace を初期化 |
| `nanobot onboard -c <path> -w <path>` | 特定インスタンスの設定を初期化/更新 |
| `nanobot agent` | 対話モードに入る |
| `nanobot agent -m "..."` | 単発メッセージ（非対話）|
| `nanobot agent --no-markdown` | プレーンテキストで応答を表示 |
| `nanobot agent --logs` | 対話中にログを出力 |
| `nanobot gateway` | Gateway サービスを起動（チャットチャンネルへ接続） |
| `nanobot gateway --port <port>` | 指定ポートで Gateway を起動 |
| `nanobot status` | 設定と接続状態を確認 |
| `nanobot channels login` | WhatsApp の QR コードログイン |
| `nanobot channels status` | 各チャネルの接続状態を表示 |
| `nanobot plugins list` | インストール済みチャンネルプラグインを一覧表示 |
| `nanobot provider login <provider>` | OAuth ログイン（openai-codex / github-copilot） |

---

## nanobot — メインコマンド

```
nanobot [OPTIONS] COMMAND [ARGS]...
```

nanobot（個人向け AI アシスタントフレームワーク）の主要エントリポイントです。

### グローバルオプション

| オプション | 説明 |
|------|------|
| `--version`, `-v` | バージョン番号を表示して終了 |
| `--help` | ヘルプを表示 |

### 例

```bash
# バージョンを表示
nanobot --version

# 利用可能なコマンド一覧を確認
nanobot --help
```

---

## nanobot onboard

```
nanobot onboard [OPTIONS]
```

対話式に設定と workspace を初期化します。ウィザードが API キーや LLM プロバイダ、チャネルを順番に案内します。

### オプション

| オプション | デフォルト | 説明 |
|------|--------|------|
| `-c`, `--config PATH` | `~/.nanobot/config.json` | 設定ファイルのパス |
| `-w`, `--workspace PATH` | `~/.nanobot/workspace` | workspace のパス |
| `--non-interactive` | `false` | 対話式ウィザードをスキップして直接設定ファイルを作成/更新 |

### 動作

- **対話式（デフォルト）**: ウィザードが LLM プロバイダ、API キー、チャネルなどを順に確認します。
- **非対話式（`--non-interactive`）**: 設定ファイルがなければデフォルトで作成し、既存ファイルがあれば上書き/不足フィールドの補完を確認します。

### 例

```bash
# 初回は対話式で設定を進めるのがおすすめ
nanobot onboard

# 特定インスタンスを初期化
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace

# 非対話式で標準設定を作成
nanobot onboard --non-interactive

# 指定パスで非対話式初期化
nanobot onboard -c ~/my-nanobot/config.json --non-interactive
```

### 完了後の後続手順

```bash
# 設定が正しく動作するか確認
nanobot agent -m "Hello!"

# チャットチャネルと接続する Gateway を起動
nanobot gateway
```

---

## nanobot agent

```
nanobot agent [OPTIONS]
```

AI エージェントと直接対話します。単発メッセージと対話モードの両方をサポートします。

### オプション

| オプション | デフォルト | 説明 |
|------|--------|------|
| `-m`, `--message TEXT` | なし | 単発メッセージ（非対話）。送信後すぐ終了 |
| `-c`, `--config PATH` | `~/.nanobot/config.json` | 設定ファイルのパス |
| `-w`, `--workspace PATH` | 設定ファイルの値 | workspace のパス（設定を上書き） |
| `-s`, `--session TEXT` | `cli:direct` | セッション ID |
| `--markdown` / `--no-markdown` | `--markdown` | Markdown でのレンダリングを有効化/無効化 |
| `--logs` / `--no-logs` | `--no-logs` | 対話中にツール実行ログを表示 |

### 対話モードのショートカット

| キー/コマンド | 機能 |
|-----------|------|
| `exit` / `quit` / `:q` | 終了 |
| `Ctrl+D` | 終了 |
| `Ctrl+C` | 終了 |
| 上下キー | 履歴参照 |
| 複数行貼り付け | bracketed paste に自動対応 |

### 例

```bash
# 単発メッセージモード
nanobot agent -m "今天天気は？"

# 対話モードに入る
nanobot agent

# 指定設定ファイルを使う
nanobot agent --config ~/.nanobot-telegram/config.json

# 指定 workspace を使う
nanobot agent --workspace /tmp/nanobot-test

# 設定ファイルと workspace を同時に指定
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test

# Markdown をレンダリングせずに純テキストで表示
nanobot agent --no-markdown

# 実行ログを表示（デバッグ）
nanobot agent --logs

# 単発メッセージかつログ表示
nanobot agent -m "workspace 内のファイル一覧" --logs
```

---

## nanobot gateway

```
nanobot gateway [OPTIONS]
```

nanobot Gateway を起動し、有効化されたチャットチャネル（Telegram、Discord、Slack、WhatsApp など）と接続します。Cron や定期ハートビートも Gateway が管理します。

### オプション

| オプション | デフォルト | 説明 |
|------|--------|------|
| `-c`, `--config PATH` | `~/.nanobot/config.json` | 設定ファイルのパス |
| `-w`, `--workspace PATH` | 設定ファイルの値 | workspace のパス（設定を上書き） |
| `-p`, `--port INT` | 設定ファイルの値 | Gateway ポートの上書き |
| `-v`, `--verbose` | `false` | 詳細なデバッグログを表示 |

### 例

```bash
# Gateway をデフォルト設定で起動
nanobot gateway

# ポートを指定して起動
nanobot gateway --port 18792

# 指定設定ファイルで起動（マルチインスタンス）
nanobot gateway --config ~/.nanobot-telegram/config.json

# 複数インスタンスを同時に実行
nanobot gateway --config ~/.nanobot-telegram/config.json &
nanobot gateway --config ~/.nanobot-discord/config.json &
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792 &

# 詳細ログを有効化（デバッグ）
nanobot gateway --verbose
```

### 起動時に表示される情報

- 有効化済みチャネル一覧
- 設定済みスケジュールタスク数
- ハートビートの間隔

---

## nanobot status

```
nanobot status
```

現在の設定と接続状態を表示します（設定ファイル、workspace、使用モデル、各プロバイダの API キー状態など）。

### 例

```bash
nanobot status
```

### 出力例

```
🐈 nanobot Status

Config: /Users/yourname/.nanobot/config.json ✓
Workspace: /Users/yourname/.nanobot/workspace ✓
Model: openrouter/anthropic/claude-3.5-sonnet
OpenRouter: ✓
Anthropic: not set
OpenAI: not set
```

---

## nanobot channels

```
nanobot channels COMMAND [ARGS]...
```

チャットチャネル接続を管理するサブコマンド群です。

### サブコマンド

#### nanobot channels login

```
nanobot channels login
```

QR コードをスキャンして WhatsApp にログインします。初回利用や再認可時に実行してください。

Node.js ブリッジが未インストールの場合、このコマンドが自動的にダウンロード/ビルドします。

**要件:**
- Node.js >= 18
- npm

**例:**

```bash
# 初回 WhatsApp ログイン
nanobot channels login

# bridge を再構築して再ログイン（アップグレード後）
rm -rf ~/.nanobot/bridge && nanobot channels login
```

---

#### nanobot channels status

```
nanobot channels status
```

検出されたすべてのチャネル（内蔵およびプラグイン）の有効状態を表形式で表示します。

**例:**

```bash
nanobot channels status
```

**出力例:**

```
        Channel Status
┌──────────────┬─────────┐
│ Channel      │ Enabled │
├──────────────┼─────────┤
│ Telegram     │ ✓       │
│ Discord      │ ✗       │
│ Slack        │ ✗       │
│ WhatsApp     │ ✓       │
└──────────────┴─────────┘
```

---

## nanobot plugins

```
nanobot plugins COMMAND [ARGS]...
```

チャンネルプラグインを管理するサブコマンド群です。

### サブコマンド

#### nanobot plugins list

```
nanobot plugins list
```

検出されたすべてのチャネル（内蔵 + サードパーティプラグイン）を一覧表示します。表示名、ソース（builtin / plugin）、有効状態を確認できます。

**例:**

```bash
nanobot plugins list
```

---

## nanobot provider

```
nanobot provider COMMAND [ARGS]...
```

LLM プロバイダを管理するサブコマンド群です。

### サブコマンド

#### nanobot provider login

```
nanobot provider login PROVIDER
```

指定した LLM プロバイダへ OAuth フローでログインします。

**引数:**

| 引数 | 説明 |
|------|------|
| `PROVIDER` | プロバイダ名（下表参照） |

**対応 OAuth プロバイダ:**

| プロバイダ | 説明 |
|-----------|------|
| `openai-codex` | OpenAI Codex（OAuth 認可） |
| `github-copilot` | GitHub Copilot（デバイス認可フロー） |

**例:**

```bash
# OpenAI Codex にログイン
nanobot provider login openai-codex

# GitHub Copilot にログイン
nanobot provider login github-copilot
```

---

## 複数インスタンス運用

nanobot は複数の独立インスタンスを同時に実行できます。各インスタンスは別個の設定ファイルと workspace を持ち、主に `--config` で区別します。

### クイックセットアップ

```bash
# 各インスタンスを初期化
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace
nanobot onboard --config ~/.nanobot-feishu/config.json --workspace ~/.nanobot-feishu/workspace

# 各インスタンスの Gateway を起動
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792
```

### 複数インスタンスで agent を使う

```bash
# 特定インスタンスへメッセージを送信
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello from Telegram instance"
nanobot agent -c ~/.nanobot-discord/config.json -m "Hello from Discord instance"

# テスト用途で workspace を上書き
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test
```

### パス解決ロジック

| 設定項目 | 由来 |
|---------|------|
| 設定ファイル | `--config` で指定したパス |
| workspace | `--workspace` の値 > 設定ファイル内 `agents.defaults.workspace` |
| 実行時データディレクトリ | 設定ファイルの場所から導出 |
