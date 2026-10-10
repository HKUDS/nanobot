# Build an official WhatsApp agent with nanobot

This guide connects nanobot to WhatsApp through the `whatsapp_agent` channel, which uses the **official WhatsApp Agent Platform** API. The agent appears as its own chat inside WhatsApp and talks only to you.

This is a different product from the [`whatsapp`](./whatsapp-ai-agent.md) channel.

## Which WhatsApp channel should I use?

| | `whatsapp_agent` (this guide) | `whatsapp` |
|---|---|---|
| How it connects | An official agent API token | A linked WhatsApp device (QR) |
| API | `https://api.whatsapp.com/agent/v1` | Neonize device session |
| Who it can talk to | Only you, the agent's creator | Chats and groups the linked device can see |
| Groups | Not supported | Supported |
| Message transport | Long-polling `GET /updates` | Device connection |
| End-to-end encryption | **No** — Meta manages agent chats | Yes, like a linked device |
| Availability | Limited countries, per account | Wherever WhatsApp can link a device |
| Account risk | Officially supported interface | Uses an unofficial linked-device protocol |

Choose `whatsapp_agent` when you want an official, sandboxed personal assistant that WhatsApp itself provides, and you do not need group access. Keep `whatsapp` when you need groups, media breadth, or availability in a country where the Agent Platform has not rolled out.

Both channels can be enabled at once with different names and different access rules.

## What this guide builds

- the `whatsapp_agent` channel enabled in `config.json`
- a WhatsApp agent created from WhatsApp Settings
- the agent's API token stored in nanobot
- one approved sender

## Prerequisites

- A working local nanobot reply:

```bash
nanobot agent -m "Hello!"
```

- A WhatsApp account with **Settings → Agents** available. This experience is available only in limited countries and might not appear in your account yet.
- A machine that can keep `nanobot gateway` running. Outbound connections are enough; no inbound webhook or public URL is required.

## Step 1: Create the agent in WhatsApp

1. Open WhatsApp and go to **Settings → Agents → Create an agent**.
2. Set a display name and avatar.
3. Open the agent's chat, then **Chat info → API key**.
4. Copy the key. This is the agent's API token.

You can connect up to five agents to one WhatsApp account. The token is shown again only if you regenerate it, and rotating it invalidates the previous value immediately. If you uninstall WhatsApp, regenerate the token.

## Step 2: Enable the channel

The channel uses only nanobot core dependencies, so no optional install is required:

```bash
nanobot plugins enable whatsapp_agent
```

Or edit `~/.nanobot/config.json` directly:

```json
{
  "channels": {
    "whatsapp_agent": {
      "enabled": true,
      "token": "<AGENT_API_TOKEN>"
    }
  }
}
```

Keep the token in an environment variable instead of the file when you can, and reference it:

```json
{
  "channels": {
    "whatsapp_agent": {
      "enabled": true,
      "token": "${WA_AGENT_TOKEN}"
    }
  }
}
```

## Step 3: Run and test

```bash
nanobot gateway
```

Open the agent's chat in WhatsApp and send a message. The agent replies in the same chat using the same model, workspace, memory, and tools as the CLI and WebUI.

## Access control

The Agent Platform already restricts the conversation to you, the agent's creator. `allowFrom` is a second, local check and is optional.

When `allowFrom` is empty, an unapproved sender receives a pairing code. Approve it from a trusted local surface:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

The sender identifier has the form `user:<id>`. Treat it as opaque, never share it, and prefer pairing over hardcoding it, because the identifier can change if you change your phone number or re-register your account. nanobot stores the most recent identifier and uses it for replies.

