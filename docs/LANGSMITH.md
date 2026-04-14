# LangSmith Integration

Nanobot can emit traces to [LangSmith](https://smith.langchain.com) for observability, debugging, and quality measurement.

## Setup

### Production (uv tool install)

Install from a published release with the `langsmith` extra:

```bash
uv tool install --reinstall "nanobot-ai[langsmith]"
```

To install from a specific branch (e.g. before a release):

```bash
uv tool install --reinstall \
  "git+https://github.com/pve/nanobot-ai.git@feature/langsmith-integration" \
  --with langsmith
```

Note: `--from` cannot be combined with extras (`[langsmith]`) — use `--with langsmith` instead, or use the PEP 440 `@` syntax in a single argument:

```bash
uv tool install --reinstall \
  "nanobot-ai[langsmith] @ git+https://github.com/pve/nanobot-ai.git@feature/langsmith-integration"
```

### Development (local checkout)

```bash
uv pip install -e '.[langsmith]'
# or with other extras
uv pip install -e '.[discord,langsmith]'
```

### Verify the right environment

`uv run python` and `uv tool install` use separate environments. To confirm tracing is active in the environment that actually runs `nanobot`:

```bash
$(dirname $(which nanobot))/python -c \
  "from nanobot.agent.runner import _LANGSMITH_ENABLED; print(_LANGSMITH_ENABLED)"
```

### Environment variables

```bash
LANGSMITH_API_KEY=ls__...
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=my-project          # optional, defaults to "default"
LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com  # optional, for EU region
```

If the API key and tracing flag are set but the package is not installed, nanobot logs a warning at startup and continues without tracing.

## What Gets Traced

Each conversation turn produces a trace tree with three named spans:

| Span | Type | What it covers |
|---|---|---|
| `agent_turn` | chain | The full turn: context build → LLM calls → tool execution → response |
| `tool_execution` | chain | All tool calls within one iteration, including their results |
| `memory_consolidation` | chain | Memory archival runs triggered at end of session |

LLM calls (`llm_call`) are captured automatically inside `agent_turn` via `wrap_openai` / `wrap_anthropic`. No additional instrumentation is needed per-provider.

## Metadata on Every Trace

Each trace carries:

| Field | Value | Use |
|---|---|---|
| `session_id` | session key (e.g. `discord:channel:thread`) | Group all turns in a conversation |
| `channel` | `discord`, `cron`, `cli`, etc. | Filter by deployment type |
| `chat_id` | platform-level thread/channel ID | Join with platform logs |
| `nanobot_version` | package version string | Compare behaviour across deploys |
| `prompt_hash` | 8-char SHA-256 of system prompt | Detect prompt drift between turns |

## Join Keys (Turn Linkage)

Each turn is assigned a UUID (`run_id`). The next turn in the same session sets `parent_run_id` to the previous turn's UUID. This creates a linked chain in LangSmith so you can trace a multi-turn conversation and see which response the user was reacting to.

## What You Can Do in LangSmith

**Debug failures** — when nanobot gives a wrong or empty response, open the trace and inspect:
- Which tool calls were made and what they returned
- Whether the LLM received the expected system prompt (check `prompt_hash` for drift)
- Latency per stage (context build vs LLM vs tool execution)

**Compare versions** — filter by `nanobot_version` metadata to compare response quality before and after a deploy.

**Spot prompt drift** — if `prompt_hash` changes unexpectedly mid-session, the system prompt changed (new memory, edited AGENTS.md, changed skills).

**Follow a conversation** — use `session_id` to pull all turns for one user session. Follow `parent_run_id` links to see the full chain in order.

**Measure latency** — `agent_turn` duration covers the full turn wall time. `tool_execution` and LLM call durations are separately visible, so you can see where time is spent.

## What Is Not Covered

- **User identity** — nanobot has no user model; `channel:chat_id` is the closest proxy.
- **Downstream outcomes** — whether the user actually accomplished their goal is outside nanobot's scope. Join keys capture retry chains within a session but not cross-session patterns.
- **Prompt versioning** — `prompt_hash` detects drift but does not explain what changed. Formal prompt management requires a separate registry.

## Verifying the Integration

```bash
# Check that tracing is active
$(dirname $(which nanobot))/python -c \
  "from nanobot.agent.runner import _LANGSMITH_ENABLED; print(_LANGSMITH_ENABLED)"
# Should print: True

# Run nanobot and send a message, then check smith.langchain.com
# Each turn should appear as an agent_turn trace with tool_execution children
```
