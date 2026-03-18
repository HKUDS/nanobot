# Email

nanobot は専用のメールアカウントを持てます。未読メールを **IMAP** でポーリング受信し、**SMTP** で自動返信します。個人用のメールアシスタントのように動作します。

---

## 前提条件

- 専用のメールアカウント（bot 用に独立アカウントを作るのがおすすめ）
- IMAP と SMTP の接続情報
- Gmail、Outlook、または標準 IMAP/SMTP を提供する任意サーバー

---

## 安全ゲート（Consent Gate）

!!! warning "`consentGranted` は必須です"
    `consentGranted` を `true` にしない限り、メールボックスアクセスは有効になりません。実メールボックスを誤って読み取ることを防ぐための安全ゲートです。`false` または未設定の場合、`enabled` が `true` でもこのチャンネルは動作しません。

---

## ステップ 1: メールアカウントを準備する

### Gmail 設定

1. bot 専用の Gmail アカウント（例: `my-nanobot@gmail.com`）を作成する
2. Google アカウント設定 → **セキュリティ** → 2 段階認証を有効化する
3. [App Passwords](https://myaccount.google.com/apppasswords) で新しい App Password を作成する
4. 生成された 16 桁パスワードを控える（IMAP/SMTP のパスワード欄に使用）

!!! tip "App Password を使う"
    Google アカウント本体のパスワードではなく App Password を使うほうが安全で、2 段階認証の影響も受けません。

### Outlook / Hotmail 設定

IMAP は `outlook.office365.com`（Port 993）、SMTP は `smtp-mail.outlook.com`（Port 587）を使用します。

### 独自 SMTP/IMAP サーバー

メール提供元が案内する IMAP/SMTP サーバーのホスト名とポートを設定してください。

---

## ステップ 2: config.json を設定する

### Gmail 例

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

### Outlook 例

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

### 完全な設定オプション

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

| パラメータ | デフォルト | 説明 |
|------|--------|------|
| `enabled` | `false` | このチャンネルを有効にするか |
| `consentGranted` | `false` | **`true` にする必要があります**（メールボックスアクセス許可） |
| `imapHost` | `""` | IMAP サーバーのホスト |
| `imapPort` | `993` | IMAP ポート（SSL は通常 993） |
| `imapUsername` | `""` | IMAP ログインユーザー名 |
| `imapPassword` | `""` | IMAP ログインパスワード |
| `imapMailbox` | `"INBOX"` | 監視するメールボックスフォルダ |
| `imapUseSsl` | `true` | IMAP に SSL/TLS を使うか |
| `smtpHost` | `""` | SMTP サーバーのホスト |
| `smtpPort` | `587` | SMTP ポート（STARTTLS は通常 587） |
| `smtpUsername` | `""` | SMTP ログインユーザー名 |
| `smtpPassword` | `""` | SMTP ログインパスワード |
| `smtpUseTls` | `true` | STARTTLS を使うか（Gmail 587 で必要） |
| `smtpUseSsl` | `false` | SSL を使うか（Port 465 の場合は `true`） |
| `fromAddress` | `""` | 送信元アドレス（返信メールに表示） |
| `autoReplyEnabled` | `true` | 自動返信するか（`false` で受信のみ） |
| `pollIntervalSeconds` | `30` | IMAP ポーリング間隔（秒） |
| `markSeen` | `true` | 読み取り後に既読にするか |
| `maxBodyChars` | `12000` | 本文の最大文字数 |
| `subjectPrefix` | `"Re: "` | 返信件名のプレフィックス |
| `allowFrom` | `[]` | 対話を許可する送信者アドレスのリスト |

---

## ステップ 3: 起動する

```bash
nanobot gateway
```

nanobot は `pollIntervalSeconds` 秒ごとにメールボックスをチェックし、新しいメールを処理して返信します。

---

## 読み取り専用モード（自動返信しない）

メールを解析するだけで自動返信したくない場合:

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

## すべての送信者を許可する

任意の送信者からのメールを受け付ける（公開 bot）場合:

```json
{
  "channels": {
    "email": {
      "allowFrom": ["*"]
    }
  }
}
```

!!! warning "スパムメールのリスク"
    `allowFrom` を `["*"]` にすると、スパムを含むすべてのメールを処理します。制御された環境でのみ使用してください。

---

## よくある質問

**Gmail に「ログインがブロックされました」と表示される？**

- Google アカウントのパスワードではなく App Password を使っているか確認する
- 2 段階認証が有効か確認する

**SMTP 接続に失敗する？**

- Gmail（Port 587）：`smtpUseTls: true`、`smtpUseSsl: false`
- Gmail（Port 465）：`smtpUseTls: false`、`smtpUseSsl: true`
- `fromAddress` と `smtpUsername` が一致しているか確認する

**Bot がメールに返信しない？**

- `consentGranted` が `true` か確認する
- 送信者アドレスが `allowFrom` に含まれているか確認する
- ログで IMAP ポーリングが正常に動作しているか確認する
