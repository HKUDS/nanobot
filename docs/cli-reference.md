# CLI 指令參考

本文件涵蓋 nanobot 所有命令列指令的完整說明。

## 快速參考表

| 指令 | 說明 |
|------|------|
| `nanobot --version` | 顯示版本號碼 |
| `nanobot --help` | 顯示說明文件 |
| `nanobot onboard` | 互動式初始化設定與工作區 |
| `nanobot onboard -c <路徑> -w <路徑>` | 初始化或更新指定實例的設定 |
| `nanobot agent` | 進入互動式對話模式 |
| `nanobot agent -m "..."` | 單次訊息模式（非互動式） |
| `nanobot agent --no-markdown` | 以純文字顯示回應 |
| `nanobot agent --logs` | 對話時顯示執行記錄 |
| `nanobot gateway` | 啟動 Gateway 服務（連接聊天頻道） |
| `nanobot gateway --port <埠號>` | 以指定埠號啟動 Gateway |
| `nanobot status` | 顯示設定與連線狀態 |
| `nanobot channels login` | WhatsApp QR Code 登入 |
| `nanobot channels status` | 顯示各頻道連線狀態 |
| `nanobot plugins list` | 列出所有已安裝的頻道插件 |
| `nanobot provider login <提供商>` | OAuth 登入（openai-codex、github-copilot） |

---

## nanobot — 主命令

```
nanobot [OPTIONS] COMMAND [ARGS]...
```

nanobot 個人 AI 助理框架的主要入口點。

### 全域選項

| 選項 | 說明 |
|------|------|
| `--version`, `-v` | 顯示版本號碼後退出 |
| `--help` | 顯示說明文件 |

### 使用範例

```bash
# 顯示版本
nanobot --version

# 顯示所有可用指令
nanobot --help
```

---

## nanobot onboard

```
nanobot onboard [OPTIONS]
```

互動式初始化設定與工作區。執行精靈引導完成 API 金鑰、LLM 提供商及基本設定。

### 選項

| 選項 | 預設值 | 說明 |
|------|--------|------|
| `-c`, `--config PATH` | `~/.nanobot/config.json` | 設定檔路徑 |
| `-w`, `--workspace PATH` | `~/.nanobot/workspace` | 工作區路徑 |
| `--non-interactive` | `false` | 略過互動式精靈，直接建立或更新設定檔 |

### 行為說明

- **互動模式（預設）**：啟動引導精靈，逐步設定 LLM 提供商、API 金鑰及頻道。
- **非互動模式（`--non-interactive`）**：若設定檔不存在則以預設值建立；若已存在則詢問是否覆寫或更新缺少的欄位。

### 使用範例

```bash
# 互動式初始化（建議首次使用）
nanobot onboard

# 初始化指定實例
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace

# 非互動式建立預設設定檔
nanobot onboard --non-interactive

# 以指定設定檔路徑進行非互動式初始化
nanobot onboard -c ~/my-nanobot/config.json --non-interactive
```

### 完成後的後續步驟

```bash
# 測試設定是否正確
nanobot agent -m "Hello!"

# 啟動 Gateway 服務以連接聊天頻道
nanobot gateway
```

---

## nanobot agent

```
nanobot agent [OPTIONS]
```

直接與 AI 代理人對話。支援單次訊息模式與互動式持續對話。

### 選項

| 選項 | 預設值 | 說明 |
|------|--------|------|
| `-m`, `--message TEXT` | 無 | 單次訊息模式（非互動式），傳送訊息後立即退出 |
| `-c`, `--config PATH` | `~/.nanobot/config.json` | 設定檔路徑 |
| `-w`, `--workspace PATH` | 設定檔中的值 | 工作區路徑（覆寫設定檔中的值） |
| `-s`, `--session TEXT` | `cli:direct` | 工作階段 ID |
| `--markdown` / `--no-markdown` | `--markdown` | 是否將回應以 Markdown 格式渲染 |
| `--logs` / `--no-logs` | `--no-logs` | 對話時是否顯示工具執行記錄 |

### 互動模式快捷鍵

| 按鍵／指令 | 功能 |
|-----------|------|
| `exit`、`quit`、`:q` | 離開對話 |
| `Ctrl+D` | 離開對話 |
| `Ctrl+C` | 離開對話 |
| 上下方向鍵 | 瀏覽歷史指令 |
| 貼上多行文字 | 自動支援多行輸入（bracketed paste） |

### 使用範例

```bash
# 單次訊息模式
nanobot agent -m "今天天氣如何？"

# 進入互動式對話
nanobot agent

# 使用指定設定檔
nanobot agent --config ~/.nanobot-telegram/config.json

# 使用指定工作區
nanobot agent --workspace /tmp/nanobot-test

# 同時指定設定檔與工作區
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test

# 以純文字顯示回應（不渲染 Markdown）
nanobot agent --no-markdown

# 顯示工具執行記錄（除錯用）
nanobot agent --logs

# 單次訊息並顯示記錄
nanobot agent -m "列出工作區檔案" --logs
```

