# Nanobot Email Assistant: End-to-End Guide

This guide explains how to run nanobot as a real email assistant with explicit user permission and optional automatic replies.

## 1. What This Feature Does

- Read unread emails via IMAP.
- Let the agent analyze/respond to email content.
- Send replies via SMTP.
- Enforce explicit owner consent before mailbox access.
- Let you toggle automatic replies on or off.

## 2. Permission Model (Required)

`channels.email.consentGranted` is the hard permission gate.

- `false`: nanobot must not access mailbox content and must not send email.
- `true`: nanobot may read/send based on other settings.

Only set `consentGranted: true` after the mailbox owner explicitly agrees.

## 3. Auto-Reply Mode

`channels.email.autoReplyEnabled` controls outbound automatic email replies.

- `true`: inbound emails can receive automatic agent replies.
- `false`: inbound emails can still be read/processed, but automatic replies are skipped.

Use `autoReplyEnabled: false` when you want analysis-only mode.

## 4. Required Account Setup (Gmail Example)

1. Enable 2-Step Verification in Google account security settings.
2. Create an App Password.
3. Use this app password for both IMAP and SMTP auth.

Recommended servers:
- IMAP host/port: `imap.gmail.com:993` (SSL)
- SMTP host/port: `smtp.gmail.com:587` (STARTTLS)

## 5. Config Example

Edit `~/.nanobot/config.json`:

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "you@gmail.com",
      "imapPassword": "${NANOBOT_EMAIL_IMAP_PASSWORD}",
      "imapMailbox": "INBOX",
      "imapUseSsl": true,
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "you@gmail.com",
      "smtpPassword": "${NANOBOT_EMAIL_SMTP_PASSWORD}",
      "smtpUseTls": true,
      "smtpUseSsl": false,
      "fromAddress": "you@gmail.com",
      "autoReplyEnabled": true,
      "pollIntervalSeconds": 30,
      "markSeen": true,
      "allowFrom": ["trusted.sender@example.com"]
    }
  }
}
```

## 6. Set Secrets via Environment Variables

In the same shell before starting gateway:

```bash
read -s "NANOBOT_EMAIL_IMAP_PASSWORD?IMAP app password: "
echo
read -s "NANOBOT_EMAIL_SMTP_PASSWORD?SMTP app password: "
echo
export NANOBOT_EMAIL_IMAP_PASSWORD
export NANOBOT_EMAIL_SMTP_PASSWORD
```

If you use one app password for both, enter the same value twice.

## 7. Run and Verify

Start:

```bash
cd /Users/kaijimima1234/Desktop/nanobot
PYTHONPATH=/Users/kaijimima1234/Desktop/nanobot .venv/bin/nanobot gateway
```

Check channel status:

```bash
PYTHONPATH=/Users/kaijimima1234/Desktop/nanobot .venv/bin/nanobot channels status
```

Expected behavior:
- `enabled=true + consentGranted=true + autoReplyEnabled=true`: read + auto reply.
- `enabled=true + consentGranted=true + autoReplyEnabled=false`: read only, no auto reply.
- `consentGranted=false`: no read, no send.

## 8. Commands You Can Tell Nanobot

Once gateway is running and email consent is enabled:

1. Summarize yesterday's emails:

```text
summarize my yesterday email
```

or

```text
!email summary yesterday
```

2. Send an email to a friend:

```text
!email send friend@example.com | Subject here | Body here
```

or

```text
send email to friend@example.com subject: Subject here body: Body here
```

Notes:
- Sending command always performs a direct send (manual action by you).
- If `consentGranted` is `false`, send/read are blocked.
- If `autoReplyEnabled` is `false`, automatic replies are disabled, but direct send command above still works.

## 9. End-to-End Test Plan

1. Send a test email from an allowed sender to your mailbox.
2. Confirm nanobot receives and processes it.
3. If `autoReplyEnabled=true`, confirm a reply is delivered.
4. Set `autoReplyEnabled=false`, send another test email.
5. Confirm no auto-reply is sent.
6. Set `consentGranted=false`, send another test email.
7. Confirm nanobot does not read/send.

## 10. Security Notes

- Never commit real passwords/tokens into git.
- Prefer environment variables for secrets.
- Keep `allowFrom` restricted whenever possible.
- Rotate app passwords immediately if leaked.

## 11. PR Checklist

- [ ] `consentGranted` gating works for read/send.
- [ ] `autoReplyEnabled` toggle works as documented.
- [ ] README updated with new fields.
- [ ] Tests pass (`pytest`).
- [ ] No real credentials in tracked files.
