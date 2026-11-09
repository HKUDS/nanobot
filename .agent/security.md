# Security Boundaries

Consult this document when changing path access, outbound HTTP/MCP, or shell execution. The agent operates with filesystem, shell, and network access; preserve the guards below on every affected path.

## Workspace Restriction

Filesystem tools and native file search use scoped operations in `nanobot/execution/files.py`. Those operations apply `nanobot/security/workspace_policy.py` to the effective request workspace before opening a file, listing a directory, or writing a patch. Edit activity snapshots use the same authorized write target, not a path from tool arguments. The media upload directory is an internal extra read root while restricted. These are application-level checks, not OS confinement against a process that can concurrently replace ancestor directories.

Additional filesystem roots must be capability-specific. `extra_allowed_dirs` is a legacy read-only alias. Use `extra_read_allowed_dirs` for read-only roots, `extra_write_allowed_dirs` only when a write-capable tool is intentionally allowed to modify an extra directory, and exact file allowlists when a tool may modify only specific files.

Shell execution (`ExecTool`, `agent/tools/shell.py`) also respects `restrict_to_workspace` as an application-level guard: if enabled and `working_dir` is outside the workspace, the command is rejected before execution, and command text is checked for obvious workspace escapes. This is not process-level isolation; use an exec sandbox backend for that.

**Rule**: File tool adapters should request a scoped file operation; do not add direct path authorization or filesystem effects in those adapters. When traversing a directory, authorize discovered file targets before reading them. Subprocess-backed search follows the shell rules below.

## SSRF Protection

All outbound HTTP requests from agent tools must pass through the shared URL guards in `security/network.py` (`validate_url_target` or `resolve_url_target`). By default they block loopback, RFC1918 private addresses, CGNAT ranges, link-local ranges, and cloud metadata endpoints (including `169.254.169.254`).

For direct requests, the only escape hatch is `configure_ssrf_whitelist(cidrs)`, which reads from `config.tools.ssrf_whitelist` at load time. The shared `network.proxy` address enabled by `providers.<name>.useProxy` is a separate user-authorized trust boundary for provider requests and provider-returned image URL downloads. Those downloads still reject malformed URLs and locally identifiable private/internal targets on every redirect, but hostnames unavailable to local DNS are delegated to the trusted proxy. The user-selected proxy owns final DNS resolution and network egress policy.

HTTP/SSE MCP transports are part of this boundary: validate configured MCP URLs before probing or constructing clients, and validate each outgoing HTTP request before redirects are followed. Local/private HTTP MCP endpoints are allowed only through the explicit SSRF whitelist. Stdio MCP servers are not part of the HTTP SSRF path.

**Rule**: Do not add direct `httpx.get` / `requests.get` calls in tools. Route through the existing web fetch utilities or replicate the `validate_url_target` check.

## Shell Sandbox

`execution/sandbox.py` builds the sandbox argument vector for both shell execution and the settings probe. `security/sandbox_launcher.py` resolves the trusted host launcher. Backends are `bwrap` (bubblewrap) on Linux and `seatbelt` (`sandbox-exec`) on macOS. Seatbelt must not expose shared host temporary directories; scratch stays in the workspace. On Windows a configured backend warns and leaves only the application guard. On Unix a configured backend that cannot start must fail, not silently execute without isolation.

**Rule**: If adding a sandbox backend, match the backend callable contract in `nanobot/execution/sandbox.py` and register it in `_BACKENDS`. Preserve read/write root handling and the configured backend's failure behavior.
