# Matrix / Element

nanobot 支援 Matrix 去中心化通訊協定，可在任何 Matrix homeserver（包括 matrix.org）上運行。支援端對端加密（E2EE）、媒體附件，以及靈活的群組存取控制。

---

## 前置條件

- 一個 Matrix 帳號（可在 [matrix.org](https://matrix.org) 免費建立，或使用自架的 homeserver）
- 能夠登入 Element 或其他 Matrix 客戶端

---

## 步驟一：安裝 Matrix 依賴套件

Matrix 頻道需要額外安裝依賴：

```bash
pip install nanobot-ai[matrix]
```

或若使用 `uv`：

```bash
uv pip install nanobot-ai[matrix]
```

---

## 步驟二：建立或選擇 Matrix 帳號

建議為 nanobot 建立專用帳號：

1. 前往 [app.element.io](https://app.element.io) → **建立帳號**
2. 選擇 homeserver（預設為 `matrix.org`，或輸入自架 homeserver 的 URL）
3. 建立帳號後確認可以正常登入

---

## 步驟三：取得存取憑證

您需要以下三項憑證：

- **userId**：格式如 `@nanobot:matrix.org`
- **accessToken**：登入用的存取 Token
- **deviceId**：（建議）裝置識別碼，用於跨重啟還原加密狀態

### 取得 Access Token 的方法

**方法一：透過 Element 客戶端**

1. 登入 Element
2. 點擊左上角個人頭像 → **設定（Settings）**
3. 前往 **Help & About** 標籤
4. 向下捲動，點擊 **Access Token** 旁的 **Click to reveal**

**方法二：透過 API**

```bash
curl -X POST "https://matrix.org/_matrix/client/v3/login" \
  -H "Content-Type: application/json" \
  -d '{"type":"m.login.password","user":"nanobot","password":"YOUR_PASSWORD"}'
```

回應中的 `access_token`、`device_id` 即為所需憑證。

---

## 步驟四：設定 config.json

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@nanobot:matrix.org",
      "accessToken": "syt_xxx",
      "deviceId": "NANOBOT01",
      "allowFrom": ["@your_user:matrix.org"]
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@nanobot:matrix.org",
      "accessToken": "syt_xxx",
      "deviceId": "NANOBOT01",
      "e2eeEnabled": true,
      "allowFrom": ["@your_user:matrix.org"],
      "groupPolicy": "open",
      "groupAllowFrom": [],
      "allowRoomMentions": false,
      "maxMediaBytes": 20971520,
      "syncStopGraceSeconds": 2
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `homeserver` | `"https://matrix.org"` | Matrix homeserver URL |
| `userId` | `""` | Bot 的 Matrix 使用者 ID（`@name:server`） |
| `accessToken` | `""` | 登入用的 Access Token |
| `deviceId` | `""` | 裝置 ID（建議設定以保持加密狀態） |
| `e2eeEnabled` | `true` | 是否啟用端對端加密（E2EE） |
| `allowFrom` | `[]` | 允許互動的使用者 Matrix ID 列表 |
| `groupPolicy` | `"open"` | 群組房間訊息處理策略（見下方） |
| `groupAllowFrom` | `[]` | 當 `groupPolicy` 為 `"allowlist"` 時，允許的房間 ID |
| `allowRoomMentions` | `false` | 是否回應 `@room` 提及 |
| `maxMediaBytes` | `20971520`（20MB） | 媒體附件最大位元組數，設 `0` 禁用媒體 |
| `syncStopGraceSeconds` | `2` | 停止時等待同步完成的秒數 |

### `groupPolicy` 說明

| 值 | 行為 |
|----|------|
| `"open"`（預設） | 回應群組房間中所有人的訊息 |
| `"mention"` | 僅在被 @提及時回應 |
| `"allowlist"` | 僅回應 `groupAllowFrom` 中指定房間的訊息 |

---

## 步驟五：啟動

```bash
nanobot gateway
```

---

## 端對端加密（E2EE）

Matrix 頻道預設啟用 E2EE。這意味著：

- Bot 與使用者之間的訊息受到加密保護
- 加密金鑰儲存在本地的 `matrix-store` 目錄中

!!! warning "保持裝置 ID 一致"
    請保持 `deviceId` 固定，且不要刪除 `matrix-store` 目錄。若這些改變，加密 session 狀態會遺失，Bot 可能無法解密新訊息。

若不需要 E2EE：

```json
{
  "channels": {
    "matrix": {
      "e2eeEnabled": false
    }
  }
}
```

---

## 媒體附件支援

Matrix 頻道支援接收和傳送媒體附件：

- **接收**：圖片、音訊、影片、檔案（包括加密媒體）
- **傳送**：AI 生成的檔案會上傳至 homeserver
- 可透過 `maxMediaBytes` 限制最大附件大小

---

## 常見問題

**Bot 在加密房間中看不到訊息？**

- 確認 `e2eeEnabled` 為 `true`
- 確認 `deviceId` 固定且 `matrix-store` 未被刪除
- 第一次啟動時需要驗證裝置身份

**Access Token 過期？**

- Matrix Access Token 通常長期有效，但若登出所有裝置會失效
- 重新登入並取得新的 Access Token 和 Device ID

**Bot 不回應群組房間訊息？**

- 預設 `groupPolicy` 為 `"open"`，應該會回應所有人
- 確認 Bot 帳號已被邀請並加入房間
- 查看日誌確認是否有權限問題

**自架 homeserver 如何設定？**

- 將 `homeserver` 改為您的伺服器 URL，例如 `"https://matrix.example.com"`
- 其餘設定相同
