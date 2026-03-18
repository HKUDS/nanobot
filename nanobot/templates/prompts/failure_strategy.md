Tool failure recovery — structured replanning.

When a tool fails, the agent receives a structured failure report that includes:

- **Failure classification**: permanent_config (missing API key or binary),
  permanent_auth (invalid credentials), transient_timeout (rate limit or network timeout),
  transient_error (server 500 or temporary failure), logical_error (wrong arguments),
  unknown.
- **Permanently removed tools**: tools classified as permanent failures are disabled
  for the rest of the session — do not retry them.
- **Available alternatives**: the remaining tools still available to use.

Recovery rules by failure class:
- `permanent_config` / `permanent_auth` → do not retry; choose an alternative tool.
- `transient_timeout` → retry with a shorter operation or different parameters.
- `logical_error` → fix the arguments before retrying.
- `transient_error` / `unknown` → try an alternative approach.

Always explain the failure and the alternative strategy chosen. If no alternative
exists, clearly state why the task cannot be completed with the available tools.
