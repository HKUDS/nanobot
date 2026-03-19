# Email

nanobot can own its own email account. It polls **IMAP** for unread mail and replies via **SMTP**, acting like a personal email assistant.

---

## Prerequisites

- A dedicated email account for the bot (recommended)
- IMAP and SMTP credentials
- Gmail, Outlook, or any standard IMAP/SMTP server is supported

---

## Consent gate

!!! warning "`consentGranted` is required"
    `consentGranted` must be set to `true` to access the mailbox. This safety gate prevents accidental access to a real mailbox. If it remains `false` or unset, the channel stays disabled even when `enabled` is `true`.

---

## Step 1: Prepare your email account

### Gmail setup

1. Create a dedicated Gmail account (e.g., `my-nanobot@gmail.com`)
2. Go to Google Account → **Security** → enable 2-Step Verification
3. Visit [App Passwords](https://myaccount.google.com/apppasswords) → create a new app password
4. Record the 16-character password (use it for both IMAP and SMTP)

!!! tip "Use an App Password"
    App Passwords are more secure and bypass 2-step verification requirements.

### Outlook / Hotmail setup

Use IMAP host `outlook.office365.com` (port 993) and SMTP host `smtp-mail.outlook.com` (port 587).

### Custom SMTP/IMAP server

Enter the server addresses and ports provided by your email provider.

---

## Step 2: Configure `config.json`

### Gmail example

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

### Outlook example

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

### Full configuration options

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

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Whether to enable this channel |
| `consentGranted` | `false` | **Must be `true` to access mail** |
| `imapHost` | `""` | IMAP server host |
| `imapPort` | `993` | IMAP port (SSL typically 993) |
| `imapUsername` | `""` | IMAP username |
| `imapPassword` | `""` | IMAP password |
| `imapMailbox` | `"INBOX"` | Mailbox folder to monitor |
| `imapUseSsl` | `true` | Use SSL/TLS for IMAP |
| `smtpHost` | `""` | SMTP server host |
| `smtpPort` | `587` | SMTP port (STARTTLS typically 587) |
| `smtpUsername` | `""` | SMTP username |
| `smtpPassword` | `""` | SMTP password |
| `smtpUseTls` | `true` | Use STARTTLS (required for Gmail 587) |
| `smtpUseSsl` | `false` | Use SSL (set to `true` for port 465) |
| `fromAddress` | `""` | From address used in replies |
| `autoReplyEnabled` | `true` | Whether to auto-reply (set to `false` to only read) |
| `pollIntervalSeconds` | `30` | IMAP poll interval in seconds |
| `markSeen` | `true` | Mark messages as read after processing |
| `maxBodyChars` | `12000` | Maximum characters of the email body |
| `subjectPrefix` | `"Re: "` | Prefix added to reply subjects |
| `allowFrom` | `[]` | Allowed sender address list |

---

## Step 3: Run nanobot

```bash
nanobot gateway
```

nanobot polls your mailbox every `pollIntervalSeconds` seconds, processes new mail, and replies automatically.

---

## Read-only mode (no auto-reply)

To only analyze email without replying automatically:

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

## Allow any senders

To accept mail from anyone (public bot):

```json
{
  "channels": {
    "email": {
      "allowFrom": ["*"]
    }
  }
}
```

!!! warning "Spam risk"
    Setting `allowFrom` to `["*"]` accepts mail from every sender, including spam. Use only in controlled environments.

---

## FAQ

**Gmail shows “sign-in blocked”?**

- Use an App Password instead of your Google account password
- Ensure 2-Step Verification is enabled

**SMTP connection fails?**

- Gmail port 587: `smtpUseTls: true`, `smtpUseSsl: false`
- Gmail port 465: `smtpUseTls: false`, `smtpUseSsl: true`
- Make sure `fromAddress` matches `smtpUsername`

**Bot not replying to emails?**

- Confirm `consentGranted` is `true`
- Ensure the sender is listed in `allowFrom`
- Check the logs for IMAP polling issues
