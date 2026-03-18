# 內建工具使用指南

Nanobot 代理配備了一組內建工具，涵蓋 Shell 執行、檔案系統操作、網路存取、排程與訊息傳送。本頁詳述每個工具的用途、參數與實際範例。

---

## Shell 工具（`exec`）

執行任意 Shell 指令，並回傳標準輸出與標準錯誤。

### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `command` | string | 是 | 要執行的 Shell 指令 |
| `working_dir` | string | 否 | 指令的工作目錄 |
| `timeout` | integer | 否 | 逾時秒數（預設 60，最大 600） |

### 使用範例

```bash
# 執行 Python 腳本
exec(command="python3 script.py")

# 安裝 npm 套件（延長逾時）
exec(command="npm install", working_dir="/project", timeout=300)

# 在特定目錄列出檔案
exec(command="ls -la", working_dir="/tmp")
```

### 安全防護

Shell 工具內建多層安全防護，以下指令模式會被自動封鎖：

| 被封鎖的模式 | 說明 |
|------------|------|
| `rm -rf` / `rm -r` | 遞迴刪除 |
| `format` / `mkfs` / `diskpart` | 磁碟格式化 |
| `dd if=` | 直接寫入磁碟 |
| `shutdown` / `reboot` / `poweroff` | 系統電源操作 |
| Fork bomb `:(){ ... }` | 資源耗盡攻擊 |
| 指向內網 IP 的 URL | SSRF 防護 |

此外，若啟用 `restrict_to_workspace`，工具將拒絕任何存取工作區目錄以外路徑的指令（包含 `../` 路徑穿越）。

### 配置選項

在 `config.yaml` 中可調整下列選項：

```yaml
tools:
  exec:
    timeout: 120          # 預設逾時秒數
    path_append: "/usr/local/bin"  # 附加至 PATH 環境變數
  restrict_to_workspace: false    # 限制所有工具只能存取工作區
```

**自訂封鎖清單**：可在程式碼層級透過 `deny_patterns`（正規表達式清單）覆寫預設的危險指令模式，或使用 `allow_patterns` 建立明確的允許清單（白名單模式）。

### 輸出截斷

單次執行結果最多回傳 **10,000 字元**。若輸出超過此限制，系統會保留前半段與後半段，並在中間標示截斷的字元數量。

---

## 檔案系統工具

檔案系統工具包含四個子工具：讀取、寫入、編輯與列目錄。

### 路徑解析規則

- **相對路徑**：相對於代理的工作區目錄（`workspace`）解析
- **絕對路徑**：直接使用
- 若設定 `restrict_to_workspace: true`，存取工作區以外的路徑會被拒絕

---

### 讀取檔案（`read_file`）

讀取檔案內容，回傳帶行號的文字。

#### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `path` | string | 是 | 檔案路徑 |
| `offset` | integer | 否 | 起始行號（從 1 開始，預設 1） |
| `limit` | integer | 否 | 最多讀取行數（預設 2000） |

#### 使用範例

```python
# 讀取整個檔案
read_file(path="config.yaml")

# 讀取大型檔案的第 500-700 行
read_file(path="large_log.txt", offset=500, limit=200)

# 讀取絕對路徑
read_file(path="/etc/hosts")
```

回傳格式為帶行號的文字，例如：
```
1| # 這是第一行
2| 這是第二行
```

單次最多讀取 **128,000 字元**；若檔案更長，輸出末尾會提示可繼續讀取的 `offset` 值。

---

### 寫入檔案（`write_file`）

將內容完整寫入檔案，若父目錄不存在會自動建立。

#### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `path` | string | 是 | 目標檔案路徑 |
| `content` | string | 是 | 要寫入的內容 |

#### 使用範例

```python
# 寫入新檔案
write_file(path="output/report.txt", content="報告內容...")

# 建立設定檔（自動建立目錄）
write_file(path="config/settings.json", content='{"debug": true}')
```

> **注意**：此工具會**完整覆寫**現有檔案。若只需修改部分內容，請使用 `edit_file`。

---

### 編輯檔案（`edit_file`）

以精確的文字取代方式修改檔案，支援輕微空白差異的模糊匹配。

#### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `path` | string | 是 | 要編輯的檔案路徑 |
| `old_text` | string | 是 | 要搜尋並取代的原始文字 |
| `new_text` | string | 是 | 取代後的新文字 |
| `replace_all` | boolean | 否 | 取代所有符合的位置（預設 false） |

#### 使用範例

