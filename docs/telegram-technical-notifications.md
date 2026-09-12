# Optional outbound-only Telegram technical notifications

This is a **disabled-by-default, lossy operational feed**, not a second agent or
conversation. No credentials or live configuration are installed by this feature.
The Telegram channel must itself be enabled and configured normally.

## Configuration

The exact default section is:

```json
{
  "channels": {
    "telegram": {
      "technical": {
        "enabled": false,
        "profileName": "Powiadomienia",
        "sharedInbox": false,
        "mainChatId": "",
        "chatId": "",
        "token": "",
        "includeToolEvents": true,
        "includeStatusEvents": true
      }
    }
  }
}
```

To enable it, set `technical.enabled` to `true` and supply a **dedicated** numeric
chat ID, such as `"-1001234567890"`. Keep the existing main Telegram token. An empty
technical token reuses that bot, **with a separate SDK client/connection pool**.
The same configured `channels.telegram.proxy` is used for both clients.

- With the **same bot**, only a negative group/channel ID is accepted. A separate
  group/channel avoids confusing the ordinary assistant DM with the technical feed.
- A **technical DM** (positive user ID) requires a **different bot token**, e.g.
  `technical.token: "${TELEGRAM_TECHNICAL_TOKEN}"`. The bot IDs (token prefixes)
  must differ; rotating a token for the same bot does not create a separate bot.
  The same person can use the ordinary DM with the main bot and a technical DM
  with the second bot. This is supported even though both DMs use the same user ID.
- Usernames, forum topic IDs, noncanonical IDs and unknown technical options are
  rejected. A technical group is reserved as a whole, **not just one topic**.
- Missing target/effective credentials are configuration errors. Invalid tokens,
  inaccessible chats and insufficient permissions produce a generic local warning,
  never an ordinary chat message or a dump of the exception/token.
- Environment variables must exist if referenced; `${VAR}` has no shell default
  syntax. Do not add an unset variable reference to an otherwise disabled feature.

The bot must already be allowed to send to the destination: add it to a dedicated
private group, grant channel posting rights, or first start the separate bot's DM.
Do not add the technical bot as another ordinary inbound channel. There is no
`getUpdates` polling or webhook receiver for that bot in this implementation.
Telegram retains any messages sent to it; this process never consumes them.

The nested fields are declared in the Telegram setup manifest, including secret
handling for `technical.token`, and validated in the channel-local Pydantic models.
Setup validation checks configuration but does **not** send a test notification or
probe technical chat membership. Enabling/reloading Telegram uses the existing
channel lifecycle; changing configuration does not itself restart this process.

## Main chat versus operational UI

While `technical.enabled` is true, the main Telegram adapter accepts final answers
and answer streaming, but suppresses progress/tool hints, reasoning, and typed
retry/compaction/recovery notices, even if global hint flags are true. This remains
true if the technical feed fails or either include flag is false: there is **no
fallback into the main chat**. Normal explicit command responses still work.

If the feed remains disabled but you still want a quiet main Telegram chat, use
existing per-channel options (not global options):

```json
{
  "channels": {
    "telegram": {
      "sendToolHints": false,
      "sendProgress": false,
      "showReasoning": false
    }
  }
}
```

Leave global/WebSocket settings unchanged to retain the WebUI's full operational
view. Disabling technical notifications otherwise restores existing Telegram
behavior. This does not remove the tool results required for the agent's own
execution context, or erase existing session history; **technical notifications
are never inserted into that context/history**.

## Isolation and privacy

- Real `ProgressEvent.tool_events` are observed before channel hint filtering;
  tool start/end/error payloads are projected to `Tool exec: start`, for example.
  Human-readable tool hints are never parsed or copied.
- Canonical local `SessionTurnStarted` / `TurnCompleted` events supply turn status.
  Routed compaction/retry/recovery events provide their corresponding short status.
  This is a gateway-wide feed of these events, including WebUI turns, not a raw
  log sink or a comprehensive audit trail. Unknown event types are ignored.
