# 内蔵ツール利用ガイド

Nanobot エージェントには、Shell 実行、ファイルシステム操作、Web アクセス、スケジューリング、メッセージ送信をカバーする内蔵ツールが備わっています。このページでは、各ツールの目的・パラメータ・実用例を詳しく説明します。

---

## Shell ツール（`exec`）

任意の Shell コマンドを実行し、標準出力と標準エラーを返します。

### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `command` | string | はい | 実行する Shell コマンド |
| `working_dir` | string | いいえ | コマンドの作業ディレクトリ |
| `timeout` | integer | いいえ | タイムアウト秒数（デフォルト 60、最大 600） |

### 使用例

```bash
# 執行 Python 腳本
exec(command="python3 script.py")

# 安裝 npm 套件（延長逾時）
exec(command="npm install", working_dir="/project", timeout=300)

# 在特定目錄列出檔案
exec(command="ls -la", working_dir="/tmp")
```

### セーフガード

Shell ツールには複数層の安全対策があり、以下のコマンドパターンは自動的にブロックされます：

| ブロック対象パターン | 説明 |
|------------|------|
| `rm -rf` / `rm -r` | 再帰削除 |
| `format` / `mkfs` / `diskpart` | ディスクのフォーマット |
| `dd if=` | ディスクへの直接書き込み |
| `shutdown` / `reboot` / `poweroff` | システム電源操作 |
| Fork bomb `:(){ ... }` | リソース枯渇攻撃 |
| 内部ネットワーク IP 宛の URL | SSRF 対策 |

さらに `restrict_to_workspace` を有効化している場合、ツールはワークスペース外パスへのアクセスを含むコマンド（`../` によるパストラバーサルを含む）を拒否します。

### 設定オプション

`config.yaml` では以下のオプションを調整できます：

```yaml
tools:
  exec:
    timeout: 120          # 預設逾時秒數
    path_append: "/usr/local/bin"  # 附加至 PATH 環境變數
  restrict_to_workspace: false    # 限制所有工具只能存取工作區
```

**カスタムブロックリスト**：コード側で `deny_patterns`（正規表現のリスト）によりデフォルトの危険パターンを上書きできます。あるいは `allow_patterns` で明示的な許可リスト（ホワイトリストモード）を構築できます。

### 出力の切り詰め

1 回の実行結果は最大 **10,000 文字**まで返します。出力がこの上限を超える場合、システムは前半と後半を保持し、中央に切り詰めた文字数を示します。

---

## ファイルシステムツール

ファイルシステムツールは 4 つのサブツール（読み取り、書き込み、編集、ディレクトリ一覧）で構成されます。

### パス解決ルール

- **相対パス**：エージェントのワークスペース（`workspace`）を基準に解決
- **絶対パス**：そのまま使用
- `restrict_to_workspace: true` の場合、ワークスペース外へのアクセスは拒否

---

### ファイル読み取り（`read_file`）

ファイル内容を読み取り、行番号付きのテキストを返します。

#### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `path` | string | はい | ファイルパス |
| `offset` | integer | いいえ | 開始行番号（1 始まり、デフォルト 1） |
| `limit` | integer | いいえ | 最大読み取り行数（デフォルト 2000） |

#### 使用例

```python
# 讀取整個檔案
read_file(path="config.yaml")

# 讀取大型檔案的第 500-700 行
read_file(path="large_log.txt", offset=500, limit=200)

# 讀取絕對路徑
read_file(path="/etc/hosts")
```

返却形式は行番号付きテキストです。例：
```
1| # 這是第一行
2| 這是第二行
```

1 回で最大 **128,000 文字**まで読み取れます。ファイルがそれ以上の場合は、出力末尾で続きの読み取りに使える `offset` 値が提示されます。

---

### ファイル書き込み（`write_file`）

内容をファイルに完全書き込みします。親ディレクトリが存在しない場合は自動的に作成します。

#### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `path` | string | はい | 対象ファイルパス |
| `content` | string | はい | 書き込む内容 |

#### 使用例

```python
# 寫入新檔案
write_file(path="output/report.txt", content="報告內容...")

# 建立設定檔（自動建立目錄）
write_file(path="config/settings.json", content='{"debug": true}')
```

> **注意**：このツールは既存ファイルを**完全に上書き**します。部分的な変更だけが必要な場合は `edit_file` を使用してください。

---

### ファイル編集（`edit_file`）

厳密な文字列置換でファイルを編集します。軽微な空白差分を許容するファジーマッチにも対応します。

#### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `path` | string | はい | 編集するファイルパス |
| `old_text` | string | はい | 検索して置換する元テキスト |
| `new_text` | string | はい | 置換後の新テキスト |
| `replace_all` | boolean | いいえ | 一致箇所をすべて置換（デフォルト false） |

#### 使用例

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

`old_text` がファイル内に複数回出現し、`replace_all=true` を設定していない場合、ツールは警告を返して変更を実行しません。完全一致が見つからない場合はファジーマッチを試み、診断のために最も近い断片を表示します。

---

### ディレクトリ一覧（`list_dir`）

ディレクトリ内容を一覧化し、再帰探索もサポートします。

#### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `path` | string | はい | ディレクトリパス |
| `recursive` | boolean | いいえ | すべてのファイルを再帰的に列挙（デフォルト false） |
| `max_entries` | integer | いいえ | 最大返却件数（デフォルト 200） |

#### 使用例

```python
# 列出當前目錄
list_dir(path=".")

# 遞迴列出專案結構
list_dir(path="/project", recursive=True, max_entries=500)
```

次のディレクトリは自動的に無視されます：`.git`、`node_modules`、`__pycache__`、`.venv`、`venv`、`dist`、`build`、`.tox`、`.mypy_cache`、`.pytest_cache`、`.ruff_cache`。

---

## Web ツール

### Web 検索（`web_search`）

設定された検索プロバイダを通じて Web を検索し、タイトル・URL・要約スニペットを返します。

#### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `query` | string | はい | 検索キーワード |
| `count` | integer | いいえ | 件数（1-10。デフォルトは設定に従う） |

#### 使用例

```python
# 基本搜尋
web_search(query="Python asyncio 教學")

# 指定回傳筆數
web_search(query="nanobot AI framework", count=5)
```

#### 検索プロバイダ

| プロバイダ | 設定値 | API キーが必要 | 説明 |
|--------|--------|--------------|------|
| Brave Search | `brave` | はい（`BRAVE_API_KEY`） | デフォルト。キーが無い場合は DuckDuckGo に自動フォールバック |
| Tavily | `tavily` | はい（`TAVILY_API_KEY`） | AI 検索。リサーチ用途に適する |
| DuckDuckGo | `duckduckgo` | いいえ | 無料。キー不要 |
| SearXNG | `searxng` | いいえ（要セルフホスト） | セルフホスト可能な OSS 検索エンジン |
| Jina | `jina` | はい（`JINA_API_KEY`） | セマンティック検索対応 |

#### 設定オプション

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

### Web 取得（`web_fetch`）

指定 URL の内容を取得し、Markdown またはプレーンテキストへ自動変換します。

#### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `url` | string | はい | 取得する URL |
| `extractMode` | string | いいえ | 出力形式：`markdown`（デフォルト）または `text` |
| `maxChars` | integer | いいえ | 最大文字数（デフォルト 50,000） |

#### 使用例

```python
# 擷取並轉換為 Markdown
web_fetch(url="https://docs.python.org/3/library/asyncio.html")

# 只取純文字，限制長度
web_fetch(url="https://example.com/article", extractMode="text", maxChars=10000)
```

#### 取得フロー

