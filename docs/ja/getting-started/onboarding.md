# Onboarding ウィザード

`nanobot onboard` は nanobot の対話式初期化ウィザードです。設定ファイルと workspace テンプレートを作成し、素早く使い始められるようにします。

---

## ウィザードの役割

`nanobot onboard` を実行すると、ウィザードは次を行います。

1. **設定ファイル** `~/.nanobot/config.json` を作成（存在しない場合）
2. **workspace ディレクトリ** `~/.nanobot/workspace/` を作成
3. **workspace テンプレートファイル**（AGENTS.md / USER.md / SOUL.md / TOOLS.md / HEARTBEAT.md）を生成
4. **基本オプションの設定を案内**（LLM プロバイダ、モデルなど）

!!! note "安全に再実行できます"
    `nanobot onboard` を繰り返し実行しても既存の設定や workspace の内容は上書きされず、不足しているファイルだけが補完されます。

---

## ウィザードを実行

```bash
nanobot onboard
```

ウィザードは対話式で、好みの設定を段階的に質問します。完了すると必要なファイルが揃います。

---

## 設定ファイルの場所

### デフォルトパス

| ファイル / ディレクトリ | パス |
|------------|------|
| **設定ファイル** | `~/.nanobot/config.json` |
| **Workspace** | `~/.nanobot/workspace/` |
| **Cron タスク** | `~/.nanobot/cron/` |
| **メディア / 状態** | `~/.nanobot/media/` |

### カスタムパス

`-c`（`--config`）と `-w`（`--workspace`）で任意のパスを指定できます。複数インスタンス運用に便利です。

```bash
# 為特定頻道建立獨立實例
nanobot onboard --config ~/.nanobot-telegram/config.json \
                --workspace ~/.nanobot-telegram/workspace

nanobot onboard --config ~/.nanobot-discord/config.json \
                --workspace ~/.nanobot-discord/workspace
```

!!! tip "複数インスタンス運用"
    `--config` のパスを分けることで、複数の nanobot インスタンスを同時に動かし、異なるチャットプラットフォームや用途にそれぞれ割り当てられます。詳しくは [複数インスタンス運用](../configuration/multi-instance.md) を参照してください。

---

## 設定ファイル（config.json）

ウィザードが生成する `~/.nanobot/config.json` には、利用に必要な設定項目が含まれます。主な構造は次の通りです。

```json
{
  "providers": {
    "openrouter": {
      "apiKey": ""
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter",
      "workspace": "~/.nanobot/workspace"
    }
  },
  "channels": {},
  "tools": {
    "restrictToWorkspace": false
  },
  "gateway": {
    "port": 18790
  }
}
```

### 主要フィールド

| フィールド | 説明 |
|------|------|
| `providers.<name>.apiKey` | LLM プロバイダの API キー |
| `agents.defaults.model` | デフォルトで使うモデル名 |
| `agents.defaults.provider` | デフォルトのプロバイダ（`"auto"` で自動検出） |
| `agents.defaults.workspace` | workspace ディレクトリのパス |
| `channels.<name>.enabled` | 該当チャットチャンネルを有効化するか |
| `tools.restrictToWorkspace` | ツールのアクセス範囲を workspace に制限するか |
| `gateway.port` | Gateway が待ち受ける HTTP ポート（デフォルト 18790） |

---

## Workspace テンプレートファイル

ウィザードは `~/.nanobot/workspace/` に次のテンプレートファイルを作成します。これらは agent のシステムプロンプト（context）として利用されます。

### AGENTS.md — Agent の振る舞いガイド

agent の基本動作、能力、制約を定義します。

```markdown
# Agent Instructions

You are a helpful personal AI assistant powered by nanobot.

## Capabilities
- Answer questions and provide information
- Help with coding, writing, and analysis
- Execute shell commands and manage files
- Search the web for current information

## Guidelines
- Be concise and helpful
- Ask for clarification when needed
- Respect user privacy
```

**用途:** 返答のスタイル、得意分野、制約条件などをカスタマイズします。

### USER.md — ユーザープロファイル

ユーザーの背景、好み、よく使う情報を記述し、よりパーソナライズされた返答を得られるようにします。

```markdown
# User Profile

## About Me
- Name: [Your Name]
- Location: [Your City/Timezone]
- Occupation: [Your Role]

## Preferences
- Language: Traditional Chinese preferred
- Response style: Concise and practical

## Frequently Used
- Work directory: ~/projects
- Preferred editor: vim
```

**用途:** 背景や好みを agent に伝え、繰り返し説明する手間を減らします。

### SOUL.md — Agent の人格定義

agent の性格特性とコミュニケーションスタイルを定義します。

```markdown
# Soul

You have a friendly, professional personality.
You are curious, helpful, and direct.
You communicate clearly and adapt your tone to the conversation.
```

