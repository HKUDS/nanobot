# WebUI state invalidation

Developer contract for refreshing pairing requests, channel status, automation lists, usage, and the local remote-instance directory.

## Event and access boundaries

Hosts advertise the optional `webui.state-events.v1` capability without changing the WebUI core protocol floor. Notifications reuse the authenticated WebSocket and its existing outbound queues:

```json
{"event":"webui_state_changed","resources":["pairing","automations"]}
```

`resources` contains names from the fixed set `pairing`, `channels`, `automations`, `usage`, and `remote_instances`. Notifications carry no snapshots or secrets; existing HTTP reads and mutation validation remain authoritative. Delivery is restricted to trusted WebUI connections. `remote_instances` additionally requires the directory endpoint's loopback, local-browser, and Origin policy; it is not sent to public or reverse-proxied connections.

Resource subscriptions are client-local; no subscription frame is sent. Notifications are transient. Clients recover missed changes by reading current snapshots, not by replaying events.

## Client refresh and compatibility

`useStateRefresh` subscribes before its initial read and owns one scheduler for automatic and explicit refreshes. Reads are serialized; requests during an in-flight read coalesce into one follow-up. Explicit callers await the coalesced reads and receive the final error or lifecycle cancellation. Automatic reads use bounded transient retries.

Active pages and expanded panels read on entry, matching notifications, focus, visible return, and reconnect. Hiding, unmounting, or changing scope releases the old listeners and timers and aborts obsolete reads; consumers must reject stale results. Remote-directory manual refresh and online/pageshow recovery use the same scheduler.

Hosts with a confirmed compatible WebUI core contract but without `webui.state-events.v1` retain legacy visible polling. Missing or malformed core metadata remains compatibility-unconfirmed and cannot authorize mutations. Event-driven and legacy timers must not run simultaneously. OAuth, QR authorization, update jobs, token renewal, and local UI timers retain independent lifecycles.

## Gateway ownership and lifecycle

Each gateway owns its file watches, deadlines, and shared runtime sampling; domain services retain state ownership. Use domain-owned storage paths and observe persisted changes from any writer, including first creation and atomic replacement, without reloading live automation owners. Mutations, expiration, committed usage, and local-date or timezone changes also invalidate their resources. Usage observation is read-only: it must not create a database or run aggregate queries for each filesystem signal. Usage snapshots include their grouping `timezone`; clients retain the settings timezone when older hosts omit it.

Native file watches must register before the WebSocket/WebUI listener opens. Registration failure prevents startup; interrupted watches re-register and invalidate affected resources. Watched storage must support native notifications, including on unusual or network-mounted filesystems. Shutdown joins owned change sources.

Remote health uses one shared sampler for live connections. Directory GETs read cached health instead of initiating probes. Preserve probe timeouts, identity/authentication/compatibility checks, and transient-failure debouncing. Notifications must not reconnect hosts or replace iframes containing user work. Shutdown joins in-flight health reads before releasing reserved listeners.
