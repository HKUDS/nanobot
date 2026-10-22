# WebUI state invalidation

This contract covers pairing requests, channel settings/runtime status, automation lists, usage, and the local remote-instance directory. It reuses the existing authenticated WebSocket connection, per-connection outbound queues, and `NanobotClient` event dispatch. It is not a topic-subscription API, an execution ledger, or an incremental state replication protocol.

## Wire and audience

Hosts advertise the optional `webui.state-events.v1` capability without changing the WebUI core protocol floor. They send a transient notification after a relevant change:

```json
{"event":"webui_state_changed","resources":["pairing","automations"]}
```

The fixed resource names are `pairing`, `channels`, `automations`, `usage`, and `remote_instances`. Notifications contain no codes, credentials, configuration snapshots, or SSH paths. They invalidate a read projection; existing HTTP reads and mutation validation remain authoritative. Events are sent only to trusted WebUI connections. The `remote_instances` resource additionally uses the same loopback, local-browser, and Origin policy as its directory endpoint; it must not leak into public or reverse-proxied WebUI connections.

## Change sources and ownership

`WebUIStateEvents` is composed per gateway. It coalesces fixed invalidations and owns its file watches, clock deadlines, and runtime-status sampling for that gateway lifetime. It does not load or modify live automation state on behalf of the cron or trigger owner. Persistent writes from CLI or other processes remain observable through parent-directory watches, including atomic replacement and first creation. Pairing and usage paths come from their storage owners, not from an assumption that a custom config file shares the data directory.

State watches explicitly use native filesystem notifications: mtime-only polling can miss atomic replacement within one timestamp tick. Source registration completes before the WebSocket/WebUI listener is exposed; registration failure prevents that listener from starting instead of advertising a silently incomplete capability. Interrupted watches re-register and invalidate their affected resources. Remote directory and pairing-receipt files share this lifecycle rather than using a second watcher with different semantics. Native-notification support on unusual or network-mounted filesystems is a deployment requirement, not established by local tests.

Pairing changes include request creation, reply delivery, approval/rejection, and expiration. The observer schedules the next known expiration rather than repeatedly querying the pending-request endpoint. A dismissed popup's local snooze also ends on a local deadline without a network query. The visible remaining-time label follows the server deadline using a local timer, suspended while hidden and recomputed on return; duration-only legacy responses are anchored when received. Pairing authorization and code validation remain server-side.

Channel configuration changes invalidate the feature projection. Existing channel adapters do not all publish connection-state callbacks, so the gateway retains a shared lightweight runtime-status sample rather than repeatedly building the feature payload for each browser. This sampling is not a new state authority.

Automation changes include persisted jobs, actions, and run records, as well as WebUI mutations. The existing readers retain their action merging and active/dirty-store protections. The calendar and session panel consume the same resource notification but read their own appropriately scoped endpoints. The panel's local elapsed-time display does not require network requests.

Usage notification observes committed SQLite changes rather than token-stream or current-chat completion events. It also invalidates time-based aggregates on local date or configured timezone changes. Both the full settings response and the lightweight usage read include the grouping `timezone` inside the usage snapshot, so a mounted client does not interpret newly grouped dates with older settings metadata. Older hosts omit that field; clients then retain the settings timezone. The change source is read-only and must not turn every file event into an aggregate query or create a database merely to watch it.

`RemoteInstances` owns one shared health loop for its live connections. Directory GETs read the current directory and cached health without starting credential-bearing probes per browser tab. The manager retains bounded probe timeouts, identity/authentication/compatibility checks, transient-failure debouncing, and joined shutdown before releasing reserved listeners. Metadata writes also invalidate the directory. A state notification must never automatically reconnect a host or replace an iframe containing user work.

## Browser lifecycle

`NanobotClient.onStateChange(resource, callback)` registers a local callback and returns an unsubscribe function; it does not send a subscription frame. `useStateRefresh` registers before its initial read and owns one scheduler for both automatic and explicit refreshes, retaining one follow-up for requests received during an in-flight read. Explicit callers await the coalesced reads and receive their final error or lifecycle cancellation; automatic requests use a small bounded retry without a permanent idle error loop. Consumers guard state application with their lifetime signal or generation, and abort obsolete reads where supported. The remote directory uses this same entry point for manual refresh, online/pageshow recovery, and state notifications; its view layer retains metadata, frame health, and mutation/connection isolation, not a second read queue.

Visible active pages and expanded panels load on entry, matching notifications, focus/visible return, and reconnect. Hidden or unmounted consumers release their listeners and timers; reconnect reads the current snapshot rather than replaying old invalidations. These notifications are transient, so no durable delivery or offline event history is promised.

For hosts with a confirmed compatible WebUI core contract that do not advertise `webui.state-events.v1`, clients retain the legacy visible polling schedule. Missing or malformed core metadata leaves compatibility unconfirmed and cannot authorize mutations. Event-driven and legacy timers must not run simultaneously for a consumer. OAuth, QR authorization, update-job tracking, token renewal, and purely local UI timers retain their separate existing lifecycles.

## Verification boundaries

Protect notification-to-refresh behavior, idle request counts, invalidation during reads, stale response isolation, visible return, reconnect, old-host compatibility, persisted changes from another writer, expiration, and the remote local-only boundary. Transport enqueue success is not proof that a browser applied a state change. Fixture and mocked-network tests do not establish compatibility with every external chat service or SSH deployment.
