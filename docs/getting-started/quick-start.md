# 快速開始

在 5 分鐘內完成 nanobot 設定，並與您的 AI 助手進行第一次對話。

---

## 步驟一：安裝 nanobot

=== "uv（推薦）"

    ```bash
    uv tool install nanobot-ai
    ```

=== "pip"

    ```bash
    pip install nanobot-ai
    ```

確認安裝成功：

```bash
nanobot --version
```

!!! tip "尚未安裝 uv？"
    請先參閱 [安裝指南](installation.md) 安裝 uv 和 nanobot。

---

## 步驟二：執行 Onboarding 精靈

```bash
nanobot onboard
```

精靈會引導您完成初始設定，並在 `~/.nanobot/` 建立以下檔案：

```
~/.nanobot/
├── config.json          # 主設定檔
└── workspace/
    ├── AGENTS.md        # Agent 行為指引
    ├── USER.md          # 用戶個人資料
    ├── SOUL.md          # Agent 個性定義
    ├── TOOLS.md         # 工具使用偏好
    └── HEARTBEAT.md     # 定期任務設定
```

!!! note "已有設定？"
    重複執行 `nanobot onboard` 不會覆蓋現有設定，只會補充缺少的部分。

---

## 步驟三：設定 API 金鑰與模型

開啟 `~/.nanobot/config.json`，加入您的 LLM API 金鑰與模型設定。

```bash
# 使用任意編輯器開啟
vim ~/.nanobot/config.json
# 或
nano ~/.nanobot/config.json
# 或
code ~/.nanobot/config.json
```

### 設定 API 金鑰

以 [OpenRouter](https://openrouter.ai/keys)（全球用戶推薦）為例：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  }
}
```

其他常用提供商：

=== "Anthropic（Claude）"

    ```json
    {
      "providers": {
        "anthropic": {
          "apiKey": "sk-ant-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "OpenAI（GPT）"

    ```json
    {
      "providers": {
        "openai": {
          "apiKey": "sk-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "DeepSeek"

    ```json
    {
      "providers": {
        "deepseek": {
          "apiKey": "sk-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "Ollama（本地）"

    ```json
    {
      "providers": {
        "ollama": {
          "apiBase": "http://localhost:11434"
        }
      },
      "agents": {
        "defaults": {
          "provider": "ollama",
          "model": "llama3.2"
        }
      }
    }
    ```

### 設定模型（選用）

可選擇性地指定預設模型。若不設定，nanobot 會根據已設定的 API 金鑰自動偵測：

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5",
      "provider": "openrouter"
    }
  }
}
```

### 完整的最簡設定範例

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

!!! warning "保護您的 API 金鑰"
    `config.json` 包含敏感的 API 金鑰，請勿將此檔案提交至版本控制系統（git）。

---

## 步驟四：在 CLI 上對話

設定完成後，立即開始對話：

```bash
nanobot agent
```

您會看到互動式對話介面：

```
nanobot> 你好！你能幫我做什麼？
```

nanobot 支援多種使用方式：

```bash
# 互動式對話（預設）
nanobot agent

# 單次訊息（非互動）
nanobot agent -m "今天天氣如何？"

# 顯示純文字回應（不渲染 Markdown）
nanobot agent --no-markdown

# 顯示執行日誌
nanobot agent --logs
```

退出互動模式：輸入 `exit`、`quit` 或按 `Ctrl+D`。

!!! tip "恭喜！"
    您已成功完成基本設定。以下步驟說明如何將 nanobot 連接至 Telegram，讓您隨時隨地透過手機與 AI 助手對話。

---

## 步驟五：連接 Telegram（選用）

Telegram 是最容易設定的聊天平台，推薦新手使用。

### 建立 Telegram Bot

1. 開啟 Telegram，搜尋 **@BotFather**
2. 傳送 `/newbot`
3. 依提示輸入 Bot 名稱（顯示名稱，例如 `My Nanobot`）
4. 輸入 Bot 用戶名（必須以 `bot` 結尾，例如 `my_nanobot_bot`）
5. BotFather 會回覆一組 **Bot Token**，格式類似：`1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`

### 取得您的 Telegram User ID

您的 User ID 顯示在 Telegram 設定中，格式為 `@yourUserId`。
複製時請**去掉 `@` 符號**。

或者，傳送任何訊息給您的 bot，然後查看 nanobot 的執行日誌，其中會顯示發送者的 User ID。

### 更新設定檔

將以下內容合併至 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
      "allowFrom": ["your_telegram_user_id"]
    }
  }
}
```

| 欄位 | 說明 |
|------|------|
| `token` | 從 @BotFather 取得的 Bot Token |
| `allowFrom` | 允許與 bot 互動的 User ID 清單（留空則拒絕所有人） |

!!! warning "安全提醒"
    `allowFrom` 清單用於控制誰可以使用您的 bot。
    使用 `["*"]` 可允許所有人，但請謹慎使用，避免濫用 API 額度。

---

## 步驟六：啟動 Gateway

```bash
nanobot gateway
```

Gateway 啟動後，您會看到類似以下的輸出：

```
[nanobot] Gateway starting on port 18790
[nanobot] Telegram channel connected
[nanobot] Ready to receive messages
```

現在，開啟 Telegram 並傳送訊息給您的 bot！

!!! note "Gateway 與 CLI 的差別"
    - `nanobot agent`：本機 CLI 互動模式，直接在終端機對話
    - `nanobot gateway`：啟動伺服器，持續監聽來自聊天平台的訊息

---

## 完整設定範例

以下是包含 Telegram 頻道的完整最簡設定：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    }
  }
}
```

---

## 下一步

- **了解 Onboarding 精靈**：[Onboarding 精靈詳細說明](onboarding.md)
- **連接其他聊天平台**：[頻道設定指南](../channels/index.md)
- **設定更多 LLM 提供商**：[Providers 文件](../providers/index.md)
- **探索工具與技能**：[工具與技能](../tools-skills/index.md)
