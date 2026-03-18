# Onboarding 精靈

`nanobot onboard` 是 nanobot 的互動式初始化精靈，負責建立設定檔與 workspace 範本，讓您快速上手。

---

## 精靈的功能

執行 `nanobot onboard` 時，精靈會：

1. **建立設定檔** `~/.nanobot/config.json`（若不存在）
2. **建立 workspace 目錄** `~/.nanobot/workspace/`
3. **生成 workspace 範本檔案**（AGENTS.md、USER.md、SOUL.md、TOOLS.md、HEARTBEAT.md）
4. **引導您設定基本選項**（LLM 提供商、模型等）

!!! note "安全的重複執行"
    重複執行 `nanobot onboard` 不會覆蓋現有的設定或 workspace 內容，只會補充缺少的檔案。

---

## 執行精靈

```bash
nanobot onboard
```

精靈為互動式介面，會逐步詢問您的偏好設定。完成後，所有必要檔案即建立完畢。

---

## 設定檔位置

### 預設路徑

| 檔案 / 目錄 | 路徑 |
|------------|------|
| **設定檔** | `~/.nanobot/config.json` |
| **Workspace** | `~/.nanobot/workspace/` |
| **Cron 任務** | `~/.nanobot/cron/` |
| **媒體 / 狀態** | `~/.nanobot/media/` |

### 自訂路徑

您可以使用 `-c`（`--config`）和 `-w`（`--workspace`）旗標指定自訂路徑，適合多實例部署：

```bash
# 為特定頻道建立獨立實例
nanobot onboard --config ~/.nanobot-telegram/config.json \
                --workspace ~/.nanobot-telegram/workspace

nanobot onboard --config ~/.nanobot-discord/config.json \
                --workspace ~/.nanobot-discord/workspace
```

!!! tip "多實例部署"
    使用不同的 `--config` 路徑，您可以同時運行多個 nanobot 實例，分別服務不同的聊天平台或用途。詳見 [多實例部署](../configuration/multi-instance.md)。

---

## 設定檔說明（config.json）

精靈生成的 `~/.nanobot/config.json` 包含所有設定選項。以下是主要結構：

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

### 關鍵設定欄位

| 欄位 | 說明 |
|------|------|
| `providers.<name>.apiKey` | LLM 提供商的 API 金鑰 |
| `agents.defaults.model` | 預設使用的模型名稱 |
| `agents.defaults.provider` | 預設使用的提供商（`"auto"` 可自動偵測） |
| `agents.defaults.workspace` | Workspace 目錄路徑 |
| `channels.<name>.enabled` | 是否啟用該聊天頻道 |
| `tools.restrictToWorkspace` | 是否限制工具只能存取 workspace 目錄 |
| `gateway.port` | Gateway 監聽的 HTTP port（預設 18790） |

---

## Workspace 範本檔案

精靈在 `~/.nanobot/workspace/` 建立以下範本檔案，這些檔案會作為 agent 的系統提示（context）：

### AGENTS.md — Agent 行為指引

定義 agent 的核心行為、能力和限制。

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

**用途：** 自訂 agent 的回應風格、專長領域、限制條件等。

### USER.md — 用戶個人資料

描述用戶的背景、偏好和常用資訊，讓 agent 提供更個人化的回應。

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

**用途：** 讓 agent 了解您的背景，避免重複解釋個人偏好。

### SOUL.md — Agent 個性定義

定義 agent 的個性特質和溝通風格。

```markdown
# Soul

You have a friendly, professional personality.
You are curious, helpful, and direct.
You communicate clearly and adapt your tone to the conversation.
```

**用途：** 調整 agent 的個性，讓互動更符合您的喜好。

### TOOLS.md — 工具使用偏好

說明 agent 應如何使用各種工具。

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

**用途：** 控制 agent 使用工具的方式和時機。

### HEARTBEAT.md — 定期任務設定

定義 gateway 每 30 分鐘自動執行的週期性任務。

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

!!! info "Heartbeat 運作方式"
    Gateway 每 30 分鐘讀取 `HEARTBEAT.md`，執行其中的任務，並將結果傳送至您最近活躍的聊天頻道。

    **注意：** Gateway 必須正在運行（`nanobot gateway`），且您至少傳送過一則訊息，讓 nanobot 知道要傳遞到哪個頻道。

---

## 自訂 Workspace

Workspace 檔案是純文字 Markdown，您可以直接編輯：

```bash
# 編輯 Agent 指引
vim ~/.nanobot/workspace/AGENTS.md

# 編輯個人資料
vim ~/.nanobot/workspace/USER.md

# 設定定期任務
vim ~/.nanobot/workspace/HEARTBEAT.md
```

### 常見自訂範例

**設定中文回應：**

在 `AGENTS.md` 加入：

```markdown
## Language
Always respond in Traditional Chinese (繁體中文) unless the user writes in another language.
```

**限制工具使用：**

在 `AGENTS.md` 加入：

```markdown
## Security
- Never execute shell commands without explicit user approval
- Do not access files outside the workspace directory
```

**設定專業領域：**

在 `AGENTS.md` 加入：

```markdown
## Expertise
You specialize in Python development and data analysis.
Prioritize clean, Pythonic code and provide explanations for complex algorithms.
```

**設定每日摘要：**

在 `HEARTBEAT.md` 加入：

```markdown
## Periodic Tasks

- [ ] Every morning at 9am: Check today's calendar events and send a summary
- [ ] Every evening at 6pm: Summarize today's news in Traditional Chinese
```

### Workspace 範本自動同步

!!! tip "範本更新"
    當 nanobot 更新後，範本內容可能有所調整。重新執行 `nanobot onboard` 可以在不覆蓋現有內容的情況下，補充新的範本欄位。

---

## 使用 `-c` 和 `-w` 旗標

所有 nanobot 指令都支援 `-c`（`--config`）和 `-w`（`--workspace`）旗標，讓您靈活切換不同實例：

### `-c` / `--config`：指定設定檔

```bash
# 使用指定的設定檔啟動 gateway
nanobot gateway --config ~/.nanobot-telegram/config.json

# 使用指定的設定檔進行 CLI 對話
nanobot agent --config ~/.nanobot-discord/config.json -m "Hello!"
```

### `-w` / `--workspace`：指定 workspace 目錄

```bash
# 使用測試用的 workspace
nanobot agent --workspace /tmp/nanobot-test

# 搭配自訂設定檔使用
nanobot agent --config ~/.nanobot-telegram/config.json \
              --workspace /tmp/nanobot-telegram-test
```

!!! note "旗標優先順序"
    `--workspace` 旗標會覆蓋設定檔中 `agents.defaults.workspace` 的值，僅對當次執行有效。

### 多實例初始化範例

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

## 完整的 Onboarding 流程回顧

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

## 下一步

- **快速開始**：[5 分鐘快速設定指南](quick-start.md)
- **連接聊天頻道**：[頻道設定指南](../channels/index.md)
- **設定 LLM 提供商**：[Providers 文件](../providers/index.md)
