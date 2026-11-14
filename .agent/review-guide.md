# Review guide: WebUI clients and hosts

Apply this checklist to changes to WebUI HTTP, WebSocket events/mutations, bootstrap, capabilities, host switching, and persisted browser state. Read this alongside the design and security constraints, not instead of them.

## Compatibility and deployment

- WebUI/gateway support and test coverage are limited to same-version combinations, including remote hosts. Cross-version combinations may work but have no compatibility guarantee, even when protocol checks pass. Align versions first when troubleshooting; do not reject connections solely because package versions differ.
- The local installation owns executable WebUI assets. A remote host supplies authenticated data, events, and media, never replacement JavaScript or CSS.
- Declare the WebUI protocol in `webui/client_contract.py`. The pre-existing terminal `protocolVersion` is a separate contract; do not overload it.
- Use named capabilities for optional features and gate their controls and requests at their owning interface. Do not add compatibility fallbacks or negotiation solely to support older gateways.
- Missing/malformed metadata means **compatibility unconfirmed**, not “old server,” “bad SSH key,” or “network error.” A matching package version alone does not validate the contract. An unconfirmed core contract cannot authorize mutations.
- A package update being available is not proof of incompatibility. Optional update notices must use verified release data, be dismissible, and never interrupt an otherwise compatible session.

## Required proof for a changed contract

- Verify the current client with a same-version host. Cross-version compatibility fixtures or fallback behavior are not required.
- For changes to contract validation, test unknown, missing, malformed and future metadata; overlapping and disjoint protocol ranges; unknown optional capabilities; and missing required capability.
- Assert the actual public bootstrap/read/mutation/event behavior, not only a version-comparison helper.
- Reconnect after a host restart or upgrade. Previously issued credentials and stale cached compatibility must not bypass a changed host contract.
- Prove local HTML/JS/CSS are used even when remote static files are missing or different. Missing local assets fail locally, never fall back to remote code.
- HTTP reads, streamed messages, upload/download, cancellation, multiple tabs, and a response arriving after switching hosts remain scoped to their host.
- Preserve drafts/preferences without mixing authentication, model choices, conversation history, file paths, or command execution across host origins.

## Update UX and operator safety

- Report the local version, host version (or “not reported”), compatibility, and which machine needs updating without presenting a passing protocol check as a guarantee of cross-version functionality.
- Show missing optional capabilities at the affected control. Block unsupported core sessions or operations.
- Reuse the application's settings rows, menus and dialogs. Do not introduce a second settings drawer or a persistent global warning for an optional update.
- Explain that updating this computer does not update its hosts. Use the installation environment that owns the running process: installer/uv/pipx/pip, checkout, container, and service-managed deployments are not interchangeable.
- Never silently install, restart, downgrade, revoke credentials, or reset configuration. Back up configuration/data and consider active tasks before an explicitly requested update. Verify the running process after restart, not merely whichever `nanobot` executable happens to be on PATH.
- Update user documentation with the change. Do not present planned support or fixture-only tests as a completed real-server acceptance test.

## Current baseline

WebUI protocol **1** with capability **`webui.core.v1`** is the initial explicit client/host contract. It covers the existing authenticated WebUI read, mutation, event, and media interfaces. Hosts predating this declaration are unconfirmed; local-client mode requires a gateway that declares a supported protocol and the required capabilities. Their independent server WebUI remains a separate way to use that installation. This is an intentional prerequisite for local-client mode, not a blanket claim that legacy nanobot installations no longer function.
