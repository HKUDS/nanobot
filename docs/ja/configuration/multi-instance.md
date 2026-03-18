# 複数インスタンスガイド

Nanobot は複数の独立インスタンスを同時に実行できます。各インスタンスはそれぞれの設定ファイル、workspace、スケジュール（Cron）、実行時データを持ち、互いに干渉しません。

---

## なぜ複数インスタンス？

| 利用シーン | 説明 |
|----------|------|
| **プラットフォーム分離** | 仕事は Slack + WeCom、個人は Telegram + Discord など |
| **モデル分離** | 片方は Claude で重いタスク、もう片方はローカル Ollama など |
| **workspace 分離** | チーム/プロジェクトごとに作業ディレクトリとメモリを隔離 |
| **セキュリティ境界** | 本番は `restrictToWorkspace` を有効、テストは無効など |
| **スケジュール分離** | インスタンスごとに独立した Cron タスクを保持 |

---

## パス解決ルール

各インスタンスの実行時データは、設定ファイルのパスから派生します。

| コンポーネント | 由来 | 例 |
|------|------|------|
| **設定ファイル** | `--config` | `~/.nanobot-work/config.json` |
| **workspace** | `--workspace` または `agents.defaults.workspace` | `~/.nanobot-work/workspace/` |
| **スケジュール（Cron）** | 設定ファイルのディレクトリ | `~/.nanobot-work/cron/` |
| **メディア/実行時状態** | 設定ファイルのディレクトリ | `~/.nanobot-work/media/` |

> [!NOTE]
> `--config` で読み込む設定ファイルを選びます。workspace はデフォルトではその設定ファイルの `agents.defaults.workspace` から読み取られます。`--workspace` を渡すと一時的に上書きできますが、設定ファイル自体は変更しません。

---

## クイックスタート

### ステップ 1: インスタンスごとの設定と workspace を作成

`nanobot onboard` で設定ファイルパスと workspace を同時に指定します。

```bash
# 仕事用インスタンス
nanobot onboard --config ~/.nanobot-work/config.json \
                --workspace ~/.nanobot-work/workspace

# 個人用インスタンス
nanobot onboard --config ~/.nanobot-personal/config.json \
                --workspace ~/.nanobot-personal/workspace
```

ウィザードは workspace パスを対応する設定ファイルへ書き込むため、以降は手動指定が不要になります。

### ステップ 2: 各インスタンスの設定を編集

`~/.nanobot-work/config.json` と `~/.nanobot-personal/config.json` をそれぞれ編集し、チャンネル認証情報やモデル設定を分けて設定します。

### ステップ 3: すべてのインスタンスを起動

```bash
# 仕事用インスタンス（デフォルトポート 18790）
nanobot gateway --config ~/.nanobot-work/config.json

# 個人用インスタンス（別ポート）
nanobot gateway --config ~/.nanobot-personal/config.json --port 18791
```

---

## 例: 仕事 + 個人の 2 インスタンス

### 仕事用インスタンス設定

`~/.nanobot-work/config.json`

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot-work/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "maxToolIterations": 40
    }
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": true,
    "slack": {
      "enabled": true,
      "botToken": "xoxb-WORK-BOT-TOKEN",
      "appToken": "xapp-WORK-APP-TOKEN",
      "allowFrom": ["U01234567", "U07654321"]
    },
    "wecom": {
      "enabled": true,
      "corpId": "YOUR_CORP_ID",
      "corpSecret": "YOUR_CORP_SECRET",
      "agentId": 1000001,
      "allowFrom": ["zhangsan", "lisi"]
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-work-key"
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  },
  "tools": {
    "restrictToWorkspace": true,
    "exec": {
      "timeout": 60
    },
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "BSA-BRAVE-KEY"
      }
    }
  }
}
```

### 個人用インスタンス設定

`~/.nanobot-personal/config.json`

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot-personal/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192
    }
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": true,
      "token": "TELEGRAM-BOT-TOKEN",
      "allowFrom": ["MY_TELEGRAM_USER_ID"]
    },
    "discord": {
      "enabled": true,
      "token": "DISCORD-BOT-TOKEN",
      "allowFrom": ["MY_DISCORD_USER_ID"]
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-personal-key"
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18791
  },
  "tools": {
    "restrictToWorkspace": false,
    "web": {
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

---

## CLI agent で各インスタンスをテスト

```bash
# 仕事用をテスト
nanobot agent -c ~/.nanobot-work/config.json -m "こんにちは、これは仕事用インスタンスです"

# 個人用をテスト
nanobot agent -c ~/.nanobot-personal/config.json -m "こんにちは、これは個人用インスタンスです"