```python
# 取代單一出現的文字
edit_file(
    path="config.yaml",
    old_text="debug: false",
    new_text="debug: true"
)

# 批次取代所有出現位置
edit_file(
    path="app.py",
    old_text="import old_module",
    new_text="import new_module",
    replace_all=True
)
```

若 `old_text` 在檔案中出現多次，且未設定 `replace_all=true`，工具會回傳警告而不執行修改。若找不到完全匹配，工具會嘗試模糊匹配並顯示最相似的片段作為診斷提示。

---

### 列出目錄（`list_dir`）

列出目錄內容，支援遞迴瀏覽。

#### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `path` | string | 是 | 目錄路徑 |
| `recursive` | boolean | 否 | 遞迴列出所有檔案（預設 false） |
| `max_entries` | integer | 否 | 最大回傳項目數（預設 200） |

#### 使用範例

```python
# 列出當前目錄
list_dir(path=".")

# 遞迴列出專案結構
list_dir(path="/project", recursive=True, max_entries=500)
```

以下目錄會自動忽略：`.git`、`node_modules`、`__pycache__`、`.venv`、`venv`、`dist`、`build`、`.tox`、`.mypy_cache`、`.pytest_cache`、`.ruff_cache`。

---

## 網路工具

### 網路搜尋（`web_search`）

透過設定的搜尋供應商搜尋網路，回傳標題、URL 與摘要片段。

#### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `query` | string | 是 | 搜尋關鍵字 |
| `count` | integer | 否 | 結果數量（1-10，預設由配置決定） |

#### 使用範例

```python
# 基本搜尋
web_search(query="Python asyncio 教學")

# 指定回傳筆數
web_search(query="nanobot AI framework", count=5)
```

#### 搜尋供應商

| 供應商 | 設定值 | 需要 API 金鑰 | 說明 |
|--------|--------|--------------|------|
| Brave Search | `brave` | 是（`BRAVE_API_KEY`） | 預設供應商；無金鑰時自動退回 DuckDuckGo |
| Tavily | `tavily` | 是（`TAVILY_API_KEY`） | AI 搜尋，適合研究用途 |
| DuckDuckGo | `duckduckgo` | 否 | 免費，無需金鑰 |
| SearXNG | `searxng` | 否（需自架） | 自架開源搜尋引擎 |
| Jina | `jina` | 是（`JINA_API_KEY`） | 支援語意搜尋 |

#### 配置選項

```yaml
tools:
  web:
    search:
      provider: brave          # 搜尋供應商
      api_key: "YOUR_KEY"      # API 金鑰（或透過環境變數設定）
      max_results: 5           # 預設結果數量
    proxy: "http://127.0.0.1:7890"  # HTTP/SOCKS5 代理（可選）
```

---

### 擷取網頁（`web_fetch`）

擷取指定 URL 的內容，自動轉換為 Markdown 或純文字格式。

#### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `url` | string | 是 | 要擷取的 URL |
| `extractMode` | string | 否 | 輸出格式：`markdown`（預設）或 `text` |
| `maxChars` | integer | 否 | 最大字元數（預設 50,000） |

#### 使用範例

```python
# 擷取並轉換為 Markdown
web_fetch(url="https://docs.python.org/3/library/asyncio.html")

# 只取純文字，限制長度
web_fetch(url="https://example.com/article", extractMode="text", maxChars=10000)
```

#### 擷取流程

1. 優先使用 **Jina Reader API**（若有 `JINA_API_KEY`）
2. 遇到限速（429）或失敗時，退回本地 **readability-lxml** 解析
3. JSON 回應直接以格式化 JSON 回傳
4. 所有擷取到的外部內容均附加不信任標記，提示代理將其視為資料而非指令

#### 安全防護

- 僅允許 `http://` 與 `https://` 協定
- 封鎖指向內網 IP（RFC 1918）、localhost、迴路位址的請求（SSRF 防護）
- 跟隨重新導向時亦會重新驗證目標 IP

#### 代理設定

```yaml
tools:
  web:
    proxy: "http://127.0.0.1:7890"   # HTTP 代理
    # proxy: "socks5://127.0.0.1:1080"  # SOCKS5 代理
```

---

## Cron 工具（`cron`）

排程提醒與週期性任務，支援固定間隔、CRON 表達式與一次性定時執行。

### 動作

| `action` | 說明 |
|----------|------|
| `add` | 新增排程任務 |
| `list` | 列出所有排程任務 |
| `remove` | 移除指定任務 |

### 參數（`add` 動作）

