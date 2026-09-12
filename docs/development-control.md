# Development controls and Codex account limits

These are optional operator features. They do not replace the existing Evolution
evaluation and promotion policy. The complete rollout remains tracked in
[autonomous-agent-rollout.md](autonomous-agent-rollout.md).

## Development project

Enable `tools.development` with an absolute `repository`, a canonical
`ownerSessionKey` such as `telegram:123456789`, and fixed `checks` as command argv
lists. The repository must be clean before a new candidate is created. Initialize
the project through `DevelopmentStore.initialize` with its full requirements;
the store rejects implicit replacement with a smaller scope.

The `development` tool lets the configured owner read requirements, propose
bounded jobs with evidence and acceptance criteria, save checkpoints, and start,
pause or cancel work. WebUI exposes **Settings → Rozwój agenta**. In Main on
Telegram, WebUI or TUI:

```text
/development
/development continue
/development pause
/development start dev-JOB_ID
/development cancel dev-JOB_ID
```

`/rozwoj` is an alias. These commands operate on one durable project, independent
of the active client's conversation view. Notifications remain a read-only view.
The pause command is handled without waiting for the main agent turn. A running
isolated step finishes before the worker begins another step.

The worker captures a source baseline, freezes existing tests and configuration,
checks the baseline, then implements and verifies a candidate in a separate
directory. Linux bubblewrap is mandatory for executing candidate code: it has a
private network, process namespace and temporary directory, no host credentials,
and only explicitly configured read-only dependencies. `readOnlyDependencies`
can expose a test virtual environment; `sourceDependencies` can mount relative
`node_modules` directories. Tests must not rewrite source files; such a result is
invalidated. Existing tests cannot be changed by the candidate; new tests can be
added.

The builder uses the configured default model and provider, including Astra when
that is the selected preset. `builderProtocol` can be `auto`, `tools` or `json`.
Auto can switch to validated JSON actions when the provider explicitly rejects
function calling or returns a valid JSON action. Authentication and rate-limit
failures do not trigger that switch. Models still need enough context and output
quality to satisfy the same checks; the adapter does not make model capabilities
equivalent.

A fresh model conversation reviews the complete bounded patch and test evidence.
The worker permits one active change, at most two repair attempts, and reserves
daily model usage before each call. Unknown usage remains charged after a crash.
Checks, review and a content-addressed source artifact are stored separately from
the builder's notes. Interrupted work preserves its files and acceptance checks;
continuation inspects the saved phase instead of assuming success. A paused job
can resume verification without repeating completed edits.

**Current boundary:** `ready` means verified source awaiting deployment. The
production release/rollback adapter and autonomous backlog scheduler are still
part of the unfinished rollout. A ready artifact is not reported as deployed.
The full device-node workflow is also unfinished.

## Codex subscription quota

Enable `tools.codexLimits` with `enable: true`, `ownerSessionKey`, and optionally
an absolute `executable` path to the installed Codex CLI. `refreshSeconds` defaults
to 60. The CLI must already have a working account login; this monitor never logs
in, starts a model turn, consumes reset credits, or changes a subscription.

The monitor uses the official app-server initialization handshake followed by
`account/rateLimits/read`. It displays returned quota buckets, percentages,
window durations and reset timestamps. No fixed five-hour/weekly assumption is
made. The full view is in **Settings → Rozwój agenta**, a compact readout appears
in the chat sidebar and TUI model bar, and `/limits` or `/limity` returns a text
summary in the owner's Main chat.

Visible clients refresh every 30 seconds; the backend coalesces reads within the
configured refresh interval. Failed refreshes retain and label the previous
observation as stale. Missing windows remain unknown, not zero. Limits belong to
the Codex CLI account; when the provider returns an account ID, the monitor checks
whether it matches nanobot's existing Codex OAuth account. It stores a fingerprint
instead of the account ID and never persists tokens or raw account responses.

Subscription quota is independent of conversation token telemetry. See the
[official Codex app-server documentation](https://learn.chatgpt.com/docs/app-server)
for the account endpoint and field definitions.
