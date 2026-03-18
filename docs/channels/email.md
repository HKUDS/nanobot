# Email

nanobot 可以擁有自己的電子郵件帳號。它透過 **IMAP** 輪詢收取未讀郵件，並透過 **SMTP** 自動回覆——就像一位個人郵件助理。

---

## 前置條件

- 一個專用的電子郵件帳號（建議為 bot 建立獨立帳號）
- IMAP 與 SMTP 存取憑證
- 支援 Gmail、Outlook 或任何標準 IMAP/SMTP 伺服器

---

## 安全閘門（Consent Gate）

!!! warning "必須設定 `consentGranted`"
    `consentGranted` 必須設為 `true` 才能啟用信箱存取。這是一個防止意外存取真實信箱的安全閘門。若設為 `false` 或未設定，即使 `enabled` 為 `true`，頻道也不會運作。

---

## 步驟一：準備電子郵件帳號

### Gmail 設定

1. 建立一個專用 Gmail 帳號（例如 `my-nanobot@gmail.com`）
2. 前往 Google 帳號設定 → **安全性** → 啟用兩步驟驗證
3. 前往 [App Passwords](https://myaccount.google.com/apppasswords) → 建立新的 App Password
4. 記錄生成的 16 位元密碼（用於 IMAP 和 SMTP 密碼欄位）

!!! tip "使用 App Password"
    使用 App Password 而非 Google 帳號密碼，更安全且不受兩步驗證影響。

### Outlook / Hotmail 設定

使用 IMAP 伺服器 `outlook.office365.com`（Port 993）和 SMTP 伺服器 `smtp-mail.outlook.com`（Port 587）。

### 自訂 SMTP/IMAP 伺服器

填入您郵件提供商提供的 IMAP 和 SMTP 伺服器位址與連接埠。

---

## 步驟二：設定 config.json

### Gmail 範例

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-nanobot@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-nanobot@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-nanobot@gmail.com",
      "allowFrom": ["your-real-email@gmail.com"]
    }
  }
}
```

### Outlook 範例

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "outlook.office365.com",
      "imapPort": 993,
      "imapUsername": "my-nanobot@outlook.com",
      "imapPassword": "YOUR_PASSWORD",
      "smtpHost": "smtp-mail.outlook.com",
      "smtpPort": 587,
      "smtpUsername": "my-nanobot@outlook.com",
      "smtpPassword": "YOUR_PASSWORD",
      "fromAddress": "my-nanobot@outlook.com",
      "allowFrom": ["your-real-email@example.com"]
    }
  }
}
```

### 完整設定選項

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-nanobot@gmail.com",
      "imapPassword": "your-app-password",
      "imapMailbox": "INBOX",
      "imapUseSsl": true,
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-nanobot@gmail.com",
      "smtpPassword": "your-app-password",
      "smtpUseTls": true,
      "smtpUseSsl": false,
      "fromAddress": "my-nanobot@gmail.com",
      "autoReplyEnabled": true,
      "pollIntervalSeconds": 30,
      "markSeen": true,
      "maxBodyChars": 12000,
      "subjectPrefix": "Re: ",
      "allowFrom": ["your-real-email@gmail.com"]
    }
  }
}
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | `false` | 是否啟用此頻道 |
| `consentGranted` | `false` | **必須設為 `true`** 才能存取信箱 |
| `imapHost` | `""` | IMAP 伺服器位址 |
| `imapPort` | `993` | IMAP 連接埠（SSL 通常為 993） |
| `imapUsername` | `""` | IMAP 登入帳號 |
| `imapPassword` | `""` | IMAP 登入密碼 |
| `imapMailbox` | `"INBOX"` | 監聽的信箱資料夾 |
| `imapUseSsl` | `true` | 是否使用 SSL/TLS 連線 IMAP |
| `smtpHost` | `""` | SMTP 伺服器位址 |
| `smtpPort` | `587` | SMTP 連接埠（STARTTLS 通常為 587） |
| `smtpUsername` | `""` | SMTP 登入帳號 |
| `smtpPassword` | `""` | SMTP 登入密碼 |
| `smtpUseTls` | `true` | 是否使用 STARTTLS（Gmail 587 Port 需要） |
| `smtpUseSsl` | `false` | 是否使用 SSL（Port 465 時設為 `true`） |
| `fromAddress` | `""` | 發件人地址（顯示在回覆郵件中） |
| `autoReplyEnabled` | `true` | 是否自動回覆（設為 `false` 只收不回） |
| `pollIntervalSeconds` | `30` | 輪詢 IMAP 的間隔秒數 |
| `markSeen` | `true` | 讀取後是否標記為已讀 |
| `maxBodyChars` | `12000` | 郵件正文最大字元數 |
| `subjectPrefix` | `"Re: "` | 回覆郵件的主旨前綴 |
| `allowFrom` | `[]` | 允許互動的發件人地址列表 |

---

## 步驟三：啟動

```bash
nanobot gateway
```

nanobot 會每隔 `pollIntervalSeconds` 秒檢查一次信箱，自動處理新郵件並回覆。

---

## 僅閱讀模式（不自動回覆）

若只想讓 nanobot 分析郵件，不自動發送回覆：

```json
{
  "channels": {
    "email": {
      "autoReplyEnabled": false
    }
  }
}
```

---

## 開放所有來信

若要接受任意寄件人的郵件（公開 bot）：

```json
{
  "channels": {
    "email": {
      "allowFrom": ["*"]
    }
  }
}
```

!!! warning "垃圾郵件風險"
    將 `allowFrom` 設為 `["*"]` 會讓 bot 處理所有收到的郵件，包括垃圾郵件。建議僅在受控環境中使用。

---

## 常見問題

**Gmail 顯示「登入被封鎖」？**

- 確認使用的是 App Password，而非 Google 帳號原始密碼
- 確認已啟用兩步驟驗證

**SMTP 連線失敗？**

- Gmail（Port 587）：`smtpUseTls: true`，`smtpUseSsl: false`
- Gmail（Port 465）：`smtpUseTls: false`，`smtpUseSsl: true`
- 確認 `fromAddress` 與 `smtpUsername` 相符

**Bot 沒有回應郵件？**

- 確認 `consentGranted` 設為 `true`
- 確認寄件人地址在 `allowFrom` 中
- 查看日誌確認 IMAP 輪詢是否正常運作
