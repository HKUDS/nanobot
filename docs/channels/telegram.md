# Telegram

Telegram 是最推薦的 nanobot 入門頻道。設定流程簡單、連線穩定，不需要公開 IP 或 Webhook。

---

## 前置條件

- 一個 Telegram 帳號
- 可使用 `@BotFather` 建立 Bot

---

## 步驟一：建立 Bot

1. 在 Telegram 中搜尋並開啟 **`@BotFather`**
2. 發送指令 `/newbot`
3. 依提示輸入 Bot 名稱（顯示名稱，例如 `My Nanobot`）
4. 輸入 Bot 使用者名稱（必須以 `bot` 結尾，例如 `my_nanobot_bot`）
5. BotFather 將回傳一串 **Bot Token**，格式如下：

```
123456789:ABCdefGhIJKlmNoPQRstuVWXyz
```

請妥善保存此 Token。

---

## 步驟二：取得您的使用者 ID

您需要將自己的 Telegram 使用者 ID 加入 `allowFrom` 白名單，才能與 bot 互動。

**方法：**

1. 在 Telegram 設定 → 個人資料中查看您的使用者名稱（`@yourUsername`）
2. 或者直接傳訊息給 Bot，nanobot 日誌中會顯示您的數字 ID

!!! tip "使用者名稱 vs 數字 ID"
    `allowFrom` 可填入數字 ID（例如 `"123456789"`）或使用者名稱（例如 `"yourUsername"`，不含 `@`），兩者皆可。

---

## 步驟三：設定 config.json

編輯 `~/.nanobot/config.json`，加入以下設定：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456789:ABCdefGhIJKlmNoPQRstuVWXyz",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "proxy": null,
      "replyToMessage": false,
      "groupPolicy": "mention"
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `token` | `""` | BotFather 提供的 Bot Token |
| `allowFrom` | `[]` | 允許互動的使用者 ID 或使用者名稱列表 |
| `proxy` | `null` | HTTP/SOCKS 代理（例如 `"http://127.0.0.1:1080"`） |
| `replyToMessage` | `false` | Bot 回應時是否引用使用者的原始訊息 |
| `groupPolicy` | `"mention"` | 群組訊息處理策略（見下方說明） |

### `groupPolicy` 說明

| 值 | 行為 |
|----|------|
| `"mention"`（預設） | 僅在群組中被 @提及時才回應 |
| `"open"` | 回應群組中的所有訊息 |

私訊（DM）永遠回應，不受 `groupPolicy` 影響。

---

## 步驟四：啟動

```bash
nanobot gateway
```

啟動後，在 Telegram 中向您的 bot 發送 `/start` 或任意訊息即可開始互動。

---

## 可用指令

Bot 預設會在 Telegram 指令選單中顯示以下指令：

| 指令 | 說明 |
|------|------|
| `/start` | 啟動 bot |
| `/new` | 開始新對話（清除上下文） |
| `/stop` | 停止目前任務 |
| `/help` | 顯示可用指令 |
| `/restart` | 重啟 bot |

---

## 語音訊息轉錄

若您設定了 Groq API Key，Telegram 的語音訊息將自動透過 Whisper 轉錄為文字：

```json
{
  "providers": {
    "groq": {
      "apiKey": "YOUR_GROQ_API_KEY"
    }
  }
}
```

!!! tip "免費語音轉錄"
    Groq 提供免費的 Whisper 語音轉錄配額，非常適合個人使用。

---

## 使用代理

在中國大陸或 Telegram 受限的地區，可透過代理連線：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

支援 `http://`、`https://`、`socks5://` 格式。

---

## 常見問題

**Bot 沒有回應訊息？**

- 確認 `allowFrom` 中已包含您的使用者 ID
- 空的 `allowFrom` 會拒絕所有人
- 查看 nanobot 日誌確認是否有「Access denied」錯誤

**Token 無效錯誤？**

- 確認 Token 從 BotFather 複製正確，中間沒有空格
- 若 Token 外洩，可在 BotFather 中使用 `/revoke` 重新生成

**群組中 bot 沒有回應？**

- 若 `groupPolicy` 為 `"mention"`，需要在訊息中 @bot 才會回應
- 確認 bot 已被加入群組，並有發言權限

**在群組中收到訊息但不回應陌生人？**

- 群組成員也需要在 `allowFrom` 中，或將 `allowFrom` 設為 `["*"]` 允許所有人
