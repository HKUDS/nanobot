# WhatsApp

nanobot 透過 Node.js Bridge 連接 WhatsApp Web 協定，使用 [@whiskeysockets/baileys](https://github.com/WhiskeySockets/Baileys) 函式庫。Bridge 與 nanobot Python 程序之間透過 WebSocket 通訊。

---

## 前置條件

- **Node.js ≥ 18**（必須）
- 一個 WhatsApp 帳號（手機需在線）

---

## 步驟一：確認 Node.js 版本

```bash
node --version
# 應顯示 v18.0.0 或更高版本
```

若未安裝，請前往 [nodejs.org](https://nodejs.org) 下載安裝。

---

## 步驟二：連結裝置（掃描 QR Code）

```bash
nanobot channels login
```

執行後會顯示 QR Code。在手機 WhatsApp 中：

1. 前往 **設定（Settings）** → **已連結裝置（Linked Devices）**
2. 點擊 **連結裝置（Link a Device）**
3. 掃描終端機中顯示的 QR Code

連結成功後，Bridge 會儲存 session 資訊，之後重啟不需要重新掃描。

!!! tip "首次使用"
    `nanobot channels login` 指令會自動下載並建置 Node.js Bridge（儲存於 `~/.nanobot/bridge/`），首次執行需要一些時間。

---

## 步驟三：設定 config.json

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+886912345678"]
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "bridgeToken": "",
      "allowFrom": ["+886912345678"]
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `bridgeUrl` | `"ws://localhost:3001"` | Node.js Bridge 的 WebSocket URL |
| `bridgeToken` | `""` | Bridge 認證 Token（選用，預設不需要） |
| `allowFrom` | `[]` | 允許互動的 WhatsApp 號碼列表（含國碼，如 `+886912345678`） |

---

## 步驟四：啟動

需要開啟兩個終端機視窗：

```bash
# 終端機 1：啟動 WhatsApp Bridge
nanobot channels login

# 終端機 2：啟動 nanobot gateway
nanobot gateway
```

!!! note "執行順序"
    建議先啟動 Bridge（`channels login`），再啟動 gateway。Bridge 會在背景持續運行以維持 WhatsApp 連線。

---

## Bridge 架構說明

```
WhatsApp App（手機）
    ↕ WhatsApp Web 協定
Node.js Bridge（~/.nanobot/bridge/）
    ↕ WebSocket（ws://localhost:3001）
nanobot Python（gateway）
    ↕ 訊息匯流排
AI Agent
```

Bridge 負責處理 WhatsApp 的低階協定，nanobot 只需透過簡單的 WebSocket 訊息格式與 Bridge 通訊。

---

## 更新 Bridge

升級 nanobot 後，若 Bridge 也有更新，需要重新建置：

```bash
rm -rf ~/.nanobot/bridge && nanobot channels login
```

!!! warning "手動重建"
    Bridge 更新不會自動套用到現有安裝。升級 nanobot 後請手動執行上述指令重建 Bridge。

---

## 常見問題

**掃描 QR Code 後立即失效？**

- WhatsApp QR Code 有時效性，請盡快掃描
- 若失敗，重新執行 `nanobot channels login` 取得新 QR Code

**重啟後需要重新掃描？**

- 正常情況下不需要，session 資訊儲存於 `~/.nanobot/bridge/`
- 若需要重置，刪除該目錄後重新執行 `nanobot channels login`

**連線中斷後無法自動重連？**

- nanobot 會自動重試連線
- 若長時間中斷，手機 WhatsApp 可能已取消裝置連結，需重新掃描

**`allowFrom` 格式？**

- 填入完整國際格式電話號碼，包含 `+` 和國碼
- 例如台灣手機：`"+886912345678"`
- 或使用 `["*"]` 允許所有聯絡人