---

## nanobot gateway

```
nanobot gateway [OPTIONS]
```

啟動 nanobot Gateway 服務，連接所有已啟用的聊天頻道（Telegram、Discord、Slack、WhatsApp 等）。Gateway 同時管理排程任務（Cron）與定期心跳檢查。

### 選項

| 選項 | 預設值 | 說明 |
|------|--------|------|
| `-c`, `--config PATH` | `~/.nanobot/config.json` | 設定檔路徑 |
| `-w`, `--workspace PATH` | 設定檔中的值 | 工作區路徑（覆寫設定檔中的值） |
| `-p`, `--port INT` | 設定檔中的值 | 覆寫 Gateway 埠號 |
| `-v`, `--verbose` | `false` | 顯示詳細除錯記錄 |

### 使用範例

```bash
# 啟動 Gateway（使用預設設定）
nanobot gateway

# 指定埠號啟動
nanobot gateway --port 18792

# 使用指定設定檔啟動（多實例部署）
nanobot gateway --config ~/.nanobot-telegram/config.json

# 多個實例同時執行
nanobot gateway --config ~/.nanobot-telegram/config.json &
nanobot gateway --config ~/.nanobot-discord/config.json &
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792 &

# 啟用詳細記錄（除錯用）
nanobot gateway --verbose
```

### 啟動後顯示資訊

Gateway 啟動時會顯示：

- 已啟用的頻道清單
- 已設定的排程任務數量
- 心跳檢查間隔時間

---

## nanobot status

```
nanobot status
```

顯示目前設定與連線狀態，包括設定檔路徑、工作區路徑、使用的模型以及各 LLM 提供商的 API 金鑰狀態。

### 使用範例

```bash
nanobot status
```

### 輸出範例

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

管理聊天頻道連線的子指令群組。

### 子指令

#### nanobot channels login

```
nanobot channels login
```

透過 QR Code 掃描進行 WhatsApp 登入。首次使用或重新授權時執行此指令。

若尚未安裝 Node.js bridge，此指令會自動下載並建置。

**需求：**
- Node.js >= 18
- npm

**使用範例：**

```bash
# 首次 WhatsApp 登入
nanobot channels login

# 重新建置 bridge 後登入（升級後使用）
rm -rf ~/.nanobot/bridge && nanobot channels login
```

---

#### nanobot channels status

```
nanobot channels status
```

以表格形式顯示所有已發現頻道（內建與插件）的啟用狀態。

**使用範例：**

```bash
nanobot channels status
```

**輸出範例：**

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

管理頻道插件的子指令群組。

### 子指令

#### nanobot plugins list

```
nanobot plugins list
```

列出所有已發現的頻道（包含內建頻道與第三方插件），顯示名稱、來源（builtin / plugin）及啟用狀態。

**使用範例：**

```bash
nanobot plugins list
```

---

## nanobot provider

```
nanobot provider COMMAND [ARGS]...
```

管理 LLM 提供商的子指令群組。

### 子指令

#### nanobot provider login

```
nanobot provider login PROVIDER
```

透過 OAuth 流程登入指定的 LLM 提供商。

**參數：**

| 參數 | 說明 |
|------|------|
| `PROVIDER` | 提供商名稱（見下表） |

**支援的 OAuth 提供商：**

| 提供商名稱 | 說明 |
|-----------|------|
| `openai-codex` | OpenAI Codex（OAuth 授權） |
| `github-copilot` | GitHub Copilot（裝置授權流程） |

**使用範例：**

```bash
# 登入 OpenAI Codex
nanobot provider login openai-codex

# 登入 GitHub Copilot
nanobot provider login github-copilot
```

---

## 多實例部署

nanobot 支援同時執行多個獨立實例，每個實例擁有各自的設定檔與工作區。使用 `--config` 作為主要區分參數。

### 快速設定

```bash
# 初始化各實例
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace
nanobot onboard --config ~/.nanobot-feishu/config.json --workspace ~/.nanobot-feishu/workspace

# 分別啟動各實例的 Gateway
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792
```

### 多實例使用 agent 指令

```bash
# 對特定實例發送訊息
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello from Telegram instance"
nanobot agent -c ~/.nanobot-discord/config.json -m "Hello from Discord instance"

# 覆寫工作區（測試用）
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test
```

### 路徑解析邏輯

| 設定項目 | 來源 |
|---------|------|
| 設定檔 | `--config` 指定的路徑 |
| 工作區 | `--workspace` 覆寫 > 設定檔中的 `agents.defaults.workspace` |
| 執行時資料目錄 | 由設定檔位置自動推導 |
