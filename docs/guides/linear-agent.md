# Connect nanobot as a Native Linear Agent

This guide takes you from an empty Linear channel configuration to a working
@mention in an issue. The recommended path uses the nanobot WebUI and a
pre-filled Linear app manifest, so you do not need to enter callback URLs or
webhook subscriptions by hand.

> [!NOTE]
> Linear's Agent APIs are currently a Developer Preview. Their schema may
> change. Keep nanobot current when you use this channel.

## What this channel does

- A new task starts only when someone explicitly @mentions the installed app.
- An ordinary issue comment does not invoke nanobot.
- A follow-up inside the existing Agent Session continues the same nanobot
  session without another @mention.
- Linear's stop control cancels the active nanobot turn.
- nanobot reports its acknowledgement, tool activity, reasoning, and final
  answer as native Linear Agent Activities.

The OAuth request includes `app:mentionable` and deliberately excludes
`app:assignable`. Do not add `app:assignable` if every new task must start with
an @mention.

Linear MCP is optional. Add it when the agent also needs tools for searching or
changing Linear issues. MCP does not replace this channel's OAuth installation,
webhook, or Agent Session transport.

## Before you start

Prepare these four things:

| Requirement | What you need |
|---|---|
| Working nanobot | `nanobot agent -m "Hello"` returns a response |
| Linear access | Permission to create a private OAuth app; a workspace admin must approve its installation |
| Public HTTPS origin | A stable address such as `https://nanobot.example.com` |
| Local route | The public address forwards to nanobot's Linear listener, which defaults to port `3979` |

The public address is an **origin**, not a complete endpoint. Enter
`https://nanobot.example.com`, not
`https://nanobot.example.com/linear/webhook`.

The four network fields have different jobs:

| nanobot field | Who uses it | Recommended value |
|---|---|---|
| **Public HTTPS URL** | Linear calls this address over the internet | Your stable HTTPS origin |
| **Listen host** | nanobot binds this local interface | `127.0.0.1` for a same-machine proxy; `0.0.0.0` when a container or another host must reach it |
| **Listen port** | The proxy or tunnel forwards to this local port | Keep `3979` unless it conflicts with another service |
| **Webhook/OAuth paths** | nanobot distinguishes webhook delivery from OAuth callbacks | Keep the defaults unless your proxy requires different paths |

### Webhook and networking requirements

The native Linear Agent transport requires a webhook; there is no polling mode.
The OAuth callback also needs to reach the same nanobot instance.

You do **not** need a public IP address. A reverse proxy or HTTPS tunnel can
forward a public hostname to `127.0.0.1:3979`. Cloudflare Tunnel, Tailscale
Funnel, Caddy, nginx, and similar tools can all provide this route. Use a stable
hostname for normal use: if the hostname changes, you must update both URLs in
the Linear app.

Choose the simplest option that matches your deployment:

| Your deployment | Recommended route |
|---|---|
| Home server, laptop, or a network behind NAT | A named HTTPS tunnel with a fixed hostname |
| VPS with a domain and existing HTTPS proxy | Add a reverse-proxy route to `127.0.0.1:3979` |
| Docker or Kubernetes | Route the ingress or proxy to the container's port `3979`; keep the public URL on the ingress |
| Short local test | A temporary HTTPS tunnel works, but you must recreate or edit the Linear app when its hostname changes |

With the default paths, the route must preserve these two requests:

```text
https://nanobot.example.com/linear/oauth/callback  -> 127.0.0.1:3979
https://nanobot.example.com/linear/webhook         -> 127.0.0.1:3979
```

If the proxy or tunnel runs on the same machine, set the advanced **Listen
host** field to `127.0.0.1` so the listener is not exposed directly on the local
network. Containers and separate reverse-proxy hosts may require `0.0.0.0`.
The Linear listener serves plain HTTP locally; terminate HTTPS at the proxy or
tunnel instead of exposing port `3979` directly to the internet.

## Recommended setup in the WebUI

Keep `nanobot webui` running throughout the setup.

### 1. Save the public address

1. Open **Settings → Channels → Linear**.
2. Enter your stable origin in **Public HTTPS URL**, for example
   `https://nanobot.example.com`.
3. Leave the three OAuth credential fields empty for now.
4. Select **Save settings**. nanobot saves the partial configuration and shows
   **Create prefilled Linear app**.

Saving a partial configuration at this point is expected. You will create the
credentials in the next step.

### 2. Create the Linear app

1. Select **Create prefilled Linear app**. Sign in to the Linear workspace in
   which you want to create the app.
2. Review the pre-filled form. It should describe a **private** app and contain:

   ```text
   Redirect URI:  https://nanobot.example.com/linear/oauth/callback
   Webhook URL:   https://nanobot.example.com/linear/webhook
   Webhook types: AgentSessionEvent, PermissionChange, OAuthAuthorization
   ```

3. Choose a short, recognizable app name and icon if you want to customize how
   nanobot appears in Linear.
4. Create the app.

Do not add a `Comment` webhook subscription. Linear delivers new @mentions and
Agent Session follow-ups through `AgentSessionEvent`; subscribing to comments
would add events that this channel intentionally ignores.

### 3. Copy the three credentials into nanobot

In the new Linear app's settings, copy these values:

| Linear value | nanobot field |
|---|---|
| Client ID | **OAuth client ID** |
| Client Secret | **OAuth client secret** |
| Webhook signing secret | **Webhook signing secret** |

Return to **Settings → Channels → Linear**, paste all three values, and select
**Save settings** again. A successful validation lists the complete webhook and
OAuth callback URLs.

Treat the Client Secret and Webhook signing secret like passwords. They belong
only in the nanobot configuration and the Linear application settings.

### 4. Authorize the workspace

