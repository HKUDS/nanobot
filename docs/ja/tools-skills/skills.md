# スキルシステム利用ガイド

スキル（Skills）は nanobot の知識拡張モジュールで、特定領域の手順、コマンド例、再利用可能なリソースを Markdown 形式でパッケージします。エージェントはスキルの説明をもとに、いつ読み込むべきかを自動判定するため、ユーザーが手動でトリガーする必要はありません。

---

## スキルとは

スキルはフォルダであり、少なくとも 1 つの `SKILL.md` を含みます。`SKILL.md` は次の 2 部で構成されます：

- **YAML frontmatter**：スキル名、用途、いつ有効化されるべきかを記述
- **Markdown 本文**：スキルがトリガーされたときに、エージェントのコンテキストへロードされる実行ガイド

スキルは [OpenClaw](https://github.com/openclaw/openclaw) の仕様に従っており、OpenClaw エコシステムのスキルと互換です。

---

## スキル形式

```
skill-name/
├── SKILL.md              （必要）
└── （選用資源）
    ├── scripts/          - 可執行腳本（Python / Bash 等）
    ├── references/       - 參考文件（按需載入）
    └── assets/           - 輸出資源（範本、圖片等）
```

### SKILL.md の構造

```markdown
---
name: my-skill
description: >
  這個技能做什麼，以及在什麼情況下應該被使用。
  包含觸發詞與使用場景說明。
always: false    # 若設為 true，永遠載入此技能（如 memory 技能）
---

# 技能標題

技能的詳細操作指引放在這裡。
```

#### frontmatter フィールド説明

| フィールド | 必須 | 説明 |
|------|------|------|
| `name` | はい | スキル名（小文字、数字、ハイフン） |
| `description` | はい | トリガー機構。スキルの機能と利用タイミングを説明 |
| `always` | いいえ | `true` にすると常時ロード（デフォルト false） |
| `homepage` | いいえ | 関連ツールやサービスの公式サイト |
| `metadata` | いいえ | nanobot 固有の拡張設定（emoji、依存ツールなど） |

> **重要**：`description` はスキルが正しくトリガーされるかどうかの鍵です。具体的なトリガーワード、利用シーン、スキルの機能説明を含めてください。

---

## スキルのインストール

### 内蔵スキル

nanobot は起動時に `nanobot/skills/` 配下の内蔵スキルをすべて自動ロードします。追加インストールは不要です。

### カスタムスキル

スキルフォルダをワークスペースの `skills/` サブディレクトリへ配置します：

```
~/.nanobot/workspace/
└── skills/
    └── my-skill/
        └── SKILL.md
```

nanobot を再起動すると、新しいスキルを利用できます。

### ClawHub からインストール

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

インストール後、新しいセッションを開始すれば利用できます。

---

## 内蔵スキル

### GitHub（`github`）

`gh` CLI で GitHub と連携し、Issue、PR、CI ワークフロー管理を行います。

**要件**：`gh` CLI をインストール済みで、`gh auth login` で認証が完了していること。

```bash
# 查看 PR 的 CI 狀態
gh pr checks 55 --repo owner/repo

# 列出最近的工作流程執行
gh run list --repo owner/repo --limit 10

# 查看失敗步驟的日誌
gh run view <run-id> --repo owner/repo --log-failed

# 以 JSON 格式列出 Issue
gh issue list --repo owner/repo --json number,title \
  --jq '.[] | "\(.number): \(.title)"'
```

**トリガーワード**：「查看 PR」、「CI 失敗」、「列出 issues」、「github」、「gh CLI」

---

### 天気（`weather`）

wttr.in と Open-Meteo を使って現在の天気と予報を取得します。完全無料で API キーは不要です。

```bash
# 快速查詢（單行格式）
curl -s "wttr.in/Taipei?format=3"
# 輸出：Taipei: ⛅️ +22°C

# 含濕度與風速的詳細格式
curl -s "wttr.in/Taipei?format=%l:+%c+%t+%h+%w"

# 完整三日預報
curl -s "wttr.in/Taipei?T"

# 儲存天氣圖
curl -s "wttr.in/Taipei.png" -o /tmp/weather.png
```

**フォーマットコード**：`%c` 天気、`%t` 気温、`%h` 湿度、`%w` 風速、`%l` 地点、`%m` 月相

**単位**：`?m` メートル法（デフォルト）、`?u` ヤード・ポンド法

**Open-Meteo フォールバック（JSON 形式）：**

```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=25.04&longitude=121.53&current_weather=true"
```

**トリガーワード**：「天氣」、「氣溫」、「今天會下雨嗎」、「氣象預報」

---

### 要約（`summarize`）

`summarize` CLI を使って、URL や PDF などのローカルファイル、YouTube 動画を素早く要約します。

**要件**：`summarize` CLI をインストール済み（`brew install steipete/tap/summarize`）

```bash
# 摘要網頁文章
summarize "https://example.com/article" --model google/gemini-3-flash-preview

# 摘要本地 PDF
summarize "/path/to/document.pdf" --model google/gemini-3-flash-preview

# 摘要 YouTube 影片
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto

# 提取逐字稿（不產生摘要）
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto --extract-only
```

**よく使うフラグ**：

| フラグ | 説明 |
|------|------|
| `--length short\|medium\|long\|xl\|xxl\|<字元數>` | 要約の長さを制御 |
| `--extract-only` | テキスト抽出のみ（要約は生成しない） |
| `--json` | JSON 形式で出力 |
| `--youtube auto` | YouTube の文字起こし抽出を有効化 |

**対応モデルの API キー**：`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`、`XAI_API_KEY`

**トリガーワード**：「摘要這個連結」、「這個 YouTube 影片在講什麼」、「幫我整理這篇文章」、「transcribe」

---

### Tmux（`tmux`）

tmux セッションをリモート操作します。対話型ターミナル環境が必要な場面に適しています。

```bash
# 建立隔離的工作階段
SOCKET="${TMPDIR:-/tmp}/nanobot.sock"
SESSION=nanobot-work

tmux -S "$SOCKET" new -d -s "$SESSION" -n shell

# 在工作階段中啟動 Python REPL
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -- \
  'PYTHON_BASIC_REPL=1 python3 -q' Enter

# 擷取輸出（最近 200 行）
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200

# 傳送指令
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -l -- "print('hello')"
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 Enter

# 清理工作階段
tmux -S "$SOCKET" kill-session -t "$SESSION"
```

**複数の AI エージェントを並列実行：**

```bash
SOCKET="${TMPDIR:-/tmp}/codex-army.sock"
for i in 1 2 3; do
  tmux -S "$SOCKET" new-session -d -s "agent-$i"
done
tmux -S "$SOCKET" send-keys -t agent-1 "claude --dangerously-skip-permissions 'Fix bug X'" Enter
```

**要件**：macOS または Linux、`tmux` をインストール済み

**トリガーワード**：「使用 tmux」、「互動式終端機」、「在背景執行並監控」

---

### メモリ（`memory`）

2 層の永続メモリシステムで、セッションをまたいで長期的な事実と履歴を保存します。

**このスキルは `always: true` が設定されており、常時ロードされます。**

#### ファイル構造

| ファイル | 説明 | ロード方法 |
|------|------|---------|
| `memory/MEMORY.md` | 長期事実：好み、プロジェクト背景、人間関係 | 常時コンテキストへロード |
| `memory/HISTORY.md` | 追記型のイベントログ。各行は `[YYYY-MM-DD HH:MM]` で開始 | 必要に応じて検索（自動ロードしない） |

#### MEMORY.md を更新

`edit_file` または `write_file` で重要な事実をすぐに記録できます：

```python
# 記錄使用者偏好
edit_file(
    path="memory/MEMORY.md",
    old_text="## 偏好設定\n",
    new_text="## 偏好設定\n- 偏好深色主題\n"
)
```

#### 履歴の検索

```bash
# 小型歷史檔案：直接讀取並在記憶體中過濾
read_file(path="memory/HISTORY.md")

# 大型歷史檔案：使用 grep 搜尋
exec(command='grep -i "關鍵字" memory/HISTORY.md')

# 跨平台 Python 搜尋
exec(command='python3 -c "from pathlib import Path; text = Path(\'memory/HISTORY.md\').read_text(); print(\'\\n\'.join([l for l in text.splitlines() if \'關鍵字\' in l.lower()][-20:]))"')
```

過去のセッション会話は、トークン数が閾値を超えると自動的に要約されて `HISTORY.md` に追記されます。長期事実は自動抽出され `MEMORY.md` に反映されます。

---

### Cron スキル（`cron`）

スケジュール機能の操作ガイドを提供し、`cron` ツールでリマインダーや定期タスクを設定する方法を説明します。

詳しくは [ツール利用ガイド - Cron ツール](tools.md#cron-cron) を参照してください。

---

### ClawHub（`clawhub`）

ClawHub の公開スキルリポジトリを検索し、スキルをインストールします。API キーは不要で、自然言語ベクトル検索を利用します。

```bash
# 搜尋技能
npx --yes clawhub@latest search "web scraping" --limit 5

# 安裝技能（必須指定 --workdir）
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace

# 更新所有已安裝技能
npx --yes clawhub@latest update --all --workdir ~/.nanobot/workspace

# 列出已安裝技能
npx --yes clawhub@latest list --workdir ~/.nanobot/workspace
```

> **重要**：必ず `--workdir ~/.nanobot/workspace` を付けてください。付けない場合、スキルは nanobot のワークスペースではなく現在のディレクトリにインストールされます。

インストール後は**セッションの再起動**が必要です。

**要件**：Node.js をインストール済み（`npx` が付属）

**トリガーワード**：「找一個技能」、「安裝技能」、「有什麼技能可以...」、「更新技能」

---

### スキル作成ツール（`skill-creator`）

スキルの設計と作成に関する包括的なガイドを提供します。カスタム領域スキルが必要な上級ユーザー向けです。

#### 新規スキル作成手順

1. **要件理解**：具体的な利用例とトリガーワードを収集
2. **内容計画**：必要なスクリプト、参考資料、リソースを確定
3. **初期化**：`init_skill.py` でフォルダ構造を生成
4. **内容編集**：`SKILL.md` と関連リソースを作成
5. **パッケージ化と配布**：`package_skill.py` で `.skill` ファイルを生成
6. **反復改善**：実運用結果に基づき調整

```bash
# 初始化技能
scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills

# 帶資源目錄的初始化
scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills \
  --resources scripts,references

# 封裝成 .skill 發佈檔
scripts/package_skill.py my-skill/
```

**トリガーワード**：「建立新技能」、「設計技能」、「我想要封裝一個技能」

---

## カスタムスキルを作る

### 最小例

```
~/.nanobot/workspace/skills/
└── my-helper/
    └── SKILL.md
```

```markdown
---
name: my-helper
description: >
  協助處理公司內部 Jira 票券。當使用者詢問 Jira 相關操作
  （查票、建票、更新狀態、指派人員）時觸發此技能。
---

# Jira Helper

## 查詢票券

```bash
curl -H "Authorization: Bearer $JIRA_TOKEN" \
  "https://company.atlassian.net/rest/api/3/issue/PROJ-123"
```

## 建立票券

```bash
curl -X POST -H "Authorization: Bearer $JIRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fields": {"project": {"key": "PROJ"}, "summary": "標題", "issuetype": {"name": "Task"}}}' \
  "https://company.atlassian.net/rest/api/3/issue"
```
```

### 設計原則

- **description がトリガーを決める**：`description` はエージェントがスキルをロードするかどうかを判断する唯一の根拠です。トリガー場面と利用タイミングを明確に列挙してください
- **簡潔第一**：スキルはエージェントの context window を共有するため、冗長な説明は避けてください
- **遅延ロード**：詳細ドキュメントは `references/` に置き、必要時のみ読み取り
- **スクリプト優先**：繰り返し使うコードは `scripts/` に置く方が、毎回生成させるより信頼性が高いです

### スキル命名規約

- 小文字、数字、ハイフンを使用
- 動詞始まりの短いフレーズ（例：`fix-pr-comments`、`deploy-aws`）
- 長さは 64 文字以内
- フォルダ名は `name` フィールドと一致させる

---

## OpenClaw との互換性

nanobot のスキル形式は OpenClaw スキル仕様と完全互換です：

- frontmatter の `name` と `description` の意味は同一
- `always: true` フラグも同一
- フォルダ構成（`scripts/`、`references/`、`assets/`）も同一
- `.skill` パッケージ形式（ZIP）も同一

nanobot 固有の `metadata` フィールド（`emoji`、`requires`、`install`）は OpenClaw 互換性に影響しません。OpenClaw クライアントは未知のフィールドを無視します。
