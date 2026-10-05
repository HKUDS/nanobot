# Connect nanobot as a Native Linear Agent

This guide takes you from an empty Linear channel configuration to a working
@mention or delegated issue. The recommended path uses the nanobot WebUI and a
pre-filled Linear app manifest. Review the generated URLs and subscriptions,
and confirm that webhook delivery is enabled before testing a task.

> [!NOTE]
> Linear's Agent APIs are currently a Developer Preview. Their schema may
> change. Keep nanobot current when you use this channel.

## What this channel does

- A new task starts when someone explicitly @mentions the installed app or
  delegates an issue to it.
- An ordinary issue comment does not invoke nanobot.
- A follow-up inside the existing Agent Session continues the same nanobot
  session without another @mention.
- Linear's stop control asks nanobot to cancel the active turn. The sender must
  have access, just as for other requests. An activity already delivered to
  Linear cannot be recalled.
- nanobot reports its acknowledgement, tool activity, reasoning, and final
  answer as native Linear Agent Activities.
- Button choices are sent as Linear selection activities, and local outbound
  files are uploaded to Linear before they are linked in the response.
- Private `uploads.linear.app` links in the session prompt are downloaded with
  the workspace OAuth token and passed to nanobot as inbound media after access
  checks. A prompt can import up to 10 attachments and 40 MB in total; skipped
  or unavailable files are called out in the prompt instead of failing silently.

The OAuth request includes `app:mentionable` and `app:assignable`, in addition
to `read` and `write`. Existing workspace installations must be reconnected to
grant `app:assignable`.

The native channel owns Agent Session transport. Connect the Linear MCP app when
the agent also needs tools for searching or changing Linear issues; OAuth scopes
on the channel do not expose those actions as nanobot tools. MCP does not replace
the channel's OAuth installation, webhook, or Agent Session transport.

## Before you start

There are two separate decisions: **connect a workspace**, then **choose who can
use nanobot**. The administrator sets up the app once; teammates do not need to
create their own apps, paste credentials, or scan a code.

```text
Prepare HTTPS → Create the Linear app → Save credentials in nanobot
             → Authorize a workspace → Enable members → Try an @mention
```

The HTTPS address receives Linear events. OAuth installs the app in a workspace.
Member access controls who may ask your nanobot to do work. These steps serve
different purposes; authorizing a workspace does not automatically approve all
its members.

Prepare these four things:

| Requirement | What you need |
|---|---|
| Working nanobot | `nanobot agent -m "Hello"` returns a response |
| Linear access | Permission to create a private OAuth app; a workspace admin must approve its installation |
| Public HTTPS origin | A reachable address such as `https://nanobot.example.com`; use a fixed hostname for ongoing use |
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

You do **not** need a public IP address when using an HTTPS tunnel such as
Cloudflare Tunnel or Tailscale Funnel. On a publicly reachable server, Caddy,
nginx, or another reverse proxy can provide HTTPS and forward requests to
`127.0.0.1:3979`. Use a stable hostname for normal use: if the hostname changes,
update **Public HTTPS URL** in nanobot and both registered URLs in the Linear app.

Choose the simplest option that matches your deployment:

| Your deployment | Recommended route |
|---|---|
| Home server, laptop, or a network behind NAT | A named HTTPS tunnel with a fixed hostname |
| VPS with a domain and existing HTTPS proxy | Add a reverse-proxy route to `127.0.0.1:3979` |
| Docker or Kubernetes | Route the ingress or proxy to the container's port `3979`; keep the public URL on the ingress |
| Short local test | A temporary HTTPS tunnel works; update nanobot's public URL and the app's callback and webhook URLs whenever its hostname changes |

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

Only the callback and webhook need public routes. Keep the nanobot WebUI and
admin API private, for example behind a VPN or SSH tunnel. Do not point your
public hostname at the WebUI port. An HTTPS endpoint is not an invitation to run
the agent: webhooks must pass signature checks, and senders must pass access checks.

### Temporary HTTPS for a local test

Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/),
then run it in a separate terminal:

```bash
cloudflared tunnel --url http://127.0.0.1:3979
```

