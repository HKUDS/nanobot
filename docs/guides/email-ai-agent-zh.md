# 使用 nanobot 构建邮件 AI Agent

本指南将 nanobot 转变为一个邮件 AI agent：它通过 IMAP 轮询已接受的
邮件，并通过 SMTP 回复。

## 本指南构建的内容

- 一个专用于 nanobot 的邮箱
- `config.json` 中的 IMAP 和 SMTP 凭据
- 一个允许的发件人列表
- 一个用于轮询和回复的 gateway 进程

## 前提条件

- 可正常工作的本地 nanobot 回复：

```bash
nanobot agent -m "Hello!"
```

- 一个供 bot 使用的邮箱。
- IMAP 和 SMTP 访问权限。对于 Gmail，请使用应用专用密码，而非账户
  密码。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 启用 Email channel

将以下片段合并到 `~/.nanobot/config.json`，并替换地址和
密码：

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
      "allowFrom": ["your-real-email@gmail.com"],
      "autoReplyEnabled": true
    }
  }
}
```

## 运行 nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## 测试邮件

从 `allowFrom` 中的地址向 bot 邮箱发送邮件。保持 gateway 持续运行足够长的
时间，以便轮询间隔接收邮件。

## 安全说明

- 使用专用邮箱，而不是您的主要个人收件箱。
- 将 `consentGranted` 设置为 `false`，以完全禁用邮箱访问。
- Email 不使用 DM 配对。请保持 `allowFrom` 范围较窄；`["*"]` 会接受
  任何人的邮件。
- 对邮箱密码使用环境变量。
- 仅在 agent 需要时启用附件类型。

## 故障排除

- 如果登录失败，请确认 IMAP/SMTP 访问权限和应用专用密码设置。
- 如果 bot 已读取但未回复，请检查 `autoReplyEnabled`、SMTP 设置和
  允许的发件人地址。
- 如果附件缺失，请检查 `allowedAttachmentTypes`、大小限制和
  gateway 日志。

## 下一步：memory、自动化、MCP tools

- [Chat Apps 参考](../chat-apps-zh.md)
- [安全的本地 AI agent](secure-local-ai-agent-zh.md)
- [AI Agent Memory](ai-agent-memory-zh.md)
- [兼容 OpenAI 的 agent API](openai-compatible-agent-api-zh.md)
