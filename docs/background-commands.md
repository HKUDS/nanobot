# Background command output

The WebUI's **Commands** panel appears above the composer when the current chat has
commands managed by the existing yielded `exec` / `write_stdin` workflow. Expand a
command to inspect its output, working directory, elapsed time, state and exit code.
This is not a new terminal, scheduler or shell: it does not accept input, launch
commands, or add execution permissions. One-shot commands and child-agent commands
owned by a separate execution manager are not included.

The panel reads a separate, non-consuming stdout/stderr tail, so opening it never
consumes output intended for the agent or extends a command's idle lifetime.
Each tail retains at most 100,000 Unicode characters and 512 chunks. Truncation is
explicit; stream ordering is observation order, not a promise of original cross-pipe
write order. The visible panel refreshes every three seconds while the page is visible.
Scrolling up pauses auto-scroll; **Follow output** resumes it. Output is plain text,
not HTML or executable terminal escape sequences. Copying is an explicit user action.

**Stop command** asks for confirmation, then stops only that command's process tree
using the existing cross-platform cleanup path. Sibling commands and the chat's agent
turn are not stopped. Repeating a stop is safe; the agent can still collect its final
output and termination status. A failed stop is shown as a failure, not success.
Existing execution timeouts and idle cleanup policies are unchanged.

Up to 32 completed commands remain available for 30 minutes after their final agent
poll or idle cleanup, with timer-based expiry even if no UI reads occur. Commands that
have exited but whose final output the agent has not yet collected remain in the
existing bounded active-session pool. Elapsed times are approximate until exit is
observed. A gateway restart clears all of these in-memory records.

The list/read/stop WebSocket actions require an authenticated WebUI connection, a live
or saved chat, and an execution owned by that exact chat. Temporary chats additionally
require their owning connection. Snapshots bypass mutation replay caches, are never
written to transcripts or browser storage, and cannot be fetched after a temporary
chat closes. Existing owner cleanup clears retained logs; shutdown clears all logs.
This does not claim secure memory erasure or remove logs produced by external tools.

Older gateways without command observation simply do not show this panel. If a
connection fails after data has loaded, the panel preserves the displayed tail but
marks live statuses unknown and disables stopping until a fresh read succeeds.
The shared project-terminal work is a separate capability; this panel currently
observes only the existing exec-session manager, not a PTY terminal backend.
