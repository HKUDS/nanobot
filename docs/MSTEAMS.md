# Microsoft Teams (MVP)

This repository includes a built-in `msteams` channel MVP for Microsoft Teams direct messages.

## Current scope

- Direct-message text in/out
- Tenant-aware OAuth token acquisition
- Conversation reference persistence for replies
- Public HTTPS webhook support through a tunnel or reverse proxy

## Not yet included

- Group/channel handling
- Attachments and cards
- Polls
- Richer Teams activity handling

## Example config

```json
{
  "channels": {
    "msteams": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "appPassword": "YOUR_APP_SECRET",
      "tenantId": "YOUR_TENANT_ID",
      "host": "0.0.0.0",
      "port": 3978,
      "path": "/api/messages",
      "allowFrom": ["*"],
      "replyInThread": true,
      "mentionOnlyResponse": "Hi — what can I help with?",
      "validateInboundAuth": false,
      "restartNotifyEnabled": false,
      "restartNotifyPreMessage": "Nanobot agent initiated a gateway restart. I will message again when the gateway is back online.",
      "restartNotifyPostMessage": "Nanobot gateway is back online."
    }
  }
}
```

## Behavior notes

- `replyInThread: true` replies to the triggering Teams activity when a stored `activity_id` is available.
- `replyInThread: false` posts replies as normal conversation messages.
- If `replyInThread` is enabled but no `activity_id` is stored, Nanobot falls back to a normal conversation message.
- `mentionOnlyResponse` controls what Nanobot receives when a user sends only a bot mention such as `<at>Nanobot</at>`.
- Set `mentionOnlyResponse` to an empty string to ignore mention-only messages.
- `validateInboundAuth: true` enables inbound Bot Framework bearer-token validation.
- `validateInboundAuth: false` leaves inbound auth unenforced, which is safer while first validating a new relay, tunnel, or proxy path.
- When enabled, Nanobot validates the inbound bearer token signature, issuer, audience, token lifetime, and `serviceUrl` claim when present.
- `restartNotifyEnabled: true` enables optional Teams restart-notification configuration for external wrapper-script driven restarts.
- `restartNotifyPreMessage` and `restartNotifyPostMessage` control the before/after announcement text used by that external wrapper.

## Setup notes

1. Create or reuse a Microsoft Teams / Azure bot app registration.
2. Set the bot messaging endpoint to a public HTTPS URL ending in `/api/messages`.
3. Forward that public endpoint to `http://localhost:3978/api/messages`.
4. Start Nanobot with:

```bash
nanobot gateway
```

5. Optional: if you use an external restart wrapper (for example a script that stops and restarts the gateway), you can enable Teams restart announcements with `restartNotifyEnabled: true` and have the wrapper send `restartNotifyPreMessage` before restart and `restartNotifyPostMessage` after the gateway is back online.
