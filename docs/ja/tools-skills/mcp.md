# MCP 統合ガイド

MCP（Model Context Protocol）は Anthropic が提案したオープンプロトコルで、AI エージェントが標準化されたインターフェースを通じて外部ツールサーバへ接続できるようにします。Nanobot は MCP を完全にサポートしており、コアコードを変更せずに任意の MCP サーバが提供するツールを動的にロードできます。

---

## MCP の仕組み

```
Nanobot 代理
  → 啟動時連線 MCP 伺服器
  → 取得工具清單
  → 將每個工具包裝為 mcp_<伺服器名>_<工具名>
  → 代理像使用內建工具一樣呼叫 MCP 工具
```

各 MCP ツールは nanobot 内では `mcp_<サーバ名>_<ツール名>` の形式で表現されます。たとえば `filesystem` という名前の MCP サーバに接続した場合、その `read_file` ツールは nanobot では `mcp_filesystem_read_file` になります。

---

## 設定方法

すべての MCP サーバは `config.yaml` の `tools.mcp_servers` セクションで設定します：

```yaml
tools:
  mcp_servers:
    <伺服器名稱>:
      type: stdio        # 或 sse 或 streamableHttp（可省略，自動偵測）
      command: "..."     # Stdio 模式：執行指令
      args: []           # Stdio 模式：指令參數
      env: {}            # Stdio 模式：額外環境變數
      url: "..."         # HTTP/SSE 模式：端點 URL
      headers: {}        # HTTP/SSE 模式：自訂 HTTP 標頭
      tool_timeout: 30   # 工具呼叫逾時秒數
      enabled_tools:     # 要啟用的工具清單（["*"] 表示全部）
        - "*"
```

### トランスポート種別の自動検出

`type` を省略した場合、nanobot は次のルールで自動検出します：

| 条件 | 検出結果 |
|------|---------|
| `command` がある | `stdio` |
| URL が `/sse` で終わる | `sse` |
| それ以外で `url` がある | `streamableHttp` |

---

## Stdio MCP サーバ

Stdio サーバはローカルでサブプロセスとして実行され、標準入力/出力で通信します。ローカルツールや CLI ラッパーに適しています。

### 例：Filesystem MCP

```yaml
tools:
  mcp_servers:
    filesystem:
      command: "npx"
      args:
        - "-y"
        - "@modelcontextprotocol/server-filesystem"
        - "/Users/john/documents"
      enabled_tools:
        - "read_file"
        - "write_file"
        - "list_directory"
```

このサーバを起動すると、nanobot エージェントは `mcp_filesystem_read_file`、`mcp_filesystem_write_file`、`mcp_filesystem_list_directory` などのツールを利用できます。

### 例：GitHub MCP

```yaml
tools:
  mcp_servers:
    github:
      command: "npx"
      args:
        - "-y"
        - "@modelcontextprotocol/server-github"
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxxxxxxxxxxxx"
      enabled_tools:
        - "create_issue"
        - "get_pull_request"
        - "list_commits"
```

### 例：SQLite MCP

```yaml
tools:
  mcp_servers:
    sqlite:
      command: "uvx"
      args:
        - "mcp-server-sqlite"
        - "--db-path"
        - "/data/mydb.sqlite"
```

### 例：カスタム Python MCP サーバ

```yaml
tools:
  mcp_servers:
    my-tools:
      command: "python3"
      args:
        - "/path/to/my_mcp_server.py"
      env:
        MY_API_KEY: "secret"
      tool_timeout: 60
```

---

## HTTP/SSE MCP サーバ

リモート MCP サーバは HTTP または SSE（Server-Sent Events）で接続され、クラウドサービスや共有ツールサーバに適しています。

### SSE トランスポート

URL が `/sse` で終わる場合、自動的に SSE が使用されます：

```yaml
tools:
  mcp_servers:
    remote-tools:
      url: "https://mcp.example.com/sse"
      headers:
        Authorization: "Bearer your-token-here"
        X-Custom-Header: "value"
      tool_timeout: 45
```

### StreamableHTTP トランスポート

一般的な HTTP エンドポイントは StreamableHTTP を使用します：

```yaml
tools:
  mcp_servers:
    cloud-service:
      url: "https://api.example.com/mcp"
      headers:
        Authorization: "Bearer your-token-here"
      tool_timeout: 60
      enabled_tools:
        - "search"
        - "summarize"
```

### トランスポート種別の明示指定

自動検出が意図と合わない場合は明示的に指定できます：

```yaml
tools:
  mcp_servers:
    my-server:
      type: sse            # 強制使用 SSE
      url: "https://..."
```

---

## ツールのフィルタリング（`enabled_tools`）

`enabled_tools` は MCP サーバからロードするツールを制御し、不要なツールがエージェントの context window を消費するのを防ぎます。

```yaml
enabled_tools:
  - "*"           # 啟用所有工具（預設值）
```

```yaml
enabled_tools:    # 只啟用特定工具（使用 MCP 原始名稱）
  - "read_file"
  - "write_file"
```