## Configuration reference

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Load the channel at gateway start. |
| `token` | — | The agent's API token. Required. |
| `allowFrom` | `[]` | Extra local allowlist of `user:<id>` values, or `["*"]`. Empty means pairing-only. |
| `stateDir` | `~/.nanobot/whatsapp-agent` | Where the durable poll cursor and dedup state are stored. |
| `pollTimeout` | `25` | Long-poll hold time in seconds (0–25). |
| `markRead` | `true` | Send read receipts for inbound messages. |
| `typingIndicator` | `true` | Show "typing…" while the agent works. |
| `downloadMedia` | `true` | Download inbound image, audio, video, document, and sticker media. |
| `deleteMediaAfterDownload` | `false` | Delete the server copy once downloaded. |
| `maxMediaMb` | `16` | Local cap on inbound and outbound media, in MB. |
| `retryAmbiguousSends` | `false` | Retry sends whose outcome is unknown (HTTP 500, read timeouts). See "Delivery semantics". |
| `sendProgress` | `false` | Send agent progress messages. Off because each one spends the send budget. |
| `sendToolHints` | `false` | Send tool-call hints. Off for the same reason. |

## Media

Inbound media is downloaded, verified against the digest WhatsApp reports, then stored under the channel's media directory and passed to the agent like media from any other channel.

- Images: JPEG, PNG — 5 MB.
- Stickers: WebP — 500 KB.
- Video, audio, documents, generic files — 16 MB.
- Voice notes are transcribed when a transcription provider is configured; the audio file stays attached.

Outbound media is uploaded first, then sent as the matching message type. Files over the limit for their type, or with an MIME type the platform does not accept, are skipped with an error in the log instead of failing the whole reply.

Note that audio the agent sends arrives as a normal file attachment, not as a WhatsApp voice-note bubble.

Reactions are receive-only on this platform: the API rejects sending them. nanobot reads an inbound reaction (including an empty emoji, which means the reaction was removed) but does not forward it as a turn, so a reaction never triggers a reply. Media on both sides expires 30 days after it is stored; nanobot holds downloaded files locally and can delete the server copy with `deleteMediaAfterDownload`.

## Delivery semantics

The platform's send result determines whether a retry is safe:

- **Rate limit or "not accepted for delivery"** (`429`, `503`): the message was not sent, so nanobot retries with backoff.
- **A plain `500`, a dropped connection, or a read timeout**: WhatsApp cannot say whether the message was delivered. nanobot does **not** retry by default, because a duplicate is more disruptive than a missed reply. Set `retryAmbiguousSends` to `true` if you prefer a chance of duplicates over a chance of loss.

Replies longer than 4096 characters are split into multiple messages and sent in order. The first chunk quotes the message being answered.

At most one poller may run per agent token. If you start a second gateway against the same token, the older poll fails with `409`; nanobot logs this clearly and backs off. Run one gateway instance per agent.

## Operational notes

- **Rate limits.** WhatsApp allows 12 sends, 12 read receipts, 15 polls, and 12 media requests per minute per agent. nanobot paces each method below its own limit and counts retries against the same budget, which is why progress messages are off by default.
- **Durable cursor.** The poll cursor is written to disk after each handled message, so a restart resumes exactly where it stopped and a replayed batch is deduplicated by message id.
- **Retention.** WhatsApp keeps updates for 30 days. nanobot starts from the current head on first run, so it does not answer old history.
- **Invalid token.** If WhatsApp rejects the token, the channel stops and logs an actionable message instead of retrying forever.
- **Privacy.** Agent conversations are not end-to-end encrypted: Meta processes them on the agent's behalf. Your other WhatsApp chats are unaffected. Do not use this channel for data that requires end-to-end encryption.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Settings → Agents` is missing | The feature is not available in your country or account | Use the `whatsapp` channel instead |
| "API token was rejected" | Token rotated, revoked, or mistyped | Regenerate it in the agent's chat info and update the config |
| `409` in the logs | Two gateways share one agent token | Run a single gateway per agent |
| Agent never replies | No inbound message has arrived yet, so no recipient is known | Send the agent a message first |
| Media messages show a placeholder | Download failed, digest mismatch, or the file exceeded the limit | Check the log; re-send the file |
| Replies arrive late | The turn is longer than the 25-second typing window | This is expected; the reply still arrives |

## Next steps

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [Official WhatsApp agent help](https://faq.whatsapp.com/1050934623978152)
- [Secure local AI agent](./secure-local-ai-agent.md)