- Only a bounded tool name and a closed status vocabulary are sent. Arguments,
  results, reasoning, user/assistant text, paths, files, call/session/user IDs,
  model details, raw exception strings and credentials are not copied. An invalid
  or oversized tool name becomes `tool`; unknown status becomes `updated`.
- The queue contains only these already-redacted short strings. It does not retain
  original messages, event payloads or metadata. Tool names themselves can reveal
  which capabilities are in use; grant destination access accordingly.
- Inbound messages, slash commands, callback buttons and media from the technical
  group/channel are discarded **before** authorization, pairing, downloads or bus
  publication. This also applies if the technical group uses a separate bot but the
  main bot happens to be present. An ordinary outbound bus message to the reserved
  target is rejected too; only the dedicated sender writes there.
- The dedicated sender calls the Telegram SDK directly and never publishes to the
  inbound/outbound bus, writes session history, invokes tools or mirrors its own
  messages. Existing WebUI events are neither mutated nor removed.

## Delivery limits and failures

There is one worker and one bounded queue (64 strings). Up to 32 tool records from
one event are projected; additional records and newest messages beyond capacity
are dropped. Sending is no faster than one message every 3 seconds, silently
(`disable_notification=true`), with a 10-second operation timeout. Failed items
are dropped, not retried; subsequent delivery pauses at least 30 seconds and
honors a longer Telegram `RetryAfter`. Main channel dispatch never awaits this
network I/O and does not share its outbound SDK pool.

A technical SDK initialization failure disables the feed until the Telegram
channel is stopped/re-enabled or the gateway is next started; it does not fail the
main channel. There are fixed, secret-free local warnings for initialization and
first delivery failure. Internal `sent`, `failed`, and `dropped` counters describe
the current worker lifetime; these are not a persisted audit log or a new WebUI
status API. Stop cancels the worker, disconnects its subscription, discards pending
messages and shuts down the isolated client. No delivery is guaranteed or replayed
after a restart. A shared bot still shares Telegram's server-side bot limits, so a
separate bot is preferable for strong rate-limit isolation.

## Offline verification

Run from the repository with development dependencies and the optional
`python-telegram-bot` SDK installed in your **test** environment:

```sh
python -m pytest nanobot/channels/telegram/tests tests/channels -q
ruff check nanobot/channels/base.py nanobot/channels/manager.py nanobot/channels/telegram
basedpyright nanobot/channels/base.py nanobot/channels/manager.py nanobot/channels/telegram
```

`test_technical.py` mocks every SDK/network operation. It covers defaults and
validation, names/status-only projection, flag behavior, queue/per-event limits,
rate limiting, failed/stalled delivery, client/proxy isolation, disabled behavior,
ingress/egress isolation, separate-bot DMs, no bus recursion, and preservation of
WebUI events and ordinary final answers. No live send, real credentials, running
configuration changes or restart are required. A skipped Telegram test module
means the optional SDK is missing, not that isolation was verified.


## Named profile and shared two-stream inbox

Telegram's existing channel configuration form now exposes all `technical.*`
fields (including the masked optional token). `profileName` names the additional
outbound-only profile; its default is **Powiadomienia**. It does not create a
second polling bot or an LLM session. The ordinary Telegram bot remains the main
conversation profile.