```yaml
enabled_tools:    # 也可使用 nanobot 包裝後的名稱
  - "mcp_filesystem_read_file"
  - "mcp_filesystem_write_file"
```

```yaml
enabled_tools: [] # 不啟用任何工具（暫時停用伺服器）
```

`enabled_tools` に指定した名前がサーバの実際の提供ツールと一致しない場合、nanobot はログに警告を記録し、参考として利用可能なツール名を列挙します。

---

## ツールタイムアウト（`tool_timeout`）

各 MCP ツール呼び出しには独立したタイムアウト（秒）が適用されます。タイムアウトするとツールはエラーを返し、エージェントはリトライや別手段への切り替えを選べます。

```yaml
tools:
  mcp_servers:
    slow-service:
      url: "https://..."
      tool_timeout: 120    # 允許最多 120 秒（預設 30）
```

サーバごとに異なるタイムアウト値を設定でき、各ツールの実行時間に合わせられます。

---

## 実用的な MCP サーバ例

よく使われる MCP サーバの設定例です：

### 公式サーバ（`@modelcontextprotocol/*`）

```yaml
tools:
  mcp_servers:
    # 檔案系統存取
    filesystem:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]

    # GitHub 操作
    github:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxx"

    # PostgreSQL 查詢
    postgres:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-postgres",
             "postgresql://user:pass@localhost/mydb"]

    # Brave 搜尋
    brave-search:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-brave-search"]
      env:
        BRAVE_API_KEY: "BSA_xxx"
      enabled_tools:
        - "brave_web_search"
```

### よく使われるサードパーティサーバ

```yaml
tools:
  mcp_servers:
    # Playwright 瀏覽器自動化
    playwright:
      command: "npx"
      args: ["-y", "@playwright/mcp"]
      tool_timeout: 60

    # Puppeteer 瀏覽器控制
    puppeteer:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-puppeteer"]
      tool_timeout: 60

    # 記憶體 / Knowledge Graph
    memory:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-memory"]
```

### 混在構成例

ローカルとリモートの MCP サーバを同時に使う例：

```yaml
tools:
  restrict_to_workspace: false
  mcp_servers:
    # 本地檔案系統工具
    local-fs:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
      tool_timeout: 15

    # 遠端 AI 增強搜尋
    ai-search:
      url: "https://search.example.com/mcp"
      headers:
        Authorization: "Bearer sk-xxx"
      tool_timeout: 30
      enabled_tools:
        - "semantic_search"
        - "summarize_results"

    # 公司內部 API 伺服器
    internal-api:
      type: streamableHttp
      url: "http://internal.corp.com:8080/mcp"
      headers:
        X-Internal-Token: "corp-token"
      tool_timeout: 20
```

---

## トラブルシューティング

### サーバ接続に失敗する

**症状**：起動ログに `MCP server 'xxx': failed to connect` が出る

**よくある原因と対処**：

| 原因 | 対処 |
|------|---------|
| `npx` または `uvx` が未インストール | Node.js または uv をインストール |
| MCP パッケージ名が誤り | パッケージ名を確認し、コマンドを手動実行してみる |
| API キーが未設定 | `env` に正しいキーが入っているか確認 |
| URL に到達できない | リモートサーバが稼働しているか確認 |

stdio サーバを手動テスト：

```bash
npx -y @modelcontextprotocol/server-filesystem /tmp
```

### ツール名が見つからない

**症状**：ログに `enabledTools entries not found: xxx` が出る

`enabled_tools` の名前が実際のツール名と一致していません。nanobot は利用可能名を列挙するため、ログ内容に従って設定を修正してください。

ツール名は次の 2 形式を使えます：
- MCP の元名：`read_file`
- nanobot のラップ名：`mcp_<伺服器名>_read_file`

### ツール呼び出しがタイムアウトする

**症状**：ツールが `MCP tool call timed out after Xs` を返す

`tool_timeout` を増やしてください：

```yaml
tool_timeout: 120
```

### SSE 接続が切断される

長時間実行の SSE 接続では次を確認してください：
- リモートサーバが keep-alive を実装しているか
- プロキシやファイアウォールが長時間接続を切っていないか
- `streamableHttp` トランスポートでテストしてみる

### MCP 関連ログを見る

nanobot 起動時、MCP 接続情報がログに出力されます：

```
INFO  MCP server 'filesystem': connected, 8 tools registered
DEBUG MCP: registered tool 'mcp_filesystem_read_file' from server 'filesystem'
WARN  MCP server 'github': enabledTools entries not found: get_repo. Available: get_repository, ...
```

---

## セキュリティ上の注意

- MCP サーバはエージェントの権限で操作を実行します。サーバの出所が信頼できることを確認してください
- Stdio サーバはローカルで動作し、nanobot と同等のシステム権限を持ちます
- HTTP/SSE サーバの `headers` に API キーが含まれる場合があります。平文で `config.yaml` に書くより、環境変数の利用を推奨します
- Nanobot の SSRF 対策は内蔵 `web_fetch` にのみ適用され、MCP ツールのネットワークリクエストは対象外です
