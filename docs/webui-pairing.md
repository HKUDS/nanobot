# WebUI pairing notifications

The gateway sends `{"event":"pairing_changed"}` through the existing authenticated WebUI WebSocket audience. The event contains no codes, sender identities, snapshots, or secrets; the existing pairing HTTP endpoint and approval/denial validation remain authoritative. Other WebSocket clients do not receive it.

The gateway observes the pairing store's parent directory with a native non-recursive watch, including first creation and atomic replacement by another process. It reads pairing deadlines through the store owner and notifies when pending requests expire. It does not observe configuration, usage, automations, or remote-connection health. Watch registration precedes opening the WebUI listener; interrupted watches re-register and reconcile missed pairing changes. Shutdown joins the watch and deadline tasks and any outstanding store reads.

The WebUI subscribes before its initial read, then re-reads on pairing notifications, foreground return, and WebSocket reconnect. Reads are serialized and coalesced; hiding or unmounting cancels obsolete reads, and stale responses cannot overwrite the current view. Automatic failures have bounded retries. Notifications are transient: recovery reads the current snapshot rather than replaying events. The countdown uses the received remaining lifetime so browser/server clock skew does not reset or extend it.

WebUI and Gateway are used as a paired release. Watched storage must support native notifications; unusual or network-mounted filesystems require deployment validation. Other pages retain their existing refresh behavior. This contract does not change channel delivery, authorization, or pairing persistence semantics.
