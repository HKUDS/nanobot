# Slack

nanobot 透過 Slack **Socket Mode** 連線，無需公開 URL 或 Webhook。支援頻道 Thread 回覆、檔案上傳，以及表情符號回應（reaction）。

---

## 前置條件

- 一個 Slack 帳號
- 具有安裝 App 權限的 Slack Workspace

---

## 步驟一：建立 Slack App

1. 前往 [Slack API](https://api.slack.com/apps)
2. 點擊 **Create New App** → 選擇 **From scratch**
3. 輸入 App 名稱並選擇您的 Workspace
4. 點擊 **Create App**

---

## 步驟二：啟用 Socket Mode 並取得 App Token

1. 在左側選單點擊 **Socket Mode**
2. 將 Socket Mode **Toggle ON**
3. 點擊 **Generate an app-level token**
4. 輸入 Token 名稱（例如 `nanobot-socket`）
5. 點擊 **Add Scope** → 選擇 `connections:write`
6. 點擊 **Generate**，複製 **App-Level Token**（格式：`xapp-1-...`）

---

## 步驟三：設定 OAuth 權限與 Bot Token

1. 在左側選單點擊 **OAuth & Permissions**
2. 在 **Bot Token Scopes** 中新增以下 Scope：
   - `chat:write` — 發送訊息
   - `reactions:write` — 添加表情回應
   - `app_mentions:read` — 讀取 @提及
   - `files:write` — （選用）上傳檔案
3. 點擊頁面頂部的 **Install to Workspace** → 授權
4. 複製 **Bot User OAuth Token**（格式：`xoxb-...`）

---

## 步驟四：訂閱事件

1. 在左側選單點擊 **Event Subscriptions**
2. 將 **Enable Events** Toggle ON
3. 在 **Subscribe to bot events** 中新增：
   - `message.im` — 接收私訊
   - `message.channels` — 接收頻道訊息
   - `app_mention` — 接收 @提及
4. 點擊 **Save Changes**

---

## 步驟五：啟用 Messages Tab

1. 在左側選單點擊 **App Home**
2. 在 **Show Tabs** 區塊啟用 **Messages Tab**
3. 勾選 **Allow users to send Slash commands and messages from the messages tab**

---

## 步驟六：取得您的 Slack 使用者 ID

1. 在 Slack 中點擊您的個人資料
2. 點擊 **...** → **複製成員 ID**

格式類似：`U0123456789`

---

## 步驟七：設定 config.json

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-1-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "mode": "socket",
      "botToken": "xoxb-...",
      "appToken": "xapp-1-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention",
      "groupAllowFrom": [],
      "replyInThread": true,
      "reactEmoji": "eyes",
      "doneEmoji": "white_check_mark",
      "dm": {
        "enabled": true,
        "policy": "open",
        "allowFrom": []
      }
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `mode` | `"socket"` | 連線模式（目前僅支援 `"socket"`） |
| `botToken` | `""` | Bot User OAuth Token（`xoxb-...`） |
| `appToken` | `""` | App-Level Token（`xapp-...`） |
| `allowFrom` | `[]` | 允許互動的使用者 ID 列表 |
| `groupPolicy` | `"mention"` | 頻道訊息處理策略（見下方） |
| `groupAllowFrom` | `[]` | 當 `groupPolicy` 為 `"allowlist"` 時，允許的頻道 ID |
| `replyInThread` | `true` | 是否在 Thread 中回覆 |
| `reactEmoji` | `"eyes"` | 收到訊息時添加的 reaction |
| `doneEmoji` | `"white_check_mark"` | 回應完成時的 reaction |
| `dm.enabled` | `true` | 是否接受私訊 |
| `dm.policy` | `"open"` | 私訊策略 |

### `groupPolicy` 說明

| 值 | 行為 |
|----|------|
| `"mention"`（預設） | 僅在頻道中被 @提及時才回應 |
| `"open"` | 回應頻道中的所有訊息 |
| `"allowlist"` | 僅回應 `groupAllowFrom` 中指定頻道的訊息 |

---

## 步驟八：啟動

```bash
nanobot gateway
```

直接傳私訊給 Bot，或在頻道中 @提及 Bot，即可開始互動。

---

## Thread 支援

`replyInThread` 預設為 `true`，Bot 的回應會在原訊息的 Thread 中顯示，保持頻道整潔。

若要停用 Thread 回覆：

```json
{
  "channels": {
    "slack": {
      "replyInThread": false
    }
  }
}
```

!!! note "私訊不使用 Thread"
    私訊（DM）不會使用 Thread，即使 `replyInThread` 為 `true`。

---

## 禁用私訊

若只想讓 Bot 在頻道中使用，可以禁用私訊：

```json
{
  "channels": {
    "slack": {
      "dm": {
        "enabled": false
      }
    }
  }
}
```

---

## 常見問題

**Bot 沒有收到私訊？**

- 確認已在 App Home 中啟用 Messages Tab
- 確認已訂閱 `message.im` 事件

**Bot 在頻道中沒有回應？**

- 確認已訂閱 `message.channels` 和 `app_mention` 事件
- 若 `groupPolicy` 為 `"mention"`，需要 @提及 Bot

**`xapp` Token 是什麼？**

- 這是 App-Level Token，與 Bot Token（`xoxb`）不同
- 在 **Socket Mode** 設定頁面生成，用於建立 WebSocket 連線

**安裝後需要重新授權嗎？**

- 每次修改 Bot Scopes 後，需要重新點擊 **Install to Workspace** 重新授權
