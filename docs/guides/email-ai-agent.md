# Build an Email AI Agent with nanobot

This guide turns nanobot into an email AI agent that polls IMAP for accepted messages and replies through SMTP.

## What this guide builds

- a dedicated mailbox for nanobot
- IMAP and SMTP credentials in `config.json`
- an allowed sender list
- a gateway process that polls and replies

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- A mailbox for the bot.
- IMAP and SMTP access. For Gmail, use an app password rather than your account password.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Enable the Email channel

Prepare a dedicated mailbox and app password. In **Channels → Email**, grant mailbox access, enter IMAP and SMTP settings, and restrict allowed senders. Use **Advanced** for trusted authentication services and other mailbox options. Enable the channel, save, and follow any restart prompt.

<details>
<summary>Manual configuration</summary>

Merge this snippet into `~/.nanobot/config.json` and replace the addresses and passwords:

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
      "trustedAuthservIds": ["mx.google.com"],
      "autoReplyEnabled": true
    }
  }
}
```

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

Send an email from an address in `allowFrom` to the bot mailbox. Keep the gateway running long enough for the polling interval to receive it.

## Security notes

- Use a dedicated mailbox, not your primary personal inbox.
- Set `consentGranted` to `false` to fully disable mailbox access.
- Email does not use DM pairing. Keep `allowFrom` narrow; `["*"]` accepts mail from anyone.
- Keep SPF/DKIM verification enabled and set `trustedAuthservIds` to the exact `authserv-id` added by your receiving mail service. For Gmail this is normally `mx.google.com`. The service must prepend one consolidated `Authentication-Results` header and remove inbound headers claiming the same identity. nanobot rejects authenticated email when this trust anchor is missing or appears more than once.
- Use environment variables for mailbox passwords.
- Enable attachment types only when the agent needs them.

## Upgrading to v0.3.5

Email authentication now requires an explicit receiving-service trust anchor. This is a security-related configuration change: an existing email channel with `verifySpf` or `verifyDkim` enabled will not start without `trustedAuthservIds`. Other channels, mailbox credentials, stored messages, and `allowFrom` do not need to be migrated. Existing values are not automatically rewritten.

1. Back up your configuration and temporarily disable the Email channel while configuring the receiver. Do not turn off SPF/DKIM verification as an upgrade workaround.
2. Confirm with your receiving mail service or administrator which exact `authserv-id` it adds, and that it strips externally supplied headers claiming that identity. It must provide one consolidated `Authentication-Results` header. A name visible in a received email is not, by itself, proof of trust; do not infer it from your IMAP hostname or copy it from an arbitrary message.
3. In **Channels → Email**, open **Advanced** and set **Trusted authentication services** to your confirmed receiver identity. Keep SPF/DKIM verification enabled.

   <details>
   <summary>Manual configuration</summary>

   Merge these fields into `channels.email` in your existing config:

   ```json
   {
     "verifySpf": true,
     "verifyDkim": true,
     "trustedAuthservIds": ["mx.google.com"]
   }
   ```

   The example is for a receiver using `mx.google.com`; use your confirmed receiver identity instead. JSON uses a list; the WebUI accepts comma-separated values. Wildcards and URLs are not accepted. Multiple configured identities are alternatives, not permission to combine multiple trusted result headers.

   </details>

4. Check the IMAP/SMTP connection, re-enable Email, and restart the gateway after editing a configuration file. Send one ordinary message from an allowed address and confirm receipt and reply. A successful connection check verifies credentials and configuration, not your mail service's header-stripping policy.

Each enabled verification method must pass and identify the visible sender's domain, or a parent/subdomain of it. DKIM uses `header.d` when present, otherwise the domain of the receiver-reported `header.i`. This is not a full DMARC policy implementation, and domain authentication does not independently authenticate the mailbox local part. Forwarders, mailing lists, or receivers that emit separate SPF and DKIM result headers may need mail-service changes. Keep Email disabled if the receiver cannot meet the trust contract.

Authentication failures remain skipped messages. Keep the default `postActionIgnoreSkipped: true` while checking the migration; setting it to `false` allows your configured move/delete action to affect skipped mail too. If the migration cannot be completed, disable Email rather than reverting to an older authentication policy.

## Troubleshooting

- If login fails, confirm IMAP/SMTP access and app-password setup.
- If Email will not start and reports `trusted_authserv_ids` as missing, complete the upgrade steps above. A configured receiver still needs to emit compatible, aligned authentication results for each enabled verification method.
- If the bot reads but does not reply, check `autoReplyEnabled`, SMTP settings, and allowed sender addresses.
- If attachments are missing, review `allowedAttachmentTypes`, size limits, and gateway logs.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Secure local AI agent](./secure-local-ai-agent.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [OpenAI-compatible agent API](./openai-compatible-agent-api.md)
