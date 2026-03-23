# Context Budget (`context_budget_tokens`)

Caps how many tokens of old session history are sent to the LLM during tool-loop iterations 2+. Reduces cost and first-token latency by trimming history between turns.

## How It Works

During multi-turn tool-use sessions, each iteration re-sends the full conversation history. `context_budget_tokens` limits how many old tokens are included:

- **Iteration 1** — always receives full context (no trimming)
- **Iteration 2+** — old history is trimmed to fit within the budget; current turn is never trimmed
- **Memory consolidation** — runs before/after the loop and always sees the full canonical history; trimming only affects the LLM's view

## Configuration

```json
{
  "agents": {
    "defaults": {
      "context_budget_tokens": 1000
    }
  }
}
```

| Value | Behavior |
|---|---|

---

`0` (default) | No trimming — full history sent every iteration
`4000` | Conservative — barely trims in practice; good for multi-step tasks
`1000` | Aggressive — significant savings; works well for typical linear tasks
`< 500` | Clamped to `500` minimum when positive (1–2 message pairs at typical token density)

## Trade-offs

**Cost & latency** — Trimming reduces tokens sent each iteration, which saves money and lowers first-token time (TTFT). This is nanobot's primary sweet spot.

**Context loss** — Older context is not visible to the LLM in later iterations. For tasks that genuinely require 20+ iterations of history to stay coherent, consider `0` or `4000`.

**Tool-result truncation** — Large results from a previous turn (e.g., reading a 10,000-line file in Round 1, then editing in Round 2) can be trimmed. The agent can re-read the file via its tools — this is a 1-tool-call recovery cost, not a failure.

**Prefix caching** — Some providers (e.g., DeepSeek) use implicit prefix-based caching. Aggressive trimming breaks prefix matching and can reduce cache hit rates. For these providers, `0` or a high value may be more cost-effective overall.

## When to Use

| Use case | Recommended value |
|---|---|
| Simple read → process → act chains | `1000` |
| Multi-step reasoning with tool chains | `4000` |
| Complex debugging / long task traces | `0` |
| Providers with implicit prefix caching | `0` or `4000` |
| Long file operations across turns | `0` or re-read via tools |

## Example

```
Turn 1: User asks to read a.py (10k lines)
Turn 2: User asks to edit line 100
```

With `context_budget_tokens=500`, the file-content result from Turn 1 may be trimmed before Turn 2. The agent will re-read the file to perform the edit — a 1-call recovery. This is normal behavior for the feature; it is not a bug.
