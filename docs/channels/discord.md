# Discord

nanobot 透過 Discord Gateway WebSocket 連線，無需公開 IP 或 Webhook。支援 Thread 回覆、檔案附件上傳，以及群組中的 @提及控制。

---

## 前置條件

- 一個 Discord 帳號
- 擁有一個 Discord 伺服器（用於測試）

---

## 步驟一：建立 Discord 應用程式與 Bot

1. 前往 [Discord Developer Portal](https://discord.com/developers/applications)
2. 點擊右上角 **New Application**，輸入名稱後建立
3. 在左側選單點擊 **Bot**
4. 點擊 **Add Bot**（或 **Reset Token**）→ 確認
5. 點擊 **Copy** 複製 **Bot Token**

!!! warning "Token 安全性"
    Bot Token 等同於密碼，切勿提交至版本控制或分享給他人。若外洩請立即在此頁面重新生成。

---

## 步驟二：啟用 Message Content Intent

在 Bot 設定頁面向下捲動至 **Privileged Gateway Intents**：

- 勾選 **MESSAGE CONTENT INTENT** ← **必須啟用，否則 bot 無法讀取訊息內容**
- （選用）勾選 **SERVER MEMBERS INTENT**，若需要根據伺服器成員資料過濾存取

點擊 **Save Changes**。

---

## 步驟三：取得您的使用者 ID

1. 前往 Discord 設定 → **進階（Advanced）**
2. 啟用 **開發者模式（Developer Mode）**
3. 右鍵點擊您的頭像 → **複製使用者 ID**

取得的數字 ID 格式類似：`123456789012345678`

---

## 步驟四：將 Bot 邀請到伺服器

1. 在 Developer Portal 左側選單點擊 **OAuth2** → **URL Generator**
2. **Scopes** 勾選：`bot`
3. **Bot Permissions** 勾選：
   - `Send Messages`
   - `Read Message History`
   - （選用）`Attach Files`，若需要 bot 傳送檔案
4. 複製生成的 URL，在瀏覽器中開啟，選擇您的伺服器並授權

---

## 步驟五：設定 config.json

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "gatewayUrl": "wss://gateway.discord.gg/?v=10&encoding=json",
      "intents": 37377,
      "groupPolicy": "mention"
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `token` | `""` | Discord Bot Token |
| `allowFrom` | `[]` | 允許互動的使用者數字 ID 列表 |
| `gatewayUrl` | Discord 預設 | Gateway WebSocket URL（通常不需修改） |
| `intents` | `37377` | Gateway Intents 位元遮罩（通常不需修改） |
| `groupPolicy` | `"mention"` | 群組頻道訊息處理策略（見下方說明） |

### `groupPolicy` 說明

| 值 | 行為 |
|----|------|
| `"mention"`（預設） | 僅在頻道中被 @提及時才回應 |
| `"open"` | 回應頻道中的所有訊息 |

私訊（DM）永遠回應，不受 `groupPolicy` 影響。

---

## 步驟六：啟動

```bash
nanobot gateway
```

---

## Thread 支援

nanobot 在 Discord 頻道中回應訊息時，會在同一個訊息串（Thread）內繼續對話。每個使用者的對話上下文是獨立維護的。

---

## 檔案附件支援

nanobot 可以接收並傳送 Discord 附件：

- **接收**：圖片、檔案等附件會被下載並傳遞給 AI 進行處理
- **傳送**：AI 產生的檔案（如程式碼、圖片）會作為附件上傳
- 單個附件上限為 **20MB**（Discord 免費帳號限制）

---

## 常見問題

**Bot 在頻道中看不到訊息？**

- 確認已啟用 **MESSAGE CONTENT INTENT**，這是最常見的問題
- 沒有此 Intent，bot 會收到事件但無法讀取訊息內容

**Bot 被邀請到伺服器但不回應？**

- 確認 `allowFrom` 中已包含您的使用者 ID
- 若 `groupPolicy` 為 `"mention"`，需要在訊息中 @bot

**Bot Token 錯誤？**

- 確認 Token 是 Bot Token，而非 OAuth Client Secret
- Bot Token 通常以 `MT`、`NT` 等開頭，長度約 70 個字元

**Rate Limit 警告？**

- Discord 有 API 速率限制，nanobot 會自動重試
- 若頻繁出現此警告，考慮減少並發請求
