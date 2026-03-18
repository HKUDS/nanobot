# 技能系統使用指南

技能（Skills）是 nanobot 的知識擴充模組，以 Markdown 格式封裝特定領域的操作程序、指令範例與可重複使用的資源。代理根據技能的描述自動判斷何時載入，不需要使用者手動觸發。

---

## 什麼是技能

技能是一個資料夾，至少包含一個 `SKILL.md` 檔案。`SKILL.md` 分為兩個部分：

- **YAML frontmatter**：描述技能的名稱、用途，以及何時應該被啟用
- **Markdown 本文**：技能觸發後載入代理上下文的操作指引

技能遵循 [OpenClaw](https://github.com/openclaw/openclaw) 的規格，可與 OpenClaw 生態系統的技能相容。

---

## 技能格式

```
skill-name/
├── SKILL.md              （必要）
└── （選用資源）
    ├── scripts/          - 可執行腳本（Python / Bash 等）
    ├── references/       - 參考文件（按需載入）
    └── assets/           - 輸出資源（範本、圖片等）
```

### SKILL.md 結構

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

#### frontmatter 欄位說明

| 欄位 | 必填 | 說明 |
|------|------|------|
| `name` | 是 | 技能名稱（小寫字母、數字、連字號） |
| `description` | 是 | 觸發機制，說明技能的功能與使用時機 |
| `always` | 否 | 設為 `true` 表示永遠載入（預設 false） |
| `homepage` | 否 | 相關工具或服務的官方網站 |
| `metadata` | 否 | nanobot 特有的延伸設定（emoji、相依工具等） |

> **重要**：`description` 是技能能否被正確觸發的關鍵。應包含具體的觸發詞、使用場景，以及技能的功能說明。

---

## 安裝技能

### 內建技能

nanobot 在啟動時自動載入 `nanobot/skills/` 目錄下的所有內建技能，無需額外安裝。

### 自訂技能

將技能資料夾放入工作區的 `skills/` 子目錄：

```
~/.nanobot/workspace/
└── skills/
    └── my-skill/
        └── SKILL.md
```

重新啟動 nanobot 後，新技能即可使用。

### 從 ClawHub 安裝

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

安裝後啟動新的工作階段即可使用。

---

## 內建技能

### GitHub（`github`）

透過 `gh` CLI 與 GitHub 互動，進行 Issue、PR、CI 工作流程管理。

**需求**：已安裝 `gh` CLI 並完成 `gh auth login` 認證。

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

**觸發詞**：「查看 PR」、「CI 失敗」、「列出 issues」、「github」、「gh CLI」

---

### 天氣（`weather`）

使用 wttr.in 與 Open-Meteo 查詢當前天氣與預報，完全免費，無需 API 金鑰。

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

**格式代碼**：`%c` 天氣狀況、`%t` 溫度、`%h` 濕度、`%w` 風速、`%l` 地點、`%m` 月相

**單位**：`?m` 公制（預設）、`?u` 英制

**Open-Meteo 備用（JSON 格式）**：

```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=25.04&longitude=121.53&current_weather=true"
```

**觸發詞**：「天氣」、「氣溫」、「今天會下雨嗎」、「氣象預報」

---

### 摘要（`summarize`）

使用 `summarize` CLI 快速摘要 URL、PDF 等本地檔案，以及 YouTube 影片。

**需求**：已安裝 `summarize` CLI（`brew install steipete/tap/summarize`）

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

**常用旗標**：

| 旗標 | 說明 |
|------|------|
| `--length short\|medium\|long\|xl\|xxl\|<字元數>` | 控制摘要長度 |
| `--extract-only` | 僅提取文字，不產生摘要 |
| `--json` | 輸出 JSON 格式 |
| `--youtube auto` | 啟用 YouTube 逐字稿提取 |

**支援的模型 API 金鑰**：`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`、`XAI_API_KEY`

**觸發詞**：「摘要這個連結」、「這個 YouTube 影片在講什麼」、「幫我整理這篇文章」、「transcribe」

---

### Tmux（`tmux`）

遠端控制 tmux 工作階段，適合需要互動式終端機環境的場景。

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

**平行執行多個 AI 代理**：

```bash
SOCKET="${TMPDIR:-/tmp}/codex-army.sock"
for i in 1 2 3; do
  tmux -S "$SOCKET" new-session -d -s "agent-$i"
done
tmux -S "$SOCKET" send-keys -t agent-1 "claude --dangerously-skip-permissions 'Fix bug X'" Enter
```

**需求**：macOS 或 Linux，已安裝 `tmux`

**觸發詞**：「使用 tmux」、「互動式終端機」、「在背景執行並監控」

---

### 記憶體（`memory`）

兩層持久化記憶系統，跨工作階段儲存長期事實與歷史記錄。

**此技能設有 `always: true`，永遠載入。**

#### 檔案結構

| 檔案 | 說明 | 載入方式 |
|------|------|---------|
| `memory/MEMORY.md` | 長期事實：偏好設定、專案背景、人際關係 | 永遠載入到上下文 |
| `memory/HISTORY.md` | 追加式事件日誌，每筆以 `[YYYY-MM-DD HH:MM]` 開頭 | 按需搜尋，不自動載入 |

#### 更新 MEMORY.md

使用 `edit_file` 或 `write_file` 立即記錄重要事實：

```python
# 記錄使用者偏好
edit_file(
    path="memory/MEMORY.md",
    old_text="## 偏好設定\n",
    new_text="## 偏好設定\n- 偏好深色主題\n"
)
```

#### 搜尋歷史記錄

```bash
# 小型歷史檔案：直接讀取並在記憶體中過濾
read_file(path="memory/HISTORY.md")

# 大型歷史檔案：使用 grep 搜尋
exec(command='grep -i "關鍵字" memory/HISTORY.md')

# 跨平台 Python 搜尋
exec(command='python3 -c "from pathlib import Path; text = Path(\'memory/HISTORY.md\').read_text(); print(\'\\n\'.join([l for l in text.splitlines() if \'關鍵字\' in l.lower()][-20:]))"')
```

舊的工作階段對話會在 token 數量超過閾值時自動摘要並追加至 `HISTORY.md`，長期事實自動提取至 `MEMORY.md`。

---

### Cron 技能（`cron`）

提供排程任務的操作指引，說明如何使用 `cron` 工具排程提醒與週期性任務。

詳見 [工具使用指南 - Cron 工具](tools.md#cron-cron)。

---

### ClawHub（`clawhub`）

搜尋 ClawHub 公開技能庫並安裝技能，無需 API 金鑰，使用自然語言向量搜尋。

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

> **重要**：務必加上 `--workdir ~/.nanobot/workspace`，否則技能會安裝到當前目錄而非 nanobot 工作區。

安裝後需要**重新啟動工作階段**才能載入新技能。

**需求**：已安裝 Node.js（`npx` 隨附）

**觸發詞**：「找一個技能」、「安裝技能」、「有什麼技能可以...」、「更新技能」

---

### 技能建立工具（`skill-creator`）

提供完整的技能設計與建立指導，適合需要客製化領域技能的進階使用者。

#### 建立新技能的步驟

1. **理解需求**：收集具體使用範例與觸發詞
2. **規劃內容**：確認需要哪些腳本、參考文件與資源
3. **初始化**：執行 `init_skill.py` 建立資料夾結構
4. **編輯內容**：撰寫 `SKILL.md` 與相關資源
5. **封裝發佈**：執行 `package_skill.py` 產生 `.skill` 檔案
6. **迭代改進**：依實際使用結果調整

```bash
# 初始化技能
scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills

# 帶資源目錄的初始化
scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills \
  --resources scripts,references

# 封裝成 .skill 發佈檔
scripts/package_skill.py my-skill/
```

**觸發詞**：「建立新技能」、「設計技能」、「我想要封裝一個技能」

---

## 建立自訂技能

### 最小範例

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

- **description 決定觸發**：description 是代理決定是否載入技能的唯一依據，應清晰列出觸發場景與使用時機
- **簡潔為主**：技能共用代理的 context window，避免冗長說明
- **延遲載入**：詳細文件放入 `references/` 子目錄，需要時才讀取
- **腳本優於重寫**：反覆使用的程式碼放入 `scripts/`，比讓代理每次重新生成更可靠

### 技能命名規範

- 使用小寫字母、數字與連字號
- 以動詞開頭的短語（如 `fix-pr-comments`、`deploy-aws`）
- 長度不超過 64 字元
- 資料夾名稱與 `name` 欄位保持一致

---

## 與 OpenClaw 的相容性

nanobot 的技能格式完全相容於 OpenClaw 技能規格：

- `name` 與 `description` frontmatter 欄位意義相同
- `always: true` 旗標相同
- 資料夾結構（`scripts/`、`references/`、`assets/`）相同
- `.skill` 封裝格式（ZIP 檔案）相同

nanobot 特有的 `metadata` 欄位（`emoji`、`requires`、`install`）不影響 OpenClaw 相容性，OpenClaw 客戶端會忽略未知欄位。
