# DingTalk / 釘釘

nanobot 透過釘釘 **Stream Mode** 連線接收訊息，無需公開 IP 或 Webhook。支援私聊與群聊、圖片、檔案等多媒體訊息。

---

## 前置條件

- 一個釘釘帳號
- 具有建立應用程式權限的釘釘企業帳號

---

## 步驟一：建立釘釘應用程式

1. 前往 [釘釘開放平台](https://open-dev.dingtalk.com/)
2. 登入後前往 **應用開發** → **企業內部應用**
3. 點擊 **建立應用**，選擇 **釘釘應用**
4. 填寫應用名稱與描述後建立

---

## 步驟二：添加機器人能力

1. 進入應用設定後，前往 **添加應用能力** → **機器人**
2. 點擊 **確認添加**
3. 在機器人設定中：
   - **Stream Mode**：確認已選擇 **Stream 模式**（即 WebSocket 接收，無需 Webhook URL）
   - 填寫機器人名稱與描述

---

## 步驟三：設定權限

前往 **權限管理**，根據需要申請以下權限：

- `qyapi_chat_group` — 群組訊息相關（若需要群聊）
- 發送互動卡片相關權限（若需要富媒體回覆）

---

## 步驟四：取得 Client ID 與 Client Secret

1. 前往 **應用憑證** 頁面
2. 複製 **AppKey**（即 Client ID）
3. 複製 **AppSecret**（即 Client Secret）

---

## 步驟五：發佈應用程式

前往 **版本管理** → 建立版本 → 提交審核或直接發佈（企業內部應用通常可直接發佈）。

---

## 步驟六：設定 config.json

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `clientId` | `""` | 釘釘應用的 AppKey（Client ID） |
| `clientSecret` | `""` | 釘釘應用的 AppSecret（Client Secret） |
| `allowFrom` | `[]` | 允許互動的員工 Staff ID 列表 |

---

## 步驟七：啟動

```bash
nanobot gateway
```

---

## 取得您的 Staff ID

`allowFrom` 填入的是釘釘的員工 Staff ID（staffId），格式類似 `user_abc123`。

**取得方法：**

1. 先將 `allowFrom` 設為 `["*"]` 暫時允許所有人
2. 啟動 nanobot 並傳訊息給 Bot
3. 查看 nanobot 日誌，其中會顯示您的 Staff ID
4. 更新 `allowFrom`

---

## 多媒體支援

釘釘頻道支援以下媒體類型：

- **圖片**：自動下載並傳遞給 AI 處理
- **檔案**：自動下載後處理
- **富文本（RichText）**：解析文字與圖片內容

---

## 常見問題

**Stream Mode 是什麼？**

- Stream Mode 使用 WebSocket 連線，由 nanobot 主動連接至釘釘伺服器
- 相對於 HTTP 回調模式，無需公開 IP 或反向代理

**Bot 無法接收訊息？**

- 確認選擇的是 **Stream 模式**，而非 HTTP 回調
- 確認應用已發佈

**群組中 Bot 沒有回應？**

- 釘釘群組中需要 @機器人才會回應
- 確認機器人已被邀請加入群組