Opt in to the shared inbox explicitly, using the main owner's **private numeric
Telegram user ID**, not a group ID. The shared inbox is independent of the optional
technical destination: `sharedInbox=true` works with `technical.enabled=false` and
an empty `technical.chatId`. Calendar, cron and explicit proactive messages sent
to the owner DM are recorded after confirmed delivery (including streamed answers).
Regular conversation answers and tool progress are not notification receipts.
For example, to enable both the shared inbox and an already configured technical group:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "allowFrom": ["123456789"],
      "technical": {
        "enabled": true,
        "profileName": "Powiadomienia",
        "chatId": "-1001234567890",
        "mainChatId": "123456789",
        "sharedInbox": true
      }
    }
  }
}
```

The main token and proxy stay in their existing settings. The shared-inbox owner
mapping is composed at gateway start; saving these fields does not silently
restart the gateway. Review the mapping and activate it on the next operator-
controlled start. Standalone technical sender settings still use the ordinary
Telegram channel lifecycle. No global configuration is changed automatically.

The WebUI pins **Powiadomienia** above **Czat główny**, ahead of ordinary chats,
independently of local archive, rename, sort and pin preferences. Shared rows
cannot be deleted or renamed. Existing sidebar new-activity indicators also work
for notification receipts. Powiadomienia has no composer: writes are rejected on
the server as well as hidden in the UI.

- **Czat główny** reads the existing `telegram:<mainChatId>` conversation directly.
  Owner Telegram messages and trusted WebUI `shared-main` turns both use that same
  canonical session. A final answer initiated in the WebUI is delivered once to
  the main Telegram DM, without another session-history write. Telegram-initiated
  answers are not sent again. No tool arguments, tool results, or hidden runtime
  context are copied into the read model.
- **Powiadomienia** reads at most 500 local delivery receipts. A receipt is written
  atomically only *after* Telegram confirms the corresponding sanitized message.
  Failed/dropped notifications do not appear as delivered. Stream receipts retain
  the full original notification text (including Markdown), independently of the
  current Telegram message buffer: one or multiple mid-stream overflows must not
  discard the already confirmed prefix or copy synthetic chunk-balancing fences.
  The receipt is committed only after the final edit and every remaining chunk
  succeeds; an incomplete/failed final delivery creates no success receipt.
  Repeated receipt IDs and duplicate completed `stream_end` events are idempotent.
  Stream delivery state is retired before receipt persistence, so a disk/callback
  failure never retries an already successful Telegram edit/send. A network failure
  in a final extra chunk does not trigger an additional plain-text fallback send;
  existing transport timeout/rate-limit retry policies remain unchanged.
  This feed is not an LLM `Session` and does not enter prompts or memory.
- With `mainChatId` set, notification sources are scoped to that owner DM; with
  `sharedInbox` enabled they also include the owner's shared main WebUI stream.
  Events from other Telegram users, groups, other WebUI chats, and other channels
  are not forwarded. Leaving `mainChatId` empty retains the legacy operator-wide
  operational feed, but cannot enable the shared inbox.

### Ownership boundary and legacy unified history

The embedded WebUI is **one authenticated operator trust domain**, not a
multi-user account system. Every trusted WebUI operator can see the same two
streams. Do not distribute its operator credentials to unrelated people.
Ordinary WebSocket client-audience tokens cannot attach to either reserved shared
chat. HTTP transcript/list access still requires the existing operator API token;
raw `telegram:*` and `unified:*` session keys remain inaccessible through HTTP.
Shared inbox configuration requires a singleton `allowFrom` matching the owner;
wildcards, pairing-only access, and multi-user lists are rejected.

This feature unifies exactly the configured owner Telegram DM and WebUI main pane;
it does **not** adopt `unified:default`, which may contain mixed-channel or other
users' legacy history. Such history is left untouched, not copied or erased.
While this feature is active, concrete channel/session overrides keep all other
chats out of the shared conversation, even when legacy global unified mode is on.
The shared main pane is a text conversation view, not a copy of full diagnostic
transcripts. Existing ordinary WebUI chats retain their full operational UI.

Receipts belong to both the configured owner and notification destination. Changing
either makes previous receipts unavailable to the new mapping. A hot-reloaded
Telegram configuration whose owner, destination, or notification bot identity no
longer matches the running inbox fails closed: shared views and receipt callbacks
are deactivated until the owner mapping is composed again on gateway start (even
if another hot reload restores the old settings). Notification bot identity is
only the public token prefix of the effective sender token:
`(technical.token or channels.telegram.token).split(":", 1)[0]`. An empty technical
token therefore tracks the main bot, while a separate technical token takes
precedence. Token rotation for the same bot is allowed; switching to another bot
is not. The inbox retains only that public identity, not either token, and writes
no credentials to receipts. This check also applies without a technical feed.
External messages sent directly by other bots/services are not scraped from Telegram: only this
gateway's confirmed notifications appear in this transcript. Media attachments are
not copied into the receipt store; the notification's text is retained. Existing
Telegram messages from before activation are not scraped or synthesized.