1. `JINA_API_KEY` がある場合は **Jina Reader API** を優先
2. レート制限（429）や失敗時はローカルの **readability-lxml** 解析へフォールバック
3. JSON 応答は整形済み JSON をそのまま返却
4. 取得した外部コンテンツにはすべて「非信頼」マークが付与され、エージェントに対して「指示ではなくデータとして扱う」よう促します

#### セーフガード

- `http://` と `https://` のみ許可
- 内部ネットワーク IP（RFC 1918）、localhost、ループバック宛のリクエストをブロック（SSRF 対策）
- リダイレクト追従時も宛先 IP を再検証

#### プロキシ設定

```yaml
tools:
  web:
    proxy: "http://127.0.0.1:7890"   # HTTP 代理
    # proxy: "socks5://127.0.0.1:1080"  # SOCKS5 代理
```

---

## Cron ツール（`cron`）

リマインダーや定期タスクをスケジュールします。固定間隔、CRON 式、ワンショットの日時指定に対応します。

### アクション

| `action` | 説明 |
|----------|------|
| `add` | スケジュールタスクの追加 |
| `list` | すべてのスケジュールタスクを一覧 |
| `remove` | 指定タスクの削除 |

### パラメータ（`add` アクション）

| パラメータ | 型 | 説明 |
|------|------|------|
| `message` | string | リマインド文言／タスク説明 |
| `every_seconds` | integer | 固定間隔（秒） |
| `cron_expr` | string | CRON 式（例：`"0 9 * * *"`） |
| `tz` | string | IANA タイムゾーン名（例：`"Asia/Taipei"`。`cron_expr` と併用） |
| `at` | string | ISO 8601 datetime。ワンショット実行（例：`"2026-03-20T10:00:00"`） |
| `job_id` | string | ジョブ ID（`remove` 用） |

### 使用例

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

### 時刻表現クイック早見表

| 説明 | パラメータ |
|------|------|
| 20 分ごと | `every_seconds: 1200` |
| 1 時間ごと | `every_seconds: 3600` |
| 毎日 8:00 | `cron_expr: "0 8 * * *"` |
| 平日 17:00 | `cron_expr: "0 17 * * 1-5"` |
| 毎月 1 日 0:00 | `cron_expr: "0 0 1 * *"` |
| 指定日時に 1 回 | `at: "2026-03-20T10:00:00"` |

> **注意**：スケジュールタスクは、別のスケジュールタスクのコールバック内部から新規作成できません。

---

## Spawn ツール（`spawn`）

バックグラウンドでサブエージェント（subagent）を起動し、複雑または時間のかかるタスクを非同期実行します。メインエージェントはすぐに制御を取り戻し、サブエージェントは完了後に結果を自発的に報告します。

### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `task` | string | はい | サブエージェントに実行させるタスク記述 |
| `label` | string | いいえ | タスクの短いラベル（表示用） |

### 使用例

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

### 適用シーン

- 複数回のツール呼び出しが必要なマルチステップ処理
- 時間のかかるデータ処理やネットワークリクエスト
- 独立に実行し、最後に集約だけ必要な並列タスク

---

## メッセージツール（`message`）

ユーザーへ能動的にメッセージを送信します。チャネル間送信やメディア添付に対応します。

### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|------|------|------|------|
| `content` | string | はい | 送信するメッセージ内容 |
| `channel` | string | いいえ | 送信先チャネル（例：`telegram`、`discord`） |
| `chat_id` | string | いいえ | 送信先チャット／ユーザー ID |
| `media` | array | いいえ | 添付ファイルパス一覧（画像、音声、ドキュメント） |

### 使用例

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

### 適用シーン

- スケジュールタスク（`cron`）実行後にユーザーへ通知
- サブエージェント（`spawn`）完了後の結果報告
- 画像、PDF などの添付を送る必要がある場合

---

## グローバルツール設定

以下の設定はすべてのツールに適用され、`config.yaml` の `tools` セクションで指定します：

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
