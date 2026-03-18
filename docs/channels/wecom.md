# WeCom / 企業微信

nanobot 透過企業微信 AI Bot 的 **WebSocket 長連線**接收訊息，無需公開 IP 或 Webhook。支援文字、圖片、語音、檔案等多媒體訊息。

---

## 前置條件

- 企業微信管理員帳號
- 企業已開通 AI Bot 功能

> nanobot 使用社群 Python SDK [wecom-aibot-sdk-python](https://github.com/chengyongru/wecom_aibot_sdk)，這是官方 [@wecom/aibot-node-sdk](https://www.npmjs.com/package/@wecom/aibot-node-sdk) 的 Python 版本。

---

## 步驟一：安裝選用依賴套件

企業微信頻道需要額外安裝 SDK：

```bash
pip install nanobot-ai[wecom]
```

或若使用 `uv`：

```bash
uv pip install nanobot-ai[wecom]
```

---

## 步驟二：建立企業微信 AI Bot

1. 登入 [企業微信管理後台](https://work.weixin.qq.com/wework_admin/frame)
2. 前往 **應用管理** → **智慧機器人** → **建立機器人**
3. 選擇 **API 模式**，並選擇 **長連線**（WebSocket 連線方式）
4. 完成建立後，複製 **Bot ID** 和 **Secret**

!!! tip "長連線模式"
    選擇長連線（WebSocket）模式，nanobot 會主動連接企業微信伺服器，無需開放公網 IP。

---

## 步驟三：設定 config.json

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "botId": "your_bot_id",
      "secret": "your_bot_secret",
      "allowFrom": ["your_user_id"]
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "botId": "your_bot_id",
      "secret": "your_bot_secret",
      "allowFrom": ["your_user_id"],
      "welcomeMessage": ""
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `botId` | `""` | 企業微信 AI Bot 的 Bot ID |
| `secret` | `""` | 企業微信 AI Bot 的 Secret |
| `allowFrom` | `[]` | 允許互動的使用者 ID 列表 |
| `welcomeMessage` | `""` | 新使用者第一次互動時發送的歡迎訊息（留空則不發送） |

---

## 步驟四：啟動

```bash
nanobot gateway
```

---

## 取得您的使用者 ID

`allowFrom` 填入的是企業微信的使用者 ID（userid）。

**取得方法：**

1. 先將 `allowFrom` 設為 `["*"]` 暫時允許所有人
2. 啟動 nanobot 並傳訊息給 Bot
3. 查看 nanobot 日誌，其中會顯示您的使用者 ID
4. 更新 `allowFrom`

---

## 多媒體支援

企業微信頻道支援以下媒體類型：

| 訊息類型 | 處理方式 |
|----------|----------|
| 文字 | 直接傳遞給 AI |
| 圖片 | 下載後傳遞給視覺模型 |
| 語音 | 若設定 Groq，自動轉錄 |
| 檔案 | 下載後傳遞給 AI |
| 混合內容 | 解析所有組件 |

---

## 常見問題

**安裝 `nanobot-ai[wecom]` 後仍提示未安裝？**

- 確認安裝在正確的 Python 環境中
- 使用 `uv sync` 或 `pip install nanobot-ai[wecom]` 重新安裝

**Bot 無法連線？**

- 確認 Bot ID 和 Secret 正確
- 確認建立的是「長連線」模式的 API Bot
- 查看 nanobot 日誌中的錯誤訊息

**歡迎訊息如何設定？**

- 設定 `welcomeMessage` 為任意字串，Bot 在使用者第一次互動時會自動發送
- 留空則不發送歡迎訊息