**用途:** 相性のよい人格に調整し、対話体験を整えます。

### TOOLS.md — ツール利用の好み

agent が各種ツールをどのように使うべきかを記述します。

```markdown
# Tool Usage Guidelines

## Shell Commands
- Always explain what a command does before running it
- Ask for confirmation before destructive operations

## Web Search
- Search for current information when needed
- Cite sources when providing factual information

## File Operations
- Work within the workspace directory by default
- Create backups before modifying important files
```

**用途:** ツールを使うタイミングや振る舞いをコントロールします。

### HEARTBEAT.md — 定期タスク設定

gateway が 30 分ごとに自動実行する定期タスクを定義します。

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

!!! info "Heartbeat の仕組み"
    Gateway は 30 分ごとに `HEARTBEAT.md` を読み取り、記載されたタスクを実行し、結果を最後にアクティブだったチャットチャンネルへ送信します。

    **注意:** Gateway（`nanobot gateway`）が起動していること、そして少なくとも一度 bot にメッセージを送って配送先チャンネルが確定していることが必要です。

---

## Workspace をカスタマイズ

workspace ファイルはプレーンテキストの Markdown なので、直接編集できます。

```bash
# 編輯 Agent 指引
vim ~/.nanobot/workspace/AGENTS.md

# 編輯個人資料
vim ~/.nanobot/workspace/USER.md

# 設定定期任務
vim ~/.nanobot/workspace/HEARTBEAT.md
```

### よくあるカスタマイズ例

**中国語で返答させる:**

`AGENTS.md` に次を追加します。

```markdown
## Language
Always respond in Traditional Chinese (繁體中文) unless the user writes in another language.
```

**ツール利用を制限する:**

`AGENTS.md` に次を追加します。

```markdown
## Security
- Never execute shell commands without explicit user approval
- Do not access files outside the workspace directory
```

**専門領域を設定する:**

`AGENTS.md` に次を追加します。

```markdown
## Expertise
You specialize in Python development and data analysis.
Prioritize clean, Pythonic code and provide explanations for complex algorithms.
```

**日次サマリーを設定する:**

`HEARTBEAT.md` に次を追加します。

```markdown
## Periodic Tasks

- [ ] Every morning at 9am: Check today's calendar events and send a summary
- [ ] Every evening at 6pm: Summarize today's news in Traditional Chinese
```

### Workspace テンプレートの自動同期

!!! tip "テンプレート更新"
    nanobot の更新によりテンプレート内容が変わる場合があります。`nanobot onboard` を再実行すると、既存内容を上書きせずに新しいテンプレート項目を補完できます。

---

## `-c` と `-w` フラグを使う

nanobot のすべてのコマンドは `-c`（`--config`）と `-w`（`--workspace`）に対応しており、異なるインスタンスを柔軟に切り替えられます。

### `-c` / `--config`: 設定ファイルを指定

```bash
# 使用指定的設定檔啟動 gateway
nanobot gateway --config ~/.nanobot-telegram/config.json

# 使用指定的設定檔進行 CLI 對話
nanobot agent --config ~/.nanobot-discord/config.json -m "Hello!"
```

### `-w` / `--workspace`: workspace を指定

```bash
# 使用測試用的 workspace
nanobot agent --workspace /tmp/nanobot-test

# 搭配自訂設定檔使用
nanobot agent --config ~/.nanobot-telegram/config.json \
              --workspace /tmp/nanobot-telegram-test
```

!!! note "フラグの優先順位"
    `--workspace` は設定ファイル内の `agents.defaults.workspace` を上書きします（その実行にのみ適用）。

### 複数インスタンス初期化の例

```bash
# 為 Telegram 建立實例
nanobot onboard \
  --config ~/.nanobot-telegram/config.json \
  --workspace ~/.nanobot-telegram/workspace

# 為 Discord 建立實例
nanobot onboard \
  --config ~/.nanobot-discord/config.json \
  --workspace ~/.nanobot-discord/workspace

# 分別啟動（使用不同 port）
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json --port 18791
```

---

## Onboarding フローの全体像

```
nanobot onboard
    ↓
建立 ~/.nanobot/config.json
    ↓
建立 ~/.nanobot/workspace/
    ├── AGENTS.md
    ├── USER.md
    ├── SOUL.md
    ├── TOOLS.md
    └── HEARTBEAT.md
    ↓
編輯 config.json，加入 API 金鑰
    ↓
（選用）編輯 workspace 範本，自訂 agent 行為
    ↓
nanobot agent   ← CLI 對話
nanobot gateway ← 啟動頻道服務
```

---

## 次のステップ

- **クイックスタート**: [5 分クイックセットアップ](quick-start.md)
- **チャットチャンネルに接続**: [チャンネル設定ガイド](../channels/index.md)
- **LLM プロバイダを設定**: [Providers ドキュメント](../providers/index.md)
