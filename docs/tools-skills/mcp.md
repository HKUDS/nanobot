# MCP 整合指南

MCP（Model Context Protocol）是 Anthropic 提出的開放協定，讓 AI 代理可以透過標準化介面連接外部工具伺服器。Nanobot 完整支援 MCP，可動態載入任意 MCP 伺服器提供的工具，而無需修改核心程式碼。

---

## MCP 的運作原理

```
Nanobot 代理
  → 啟動時連線 MCP 伺服器
  → 取得工具清單
  → 將每個工具包裝為 mcp_<伺服器名>_<工具名>
  → 代理像使用內建工具一樣呼叫 MCP 工具
```

每個 MCP 工具在 nanobot 中以 `mcp_<伺服器名稱>_<工具名稱>` 的格式呈現。例如，連線名為 `filesystem` 的 MCP 伺服器後，其 `read_file` 工具在 nanobot 中名為 `mcp_filesystem_read_file`。

---

## 配置方式

所有 MCP 伺服器在 `config.yaml` 的 `tools.mcp_servers` 區段配置：

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

### 傳輸類型自動偵測

若省略 `type` 欄位，nanobot 依下列規則自動偵測：

| 條件 | 偵測結果 |
|------|---------|
| 有 `command` 欄位 | `stdio` |
| URL 以 `/sse` 結尾 | `sse` |
| 其他有 `url` 欄位 | `streamableHttp` |

---

## Stdio MCP 伺服器

Stdio 伺服器在本機以子程序執行，透過標準輸入/輸出通訊。適合本地工具與 CLI 工具包裝。

### 範例：Filesystem MCP

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

此伺服器啟動後，nanobot 代理可使用 `mcp_filesystem_read_file`、`mcp_filesystem_write_file`、`mcp_filesystem_list_directory` 等工具。

### 範例：GitHub MCP

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

### 範例：SQLite MCP

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

### 範例：自訂 Python MCP 伺服器

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

## HTTP/SSE MCP 伺服器

遠端 MCP 伺服器透過 HTTP 或 SSE（Server-Sent Events）連線，適合雲端服務或共享工具伺服器。

### SSE 傳輸

URL 以 `/sse` 結尾時自動使用 SSE 傳輸：

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

### StreamableHTTP 傳輸

一般 HTTP 端點使用 StreamableHTTP 傳輸：

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

### 顯式指定傳輸類型

若自動偵測不符合預期，可明確指定：

```yaml
tools:
  mcp_servers:
    my-server:
      type: sse            # 強制使用 SSE
      url: "https://..."
```

---

## 工具過濾（`enabled_tools`）

`enabled_tools` 控制要從 MCP 伺服器載入哪些工具，避免不必要的工具佔用代理的 context window。

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

若 `enabled_tools` 中有工具名稱與伺服器實際提供的工具不符，nanobot 會在日誌中記錄警告，並列出可用的工具名稱供參考。

---

## 工具逾時（`tool_timeout`）

每個 MCP 工具呼叫都有獨立的逾時限制（秒）。超時後工具回傳錯誤訊息，代理可選擇重試或採取其他方式。

```yaml
tools:
  mcp_servers:
    slow-service:
      url: "https://..."
      tool_timeout: 120    # 允許最多 120 秒（預設 30）
```

不同伺服器可設定不同的逾時值，以因應各工具的實際執行時間差異。

---

## 實用 MCP 伺服器範例

以下為常見 MCP 伺服器的配置範例：

### 官方伺服器（`@modelcontextprotocol/*`）

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

### 第三方常用伺服器

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

### 混合配置範例

同時使用本地與遠端 MCP 伺服器：

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

## 疑難排解

### 伺服器連線失敗

**現象**：啟動時日誌出現 `MCP server 'xxx': failed to connect`

**常見原因與解決方式**：

| 原因 | 解決方式 |
|------|---------|
| `npx` 或 `uvx` 未安裝 | 安裝 Node.js 或 uv |
| MCP 套件名稱錯誤 | 確認套件名稱，嘗試手動執行指令 |
| API 金鑰未設定 | 確認 `env` 中已填入正確金鑰 |
| URL 不可達 | 確認遠端伺服器是否正常運作 |

手動測試 stdio 伺服器：

```bash
npx -y @modelcontextprotocol/server-filesystem /tmp
```

### 工具名稱找不到

**現象**：日誌出現 `enabledTools entries not found: xxx`

`enabled_tools` 中的名稱不符合實際工具名稱。nanobot 會列出可用名稱，請依據日誌內容修正配置。

工具名稱可使用兩種格式：
- MCP 原始名稱：`read_file`
- nanobot 包裝名稱：`mcp_<伺服器名>_read_file`

### 工具呼叫逾時

**現象**：工具回傳 `MCP tool call timed out after Xs`

增加 `tool_timeout` 值：

```yaml
tool_timeout: 120
```

### SSE 連線中斷

對於長時間執行的 SSE 連線，建議確認：
- 遠端伺服器是否有 keep-alive 機制
- 網路代理或防火牆是否截斷長連線
- 可改用 `streamableHttp` 傳輸類型測試

### 查看 MCP 相關日誌

啟動 nanobot 時，MCP 連線資訊會輸出到日誌：

```
INFO  MCP server 'filesystem': connected, 8 tools registered
DEBUG MCP: registered tool 'mcp_filesystem_read_file' from server 'filesystem'
WARN  MCP server 'github': enabledTools entries not found: get_repo. Available: get_repository, ...
```

---

## 安全注意事項

- MCP 伺服器以代理的身份執行操作，請確認伺服器來源可信
- Stdio 伺服器在本機執行，具有與 nanobot 相同的系統權限
- HTTP/SSE 伺服器的 `headers` 中可能包含 API 金鑰，建議使用環境變數而非明文寫入 `config.yaml`
- Nanobot 的 SSRF 防護僅適用於內建的 `web_fetch` 工具，不覆蓋 MCP 工具的網路請求
