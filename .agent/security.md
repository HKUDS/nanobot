# Security Boundaries

The agent operates with significant power (file system, shell, web). The following guards must not be bypassed when modifying related code.

## Workspace Restriction

Filesystem tools (`read_file`, `write_file`, `edit_file`, `list_dir`) resolve paths through `_resolve_path` (`agent/tools/filesystem.py`), which enforces that the resolved path must lie under `allowed_dir` (typically the configured workspace), plus the media upload directory (`get_media_dir()`) and any `extra_allowed_dirs`.

Shell execution (`ExecTool`, `agent/tools/shell.py`) also respects `restrict_to_workspace`: if enabled and `working_dir` is outside the workspace, the command is rejected before execution.

**Rule**: Any new path-handling logic must go through `_resolve_path` or perform an equivalent `allowed_dir` check.

## SSRF Protection

All outbound HTTP requests from agent tools must pass through `validate_url_target` (`security/network.py`). By default it blocks RFC1918 private addresses, link-local ranges, and cloud metadata endpoints (including `169.254.169.254`).

The only escape hatch is `configure_ssrf_whitelist(cidrs)`, which reads from `config.tools.ssrf_whitelist` at load time.

**Rule**: Do not add direct `httpx.get` / `requests.get` calls in tools. Route through the existing web fetch utilities or replicate the `validate_url_target` check.

## Shell Sandbox

`tools/sandbox.py` provides optional command wrapping. The only backend currently shipped is `bwrap` (bubblewrap), intended for containerized deployments. On Windows and bare-metal Linux without `bwrap`, commands run in the native shell with workspace restriction as the only guard.

**Rule**: If adding a new sandbox backend, implement `_wrap_<name>(command, workspace, cwd) -> str` and register it in `_BACKENDS`.
