# Review guide: independently updated WebUI clients and hosts

Apply this checklist to changes to WebUI HTTP, WebSocket events/mutations, bootstrap, capabilities, host switching, and persisted browser state. Read this alongside the design and security constraints, not instead of them.

## Compatibility is a contract, not a package-version comparison

- The local installation owns executable WebUI assets. A remote host supplies authenticated data, events, and media, never replacement JavaScript or CSS.
- Negotiate the WebUI protocol in `webui/client_contract.py`. The pre-existing terminal `protocolVersion` is a separate contract; do not overload it.
- Different package versions may use the same protocol. New hosts should keep the previously supported protocol when possible. Extra fields and unknown optional capabilities must not break older clients.
- Add optional features as named capabilities. Gate their controls and requests at their owning interface; do not require a server upgrade for unrelated features. Raise the core protocol floor only for an intentional breaking change with a documented support window and migration path.
- Missing/malformed metadata means **compatibility unconfirmed**, not “old server,” “bad SSH key,” or “network error.” Do not infer support from matching package versions. An unconfirmed core contract cannot authorize mutations.
- A package update being available is not proof of incompatibility. Optional update notices must use verified release data, be dismissible, and never interrupt an otherwise compatible session.

## Required proof for a changed contract

- Current client/current host, current client/oldest supported host, and oldest supported client/current host. State the supported protocol range explicitly; never claim every historical nanobot release is supported.
- Unknown, missing, malformed and future metadata; overlapping and disjoint protocol ranges; unknown optional capabilities; missing required capability.
- Assert the actual public bootstrap/read/mutation/event behavior, not only a version-comparison helper. Keep an older client/host fixture independent of the implementation under test. Test the affected optional feature's fallback.
- Reconnect after a host restart or upgrade. Previously issued credentials and stale cached compatibility must not bypass a changed host contract.
- Prove local HTML/JS/CSS are used even when remote static files are missing or different. Missing local assets fail locally, never fall back to remote code.
- HTTP reads, streamed messages, upload/download, cancellation, multiple tabs, and a response arriving after switching hosts remain scoped to their host.
- Preserve drafts/preferences without mixing authentication, model choices, conversation history, file paths, or command execution across host origins.

## Update UX and operator safety

- Report the local version, host version (or “not reported”), compatibility, and which machine needs updating. A newer host must not be told to downgrade when the client needs updating.
- Keep compatible version differences quiet. Show missing optional capabilities at the affected control. Block only unsupported core sessions or operations.
- Reuse the application's settings rows, menus and dialogs. Do not introduce a second settings drawer or a persistent global warning for an optional update.
- Explain that updating this computer does not update its hosts. Use the installation environment that owns the running process: installer/uv/pipx/pip, checkout, container, and service-managed deployments are not interchangeable.
- Never silently install, restart, downgrade, revoke credentials, or reset configuration. Back up configuration/data and consider active tasks before an explicitly requested update. Verify the running process after restart, not merely whichever `nanobot` executable happens to be on PATH.
- Update user documentation with the change. Do not present planned support or fixture-only tests as a completed real-server acceptance test.

## Current baseline

WebUI protocol **1** with capability **`webui.core.v1`** is the initial explicit client/host contract. It covers the existing authenticated WebUI read, mutation, event, and media interfaces. Hosts predating this declaration are unconfirmed; the local-client mode requires updating them to a build that declares support. Their independent server WebUI remains a separate way to use that installation. This is an intentional prerequisite for local-client mode, not a blanket claim that legacy nanobot installations no longer function.