Use the printed `https://<random-name>.trycloudflare.com` origin as **Public
HTTPS URL** in the setup below. Keep the tunnel running throughout authorization
and testing. The listener starts when you select **Connect Linear**, so a 502
before that step can mean the local listener has not started yet.

[Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
are intended for testing and generate a new hostname on restart. Update the
nanobot public URL and the Linear app's Redirect URI and Webhook URL before
continuing with a new hostname.

These settings must be updated together:

| Setting | Value with the new tunnel hostname |
|---|---|
| nanobot **Public HTTPS URL** | `https://<new-hostname>.trycloudflare.com` |
| Linear **Redirect URIs** | `https://<new-hostname>.trycloudflare.com/linear/oauth/callback` |
| Linear **Webhooks → URL** | `https://<new-hostname>.trycloudflare.com/linear/webhook` |

Updating only the Redirect URI allows OAuth to succeed but leaves task events
pointing at the old tunnel. After updating the Webhook URL, also check its
**Delivery status**; a correct URL does not enable delivery by itself.

## Recommended setup in the WebUI

Keep `nanobot webui` running throughout the setup.

### 1. Enter the public address

1. Open **Settings → Channels → Linear**.
2. Enter your public origin in **Public HTTPS URL**, for example
   `https://nanobot.example.com`.
3. Leave the three credential fields empty for now.
4. Wait for **Settings saved.**, then select **Create Linear app**. Selecting it
   before entering an address shows a prompt and returns focus to the URL field.

Saving a partial configuration at this point is expected. You will create the
credentials in the next step.

### 2. Create the Linear app

1. Select **Create Linear app**. Sign in to the Linear workspace in
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
5. In the app's **Webhooks** section, check **Delivery status**. If it is
   **Disabled**, use the adjacent **…** menu to enable delivery. Confirm the URL
   points to the current public origin and that **Events** includes
   **Agent session events** (`AgentSessionEvent`).

> [!IMPORTANT]
> OAuth authorization and webhook delivery are separate. Authorization can
> succeed while webhook delivery is disabled. In that state, Linear can create
> an Agent Session, but nanobot receives no task and Linear may report
> **Agent didn't start** or **nanobot failed to start**.

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

Return to **Settings → Channels → Linear** and paste all three values. Ordinary
fields save automatically after a short pause. For each secret, select **Save**
beside that field and wait for its **Saved** status.
**Connect Linear** becomes available once the required settings are saved.
Listener settings, callback paths, and allowed users are in **Advanced**; setup
guides are in the dialog's **Help** menu.

A masked value with **Saved** means this instance already has the secret; it is
not an empty input. To change it, select **Replace**, enter the new secret, then
**Save**. **Cancel** or Escape leaves the saved secret unchanged. Leaving the
field or showing the newly typed value does not save it. A failed save retains
the draft for retry; the old secret is never sent back to the browser.

Closing the dialog waits for in-flight saves, but does not save an unsubmitted
secret draft. Save each secret explicitly before continuing.

Treat the Client Secret and Webhook signing secret like passwords. They belong
only in the nanobot configuration and the Linear application settings.

### 4. Authorize the workspace

1. Select **Connect Linear**.
2. Select **Continue in Linear** to open authorization in your browser. There is
   no QR step.
3. Choose the workspace, review the app's permissions and team access, and
   approve the installation as a workspace admin.
4. Return to nanobot and wait for the **Channel running** badge. The
   **Authorized workspaces** section lists the workspace separately.

nanobot enables the channel automatically after authorization. The gateway must
remain running so Linear can deliver webhooks. Reopening the panel shows the
running channel and its authorized workspaces without another authorization
attempt. Use **… → Remove workspace** on a workspace to revoke its Linear OAuth
tokens and remove the local installation; see the lifecycle controls below for
what is kept.

The pre-filled manifest creates a private app for the current workspace. A
distributable OAuth app can authorize additional workspaces; nanobot stores and
refreshes each workspace installation separately.

### 5. Choose who can use nanobot

Under the workspace card, expand **Member access**, find yourself, and turn on
your switch. Do the same for any teammates you want to invite. Wait for **Saved**
beside each member; they can then use the agent without a pairing code.

You manage two levels here: **workspace → members**. A Linear team groups issues
and has its own workflow; it is not another installation to configure in nanobot.
The app can only work within the teams authorized in Linear. A member switch
does not expand that team access or grant access to the nanobot admin UI.

Pairing codes remain available as an alternative: a member without an explicit
switch setting can send a first prompt, have an administrator approve the code,
and repeat the prompt. An explicit **off** switch overrides pairing approval;
turn the switch on again to restore access.

### 6. Test the first task

1. Open an issue in the connected Linear workspace.
2. Add a comment that @mentions the app and includes a request, for example:

   ```text
   @nanobot summarize the likely cause and suggest the next diagnostic step
   ```

   You can instead delegate the issue to the app to start the Agent Session.
3. Open the Agent Session. You should first see a starting acknowledgement,
   followed by agent activity and a final response.
4. Send a follow-up inside that Agent Session. You do not need to @mention the
   app again there.

### Member access details

The list contains active human members of teams this app can access. It does not
grant access to additional Linear teams or to the nanobot admin UI. Names are for
display; permissions use stable user IDs scoped to the OAuth client and workspace.
Profile images come from Linear's `avatarUrl` field and load directly from its
`public.linear.app` or `uploads.linear.app` CDN without a referrer. Missing,
unsupported or failed images fall back to initials; no extra account linking is needed.
Workspace logos use Linear's optional `Organization.logoUrl` field with the same
CDN restrictions. They load independently of the workspace and member lists; a
missing or unavailable logo falls back to a workspace icon. Existing installations
do not need to authorize again to retrieve a logo.
Use **Refresh members** to refresh the directory and effective permission state.
The UI prefetches on hover or keyboard focus and keeps visited lists in memory,
scoped to this gateway, admin login, app configuration and workspace. Lists older
than one minute stay visible while refreshing. This display cache is not used to
authorize agent requests.
Workspace cards are also cached for one minute within the current gateway, admin
login and app configuration. Refreshing keeps existing cards visible, and a slow
logo request never blocks member access controls. Expand **Advanced** to inspect
OAuth scopes; authorization problems remain visible on the workspace card.

Each switch changes only after the server confirms the save; other members remain
editable while it saves. A failed save may have an uncertain outcome (for example,
after a timeout), so refresh before editing that member again. Failed refreshes keep
the last confirmed list visible and show an error, rather than an empty directory.

New members are off by default. Existing pairing approvals and **Advanced →
Allowed Linear users** remain valid until explicitly overridden by a member
switch. An explicit **off** wins over both legacy approvals and `*`, even if a
new pairing code is subsequently approved. Use the switch to enable that member
again. If you keep `*`, new members will still be allowed automatically; the UI
displays a warning. Remove `*` to require approval for new members.

Pairing remains a fallback for members without an explicit switch setting:
approve their pending request in the WebUI pairing dialog, then repeat the prompt
in the same Agent Session. You may also keep a static list of IDs in **Allowed
Linear users**. Other channels' pairing behavior is unchanged.

At request admission nanobot checks current team membership through the app's
Linear API authorization, including active status and excluding app accounts.
Directory/API failure does not authorize a task; transient failures use the
channel's bounded webhook retry path. This adds API requests and latency, rather
than relying on stale cached permissions. Turning a member off blocks new
requests (including stop requests); it does not cancel already admitted/running
tasks or recall replies. Administrators should stop ongoing tasks separately.

By default, reasoning is posted as Linear thought activities. Turn off **Show
reasoning** under **Advanced** for a quieter session. Use **Configure Linear
MCP**, to the left of **Create Linear app**, to open Linear MCP's connection
settings when prompts need to search, edit, or transition issues. Pairing and
access guidance is available in the dialog's **Help** menu.

## Connect, remove, or reset workspaces

Each nanobot instance uses one configured Linear OAuth app, which may have
multiple workspace installations. A **private** app can only be installed in its
own workspace. To use the same app in another workspace, its distribution must
allow that installation in Linear; changing a nanobot field cannot bypass this.

- **Connect workspace** uses the current app and opens the same browser
  authorization flow. Choose the other workspace in Linear, review team access,
  and authorize. You do not need another HTTPS address or another set of app
  credentials for the same app. Review member access in the new workspace.
- **… → Reauthorize** on a workspace updates its connection, without creating a
  duplicate or clearing its member choices. Use it to renew authorization or
  grant missing scopes. Cancelling authorization leaves existing connections alone.
- **… → Remove workspace** revokes that workspace's tokens and clears its local
  installation and member switches. Other workspaces are unaffected. Removing
  the last workspace also stops the channel. App credentials remain available
  for connecting again.
- **Advanced → Reset Linear connection** removes all installations for the
  current app, stops the channel, and clears this instance's Linear app settings,
  including its saved credentials. Use this when starting over or switching apps.
  If a step fails, the UI reports an incomplete reset; removed workspaces stay
  removed, and you can retry the remaining steps.

If authorization changes while a member refresh or removal is in progress,
nanobot discards the stale result instead of restoring a removed connection or
overwriting a new authorization. Refresh the workspace/member list and retry the
action against the current connection.

Neither removal nor reset deletes the Linear workspace, app, issues or comments,
nor nanobot conversation history or pairing approvals. Deleting the app itself
is a separate action in Linear. After removing and reconnecting a workspace,
member switches start fresh, but retained pairing approvals or an `allowFrom`
entry can still grant access. **Reset is not a wipe of all authorization history.**

## Updating a remote installation

Member management includes both Python channel code and WebUI assets. A local
branch does not update an already running remote gateway, and the browser UI
served by that remote gateway is not replaced by installing a local client.

1. Develop and test in a separate checkout with test-only config/state. Do not
   copy production OAuth tokens, model keys, or pairing state into a development
   profile, or run a second gateway against the production webhook installation.
2. After review and deployment approval, back up the remote config, pairing file,
   and Linear SQLite state consistently (stop the gateway or use SQLite backup;
   copying just the database while WAL writes are active is not sufficient).
3. Update the remote source and dependencies to the reviewed revision, build the
   WebUI from that same revision, and restart the gateway. Preserve remote
   credentials and state. Existing OAuth scopes and webhook routes need not change.
4. Verify member listing, the existing owner's access, enable/disable behavior,
   and that the admin UI remains private. Grant teammate access only deliberately.

Member switches are stored in the instance's `linear/state.sqlite3`, separately
from legacy pairing and config. Older code ignores those overrides: **do not
blindly roll back after revoking access with a switch**, because old code could
re-enable a member through a retained pairing approval or wildcard. Keep the
channel disabled during rollback until the older allowlist/pairing configuration
has been reconciled. Ordinary restarts and reconnecting the same OAuth app keep
the saved member choices.

## Verify the setup

The setup is complete when all of these checks pass:

- **Settings → Channels → Linear** shows the channel as on with no runtime error.
- The Linear app's **Webhooks → Delivery status** is enabled, its URL uses the
  current public origin, and **Events** includes **Agent session events**.
- While the channel is running, opening
  `http://127.0.0.1:3979/linear/health` on the nanobot machine returns
  `{"ok":true}`. Use your configured host and port if you changed them.
- If your proxy also forwards `/linear/health`, its public URL returns
  `{"ok":true}`. This is optional: a proxy exposing only the callback and webhook
  can correctly return 404 for public health. Use successful OAuth and webhook
  delivery to verify those two routes; do not expose the admin UI for this check.
- A new comment with an explicit @mention creates an Agent Session and receives
  a response.
- Delegating an issue to the app creates an Agent Session and receives a response.
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
      "allowFrom": ["YOUR_LINEAR_USER_ID"],
      "showReasoning": true
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
`OAuthAuthorization` and enable webhook delivery in the Linear app's settings.
Do not subscribe to `Comment`. The OAuth connection step
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
  HTTP 200. Queued webhook deliveries that have not yet been dispatched are
  retried after a restart. This does not guarantee resumption of an interrupted
  agent turn.
- Access and rotating refresh tokens are stored in the Linear channel state
  database, not in `config.json` or the browser.
- OAuth revocation removes the affected workspace installation locally.

Back up the nanobot instance data directory as carefully as other credentials.
Do not publish `linear/state.sqlite3`, the Client Secret, or the Webhook signing
secret.

## Troubleshooting

| Symptom | What to check |
|---|---|
| **Create Linear app** asks for a public address or waits for saving | Enter only the public HTTPS origin in **Public HTTPS URL** and wait for automatic saving to finish. If saving fails, correct the address or select **Retry**. |
| Linear rejects the callback or webhook URL | Use a public `https://` hostname. Do not use HTTP, localhost, a private IP, or a path in **Public HTTPS URL**. |
| `Invalid redirect_uri parameter for the application` | In the Linear app matching nanobot's Client ID, set **Redirect URIs** to the current public origin plus `/linear/oauth/callback` (or your configured OAuth path). It must match the authorization request's `redirect_uri`. Save, cancel the pending authorization in nanobot, and start **Connect Linear** again. |
| The tunnel URL changed | Update **Public HTTPS URL** in nanobot and the Redirect URI and Webhook URL in the Linear app, then start **Connect Linear** again. |
| Public health returns 502 | Start **Connect Linear** or enable the connected channel. Check local health first, then confirm the tunnel or proxy targets the same listener port. |
| OAuth opens but cannot finish | Keep `nanobot webui` running. Confirm the proxy forwards `/linear/oauth/callback` to the configured listen host and port. Then start **Connect Linear** again. |
| OAuth finishes in Linear but nanobot keeps waiting | Keep the nanobot connection dialog open. Confirm the Redirect URI reaches the same nanobot process, and inspect gateway logs for callback or token exchange errors. |
| A secret shows **Saved**, but no readable value | This is expected. The secret is stored on this instance and not returned to the browser. Use **Replace → Save** only when changing it. |
| Another workspace is unavailable during authorization | Check the current app's distribution and your installation permissions in Linear. A private app only works in its own workspace. **Connect workspace** does not create a new app. |
| The local health URL does not load | Start **Connect Linear** or enable the connected channel, then check the configured listen host and port. |
| **Agent didn't start**, **nanobot failed to start**, or a session stays on **Thinking…** without a response | First check **Webhooks → Delivery status** in the Linear app. If **Disabled**, enable it from **…**. Confirm the current Webhook URL and `AgentSessionEvent` subscription, then select **Retry** in the Linear session. OAuth success and a working `/linear/health` endpoint do not prove that Linear is sending events. |
| An @mention still gets no response with delivery enabled | Inspect **Webhook delivery failures** in the Linear app and run `nanobot gateway logs`. A 404 points to the webhook path; a 502 points to the listener or tunnel; a 401 can indicate a signing-secret mismatch or stale event timestamp. Confirm the Client ID and signing secret belong to the same app and the workspace authorization has not been revoked. |
| The first @mention returns a pairing code | Enable the member under the workspace's **Member access**, or approve the code in the WebUI pairing dialog, then repeat the prompt. An explicit off switch must be changed in **Member access**; pairing or allowlist changes do not override it. |
| Normal comments do nothing | This is intentional. Start a task by @mentioning the app, or continue inside an existing Agent Session. |
| Delegating an issue does not start a session | Reconnect the workspace so the installation grants `app:assignable`, then confirm the app can be selected as the issue delegate. |
| The agent can discuss an issue but cannot search or change it | Connect the Linear MCP app from **Configure Linear MCP**. The native channel transports the conversation but does not add issue-management tools. |
| Authorization reports missing scopes | Reconnect from nanobot. Do not reuse an authorization URL that omits `read`, `write`, `app:mentionable`, or `app:assignable`. |

For Linear's platform-side behavior, see the official
[Agents guide](https://linear.app/developers/agents),
[OAuth app manifest reference](https://linear.app/developers/oauth-app-manifests),
[OAuth guide](https://linear.app/developers/oauth-2-0-authentication), and
[webhook reference](https://linear.app/developers/webhooks).
