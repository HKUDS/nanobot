# Feishu / 飛書

nanobot 透過飛書 **WebSocket 長連線**接收事件，無需公開 IP 或 Webhook。支援多模態輸入（圖片、檔案）、群組 @提及控制，以及引用回覆。

---

## 前置條件

- 一個飛書帳號
- 具有建立應用程式權限的飛書企業或團隊

---

## 步驟一：建立飛書應用程式

1. 前往 [飛書開放平台](https://open.feishu.cn/app)
2. 點擊 **建立企業自建應用**，輸入名稱與描述
3. 進入應用程式設定後，在左側選單找到 **功能** → **機器人**，啟用機器人能力

---

## 步驟二：設定權限

在左側選單前往 **開發設定** → **權限管理**，搜尋並新增以下權限：

- `im:message` — 獲取與發送單聊、群組中的消息
- `im:message.p2p_msg:readonly` — 接收私聊消息
- （選用）`im:message.group_at_msg:readonly` — 接收群組中 @機器人的消息

---

## 步驟三：訂閱事件並選擇長連線模式

1. 在左側選單前往 **開發設定** → **事件訂閱**
2. 新增事件：`im.message.receive_v1`（接收消息）
3. **連線方式選擇「使用長連線接收事件」**（Long Connection）

!!! tip "無需公開 IP"
    長連線模式由 nanobot 主動發起連線至飛書伺服器，不需要 Webhook URL 或公開 IP。

---

## 步驟四：取得 App ID 與 App Secret

1. 在左側選單前往 **憑證與基礎資訊**
2. 複製 **App ID**（格式：`cli_xxx`）
3. 複製 **App Secret**

---

## 步驟五：發佈應用程式

前往 **版本管理與發佈** → 建立版本 → 申請發佈（若為企業應用需管理員審核）。

!!! note "開發測試"
    開發測試階段可以先不發佈，直接在「線上測試」中測試功能。

---

## 步驟六：設定 config.json

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "YOUR_APP_SECRET",
      "allowFrom": ["ou_YOUR_OPEN_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "YOUR_APP_SECRET",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": ["ou_YOUR_OPEN_ID"],
      "reactEmoji": "THUMBSUP",
      "groupPolicy": "mention",
      "replyToMessage": false
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `appId` | `""` | 飛書應用程式 App ID |
| `appSecret` | `""` | 飛書應用程式 App Secret |
| `encryptKey` | `""` | 消息加密金鑰（長連線模式下可留空） |
| `verificationToken` | `""` | 事件驗證 Token（長連線模式下可留空） |
| `allowFrom` | `[]` | 允許互動的使用者 Open ID 列表 |
| `reactEmoji` | `"THUMBSUP"` | 收到訊息時添加的 emoji reaction |
| `groupPolicy` | `"mention"` | 群組訊息處理策略（見下方） |
| `replyToMessage` | `false` | Bot 回應時是否引用使用者原始訊息 |

### `groupPolicy` 說明

| 值 | 行為 |
|----|------|
| `"mention"`（預設） | 僅在群組中被 @提及時才回應 |
| `"open"` | 回應群組中的所有訊息 |

私聊永遠回應，不受 `groupPolicy` 影響。

---

## 步驟七：啟動

```bash
nanobot gateway
```

---

## 取得您的 Open ID

`allowFrom` 需填入飛書使用者的 Open ID（格式：`ou_xxxxxxxx`）。

**取得方法：**

1. 先將 `allowFrom` 設為 `["*"]` 暫時允許所有人
2. 啟動 nanobot 並傳訊息給 Bot
3. 查看 nanobot 日誌，其中會顯示您的 Open ID
4. 將 `allowFrom` 改回 `["ou_xxxxxxxx"]`

---

## 多模態支援

飛書頻道支援接收以下媒體類型：

- **圖片**：直接傳給 AI 處理（支援視覺模型）
- **語音**：若已設定 Groq API Key，自動轉錄為文字
- **檔案**：下載後傳遞給 AI
- **貼圖**：顯示為 `[sticker]`

---

## 常見問題

**Bot 無法接收訊息？**

- 確認應用程式已發佈，且機器人能力已啟用
- 確認已訂閱 `im.message.receive_v1` 事件
- 確認選擇了「長連線」接收方式

**群組中 Bot 沒有回應？**

- 若 `groupPolicy` 為 `"mention"`，需要 @Bot 才會回應
- 確認 Bot 已被邀請進入群組

**`encryptKey` 需要設定嗎？**

- 使用長連線模式時，`encryptKey` 和 `verificationToken` 可留空
- 只有使用 HTTP 回調模式時才需要設定
