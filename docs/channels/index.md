# 頻道總覽

**頻道（Channel）** 是 nanobot 與各聊天平台之間的橋梁。每個頻道負責連接一個特定的即時通訊平台，將使用者訊息轉入 nanobot 的訊息匯流排，再將 AI 的回應送回平台。

---

## 支援的頻道清單

nanobot 目前支援以下 12 個平台：

| 頻道 | 說明 | 連線方式 |
|------|------|----------|
| [Telegram](telegram.md) | 最推薦的入門平台，設定簡單、穩定 | Long Polling |
| [Discord](discord.md) | 社群伺服器與私訊，支援附件上傳 | Gateway WebSocket |
| [Slack](slack.md) | 企業即時通訊，支援 Thread 回覆 | Socket Mode |
| [Feishu / 飛書](feishu.md) | 飛書企業通訊，支援多模態輸入 | WebSocket 長連線 |
| [DingTalk / 釘釘](dingtalk.md) | 阿里巴巴企業通訊 | Stream Mode |
| [WeCom / 企業微信](wecom.md) | 騰訊企業通訊平台 | WebSocket 長連線 |
| [QQ](qq.md) | QQ 官方 Bot 平台，支援私聊與群組 | WebSocket |
| [Email](email.md) | IMAP 收信 + SMTP 回信，適合非同步場景 | IMAP Polling |
| [Matrix](matrix.md) | 去中心化通訊協定，支援 E2EE 加密 | Matrix Sync |
| [WhatsApp](whatsapp.md) | 透過 Node.js Bridge 連接 | WebSocket Bridge |
| [Mochat / Claw IM](mochat.md) | Claw IM 開放平台 | Socket.IO |

---

## 如何啟用多個頻道

在 `~/.nanobot/config.json` 的 `channels` 物件中，將多個頻道同時設為 `"enabled": true`，nanobot 啟動後即可同時監聽所有已啟用的頻道：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    },
    "discord": {
      "enabled": true,
      "token": "YOUR_DISCORD_BOT_TOKEN",
      "allowFrom": ["YOUR_DISCORD_USER_ID"]
    }
  }
}
```

啟動：

```bash
nanobot gateway
```

所有已啟用的頻道將在同一個 gateway 程序中同時運行。

---

## 頻道專屬設定與全域設定

**全域設定**位於 `channels` 物件的頂層，適用於所有頻道：

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `sendProgress` | `true` | 將 AI 處理中的串流進度訊息發送至頻道 |
| `sendToolHints` | `false` | 是否將工具呼叫提示（例如 `read_file("…")`）顯示給使用者 |

**頻道專屬設定**則放在各頻道的子物件中。以下是一個同時設定全域選項與頻道選項的範例：

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

---

## `sendProgress` 與 `sendToolHints`

### `sendProgress`（預設：`true`）

啟用時，nanobot 在生成回應期間會將中間文字逐步串流傳送到頻道。這讓使用者知道 AI 正在處理，不必等到完整回應才看到輸出。

```json
{
  "channels": {
    "sendProgress": true
  }
}
```

### `sendToolHints`（預設：`false`）

啟用時，當 nanobot 呼叫工具時（例如搜尋網頁、執行 Shell 指令），會先發送一條簡短的提示訊息，例如：

```
🔧 web_search("nanobot documentation")
```

這有助於使用者了解 AI 正在做什麼，但在安靜模式下建議關閉。

```json
{
  "channels": {
    "sendToolHints": true
  }
}
```

---

## `allowFrom` 存取控制

每個頻道都有 `allowFrom` 欄位，用來控制哪些使用者可以使用 bot：

| 設定 | 效果 |
|------|------|
| `[]`（空陣列）| 拒絕所有人（預設，未設定前無法使用） |
| `["USER_ID_1", "USER_ID_2"]` | 僅允許指定的使用者 |
| `["*"]` | 允許所有人（公開模式，請謹慎使用） |

!!! warning "安全提醒"
    若 `allowFrom` 為空陣列，所有訊息都會被拒絕。請務必在啟動前設定您的使用者 ID。

---

## 多實例部署

您可以為不同頻道建立獨立的設定檔，讓每個 bot 有自己的工作空間：

```bash
# 各頻道獨立 onboard
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace

# 各自啟動 gateway
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json
```

詳細設定請參考各頻道的專屬文件。