1. Select **Connect Linear**.
2. Open the displayed authorization link, or scan the QR code.
3. Choose the workspace and approve the installation as a workspace admin.
4. Return to nanobot and wait for **Linear is connected**.

nanobot enables the channel automatically after authorization. The gateway must
remain running so Linear can deliver webhooks. To replace an authorization, use
the reconnect action and approve it again.

The pre-filled manifest creates a private app for the current workspace. A
distributable OAuth app can authorize additional workspaces; nanobot stores and
refreshes each workspace installation separately.

### 5. Test the first task

1. Open an issue in the connected Linear workspace.
2. Add a comment that @mentions the app and includes a request, for example:

   ```text
   @nanobot summarize the likely cause and suggest the next diagnostic step
   ```

3. Open the Agent Session. You should first see a starting acknowledgement,
   followed by agent activity and a final response.
4. Send a follow-up inside that Agent Session. You do not need to @mention the
   app again there.

If **Allowed Linear users** is empty, the first mention returns a nanobot pairing
code. Approve the pending request in the WebUI pairing dialog, then repeat the
prompt in the same Agent Session. For a static allowlist, enter Linear user IDs
in **Allowed Linear users**. Enter `*` only if every member of every connected
workspace should be able to invoke the agent.

## Verify the setup

The setup is complete when all of these checks pass:

- **Settings → Channels → Linear** shows the channel as on with no runtime error.
- While the channel is running, opening
  `http://127.0.0.1:3979/linear/health` on the nanobot machine returns
  `{"ok":true}`. Use your configured host and port if you changed them.
- A new comment with an explicit @mention creates an Agent Session and receives
  a response.
- A normal issue comment without an @mention does nothing.
- A follow-up inside the Agent Session receives a response without another
  @mention.

## Manual configuration

Use this path when deployment tooling manages `~/.nanobot/config.json` directly.
The WebUI path above is easier because it generates the Linear app definition
and completes OAuth for you.

Merge this section into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "linear": {
      "enabled": true,
      "clientId": "YOUR_LINEAR_CLIENT_ID",
      "clientSecret": "YOUR_LINEAR_CLIENT_SECRET",
      "webhookSigningSecret": "YOUR_LINEAR_WEBHOOK_SIGNING_SECRET",
      "publicBaseUrl": "https://nanobot.example.com",
      "host": "127.0.0.1",
      "port": 3979,
      "webhookPath": "/linear/webhook",
      "oauthCallbackPath": "/linear/oauth/callback",
      "allowFrom": ["YOUR_LINEAR_USER_ID"]
    }
  }
}
```

Register these exact URLs in the Linear OAuth app:

```text
OAuth callback: https://nanobot.example.com/linear/oauth/callback
Webhook:        https://nanobot.example.com/linear/webhook
```

Subscribe the webhook to exactly `AgentSessionEvent`, `PermissionChange`, and
`OAuthAuthorization`. Do not subscribe to `Comment`. The OAuth connection step
in the WebUI is still required: it installs the app and stores the
workspace-scoped access and refresh tokens.

## Security and reliability

- OAuth uses authorization code flow, PKCE, a short-lived CSRF state, and the
  Linear app actor.
- Webhooks are verified against `Linear-Signature` using the raw request body
  before JSON parsing. nanobot also checks the delivery timestamp and configured
  OAuth Client ID.
- `Linear-Delivery` IDs are deduplicated.
- Verified events are committed to a local SQLite queue before nanobot returns
  HTTP 200. Pending work resumes after a restart.
- Access and rotating refresh tokens are stored in the Linear channel state
  database, not in `config.json` or the browser.
- OAuth revocation removes the affected workspace installation locally.

Back up the nanobot instance data directory as carefully as other credentials.
Do not publish `linear/state.sqlite3`, the Client Secret, or the Webhook signing
secret.

## Troubleshooting

| Symptom | What to check |
|---|---|
| **Create prefilled Linear app** is missing | Enter only the public HTTPS origin in **Public HTTPS URL**, then select **Save settings**. |
| Linear rejects the callback or webhook URL | Use a stable public `https://` hostname. Do not use HTTP, localhost, a private IP, or a path in **Public HTTPS URL**. |
| OAuth opens but cannot finish | Keep `nanobot webui` running. Confirm the proxy forwards `/linear/oauth/callback` to the configured listen host and port. Then start **Connect Linear** again. |
| OAuth finishes in Linear but nanobot keeps waiting | The callback reached a different nanobot process or URL. Compare the app's Redirect URI with the callback URL shown by nanobot. |
| The local health URL does not load | Start **Connect Linear** or enable the connected channel, then check the configured listen host and port. |
| An @mention gets no response | Confirm `AgentSessionEvent` is subscribed, the Client ID and signing secret match the same app, and the workspace authorization has not been revoked. Run `nanobot gateway logs` for the exact error. |
| The first @mention returns a pairing code | Approve it in the WebUI pairing dialog, then repeat the prompt in the same Agent Session. Alternatively, configure a narrow **Allowed Linear users** list. |
| Normal comments do nothing | This is intentional. Start a task by @mentioning the app, or continue inside an existing Agent Session. |
| Issues can be delegated to the app without an @mention | Remove `app:assignable`, reconnect the workspace, and use nanobot's built-in OAuth flow, which requests only `read`, `write`, and `app:mentionable`. |
| Authorization reports missing scopes | Reconnect from nanobot. Do not reuse an authorization URL that omits `read`, `write`, or `app:mentionable`. |

For Linear's platform-side behavior, see the official
[Agents guide](https://linear.app/developers/agents),
[OAuth app manifest reference](https://linear.app/developers/oauth-app-manifests),
[OAuth guide](https://linear.app/developers/oauth-2-0-authentication), and
[webhook reference](https://linear.app/developers/webhooks).