| 參數 | 類型 | 說明 |
|------|------|------|
| `message` | string | 提醒文字或任務描述 |
| `every_seconds` | integer | 固定間隔（秒） |
| `cron_expr` | string | CRON 表達式，如 `"0 9 * * *"` |
| `tz` | string | IANA 時區名稱，如 `"Asia/Taipei"`（僅與 `cron_expr` 併用） |
| `at` | string | ISO 8601 datetime，一次性執行，如 `"2026-03-20T10:00:00"` |
| `job_id` | string | 任務 ID（用於 `remove`） |

### 使用範例

```python
# 每 20 分鐘提醒休息
cron(action="add", message="起來動一動！", every_seconds=1200)

# 每天早上 9 點（台北時間）執行任務
cron(action="add", message="查詢今日天氣並回報", cron_expr="0 9 * * *", tz="Asia/Taipei")

# 在特定時間只執行一次
cron(action="add", message="會議提醒：週三下午三點", at="2026-03-18T15:00:00")

# 每週一至週五下午 5 點提醒下班
cron(action="add", message="可以準備下班了", cron_expr="0 17 * * 1-5", tz="Asia/Taipei")

# 列出所有任務
cron(action="list")

# 移除任務（使用 list 取得 job_id）
cron(action="remove", job_id="abc123")
```

### 時間表達式快速對照

| 描述 | 參數 |
|------|------|
| 每 20 分鐘 | `every_seconds: 1200` |
| 每小時 | `every_seconds: 3600` |
| 每天早上 8 點 | `cron_expr: "0 8 * * *"` |
| 平日下午 5 點 | `cron_expr: "0 17 * * 1-5"` |
| 每月 1 日午夜 | `cron_expr: "0 0 1 * *"` |
| 指定時間一次性 | `at: "2026-03-20T10:00:00"` |

> **注意**：排程任務不能從另一個排程任務的回呼內部建立新任務。

---

## Spawn 工具（`spawn`）

在背景啟動子代理（subagent）非同步執行複雜或耗時的任務，主代理立即取得控制權，子代理完成後會主動回報結果。

### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `task` | string | 是 | 子代理要執行的任務描述 |
| `label` | string | 否 | 任務的簡短標籤（顯示用途） |

### 使用範例

```python
# 背景執行長時間運算
spawn(
    task="分析 /data/logs/ 目錄下所有日誌檔案，統計每小時的錯誤數量，並以表格格式回報結果",
    label="日誌分析"
)

# 同時處理多個獨立任務
spawn(task="從 GitHub API 取得 nanobot 最新發佈版本資訊", label="版本查詢")
spawn(task="搜尋 Python 3.13 的新功能並整理摘要", label="新功能摘要")
```

### 適用情境

- 需要多個工具呼叫的多步驟流程
- 耗時的資料處理或網路請求
- 需要獨立執行、最終才需要匯總結果的平行任務

---

## 訊息工具（`message`）

主動向使用者傳送訊息，支援跨頻道傳送與媒體附件。

### 參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `content` | string | 是 | 要傳送的訊息內容 |
| `channel` | string | 否 | 目標頻道（如 `telegram`、`discord`） |
| `chat_id` | string | 否 | 目標聊天室或使用者 ID |
| `media` | array | 否 | 附件檔案路徑清單（圖片、音訊、文件） |

### 使用範例

```python
# 傳送純文字訊息
message(content="任務已完成！")

# 傳送帶附件的訊息
message(
    content="這是今日的報告",
    media=["/workspace/report.pdf", "/workspace/chart.png"]
)

# 跨頻道傳送（從 Slack 傳送到 Telegram）
message(
    content="部署成功",
    channel="telegram",
    chat_id="123456789"
)
```

### 適用情境

- 排程任務（`cron`）執行完畢後主動通知使用者
- 子代理（`spawn`）完成工作後回報結果
- 需要傳送圖片、PDF 或其他媒體附件時

---

## 全域工具配置

以下配置適用於所有工具，在 `config.yaml` 中的 `tools` 區段設定：

```yaml
tools:
  restrict_to_workspace: false   # 限制所有工具只能存取工作區目錄
  exec:
    timeout: 60                  # Shell 工具預設逾時（秒）
    path_append: ""              # 附加至 PATH 的路徑
  web:
    proxy: null                  # HTTP/SOCKS5 代理 URL
    search:
      provider: brave            # 搜尋供應商
      api_key: ""                # 供應商 API 金鑰
      max_results: 5             # 預設搜尋結果數
  mcp_servers: {}                # MCP 伺服器設定（見 MCP 整合指南）
```