# 一時 workspace を使用（設定ファイルは変更しない）
nanobot agent -c ~/.nanobot-work/config.json -w /tmp/work-test -m "テスト"
```

> [!NOTE]
> `nanobot agent` はローカル CLI agent を起動し、選択した workspace/config を直接使います。稼働中の `nanobot gateway` プロセスを経由するものではありません。

---

## systemd で複数インスタンスを管理

Linux サーバーでの本番デプロイに適しています。

### サービステンプレート

`/etc/systemd/system/nanobot@.service` を作成します。

```ini
[Unit]
Description=Nanobot AI Assistant - %i instance
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
Group=YOUR_GROUP
WorkingDirectory=/home/YOUR_USER
ExecStart=/home/YOUR_USER/.local/bin/nanobot gateway \
    --config /home/YOUR_USER/.nanobot-%i/config.json
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nanobot-%i

# セキュリティ強化（任意）
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/home/YOUR_USER/.nanobot-%i

[Install]
WantedBy=multi-user.target
```

### 各インスタンスを起動

```bash
# 新しいサービス定義を読み込み
sudo systemctl daemon-reload

# 仕事用を有効化して起動
sudo systemctl enable nanobot@work
sudo systemctl start nanobot@work

# 個人用を有効化して起動
sudo systemctl enable nanobot@personal
sudo systemctl start nanobot@personal

# 状態を確認
sudo systemctl status nanobot@work
sudo systemctl status nanobot@personal

# ログを見る
sudo journalctl -u nanobot@work -f
sudo journalctl -u nanobot@personal -f
```

### 個別のサービスファイル（テンプレートを使わない）

各インスタンスに個別サービスファイルを作る場合、`/etc/systemd/system/nanobot-work.service` を作成します。

```ini
[Unit]
Description=Nanobot AI Assistant - Work Instance
After=network.target

[Service]
Type=simple
User=YOUR_USER
ExecStart=/home/YOUR_USER/.local/bin/nanobot gateway \
    --config /home/YOUR_USER/.nanobot-work/config.json
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

同様に `/etc/systemd/system/nanobot-personal.service` を作り、設定ファイルパスを `~/.nanobot-personal/config.json` に置き換えてください。

---

## 最小構成: 手動コピー

ウィザードを使わない場合は、手動でインスタンスディレクトリを作成できます。

```bash
# ディレクトリ構成を作成
mkdir -p ~/.nanobot-work/workspace
mkdir -p ~/.nanobot-personal/workspace

# ベース設定をコピー
cp ~/.nanobot/config.json ~/.nanobot-work/config.json
cp ~/.nanobot/config.json ~/.nanobot-personal/config.json
```

各設定ファイルで、少なくとも次を変更してください。

1. `agents.defaults.workspace` — 各 workspace を指すようにする
2. チャンネル設定 — プラットフォームの認証情報を入力
3. `gateway.port` — 各インスタンスが異なるポートを使うようにする

---

## インスタンスごとのデータ分離

| データ種類 | 分離方法 | 説明 |
|----------|----------|------|
| workspace ファイル | 各 `workspace` ディレクトリ | エージェントが操作するファイルは完全に独立 |
| メモリ要約 | workspace 内の `memory/` | インスタンスごとに異なる会話文脈を保持 |
| スケジュールタスク | 設定ディレクトリの `cron/` | 独立したスケジュールを維持 |
| メディアキャッシュ | 設定ディレクトリの `media/` | 画像などのメディアは互いに影響しない |
| API キー | 各設定ファイル | インスタンスごとに別アカウント/キーを使える |

---

## FAQ

**Q: ポートが衝突した場合は？**

各インスタンスで `gateway.port` を別々に設定するか、起動時に `--port` で上書きしてください。デフォルトは `18790` です。

**Q: 複数インスタンスで同じ workspace を共有できますか？**

技術的には可能ですが推奨しません。メモリ、スケジュール、作業ファイルが混在し、管理が難しくなります。

**Q: インスタンスが動いていることをどう確認しますか？**

```bash
# 各ポートでプロセスがリッスンしているか確認
lsof -i :18790
lsof -i :18791

# または nanobot status
nanobot status --config ~/.nanobot-work/config.json
nanobot status --config ~/.nanobot-personal/config.json
```

**Q: モデルを動的に切り替えられますか？**

チャットから agent にモデル切替を指示するか、設定ファイルを変更してインスタンスを再起動してください。モデル設定は `--model` で一時的に上書きすることもできます（`nanobot agent` のみ対応）。
