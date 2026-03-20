# Runbook: LLM Cost Overrun Response

**Severity**: High
**Owner**: On-call engineer
**Last reviewed**: 2026-03-20

---

## Symptoms

- LLM API spend exceeds expected daily/weekly budget
- Unexpected spike visible in provider billing dashboard (Anthropic / OpenAI / etc.)
- `nanobot_llm_calls_total` or `nanobot_llm_latency_seconds` Prometheus metrics show
  anomalous volume or duration
- `BudgetExceededError` raised in logs (when per-session cost guardrails are enabled)

---

## Immediate Actions (< 15 min)

1. **Check active sessions** — identify which sessions are driving cost:

   ```bash
   # Search for high-token completions in recent logs
   grep -i "total_tokens\|prompt_tokens\|usage" ~/.nanobot/logs/nanobot.log | tail -100
   ```

2. **Stop runaway sessions** — if a specific session is the culprit:

   ```bash
   nanobot agent stop --session <session_id>
   ```

3. **Temporarily lower model tier** — switch expensive sessions to a cheaper model in
   `~/.nanobot/config.json`:

   ```json
   {
     "provider": {
       "default_model": "claude-haiku-4-5-20251001"
     }
   }
   ```

4. **Check for stuck tool loops** — a `ToolCallTracker` loop-detection log entry indicates
   a tool call cycle that may be burning tokens:

   ```bash
   grep "tool_call_loop\|ToolCallTracker" ~/.nanobot/logs/nanobot.log | tail -20
   ```

---

## Investigation (15–60 min)

### Identify the cost driver

| Signal | Location | What to look for |
|--------|----------|-----------------|
| Per-session token totals | Provider billing dashboard | Sessions using 10× normal tokens |
| Model used | `nanobot.log` (`model=` field) | Unexpectedly using large/expensive model |
| Delegation depth | `routing_trace.jsonl` | Deeply nested delegations (depth > 3) |
| Memory consolidation | `nanobot.log` | Consolidation running too frequently |
| Skill/mission usage | `nanobot.log` | Background missions looping |

### Check routing traces

```bash
# Inspect recent routing decisions
tail -50 ~/.nanobot/routing_trace.jsonl | python3 -m json.tool | grep -E "role|depth|latency"
```

### Check delegation depth

Excessive nesting can multiply LLM calls geometrically. Normal max depth is 3; anything
higher is a potential runaway:

```bash
grep '"depth"' ~/.nanobot/routing_trace.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    if d.get('depth', 0) > 3:
        print(d)
"
```

---

## Mitigation Options

### Option A — Per-session cost cap (preferred)

Set `max_session_cost_usd` in `AgentConfig` to hard-limit spend per session.
When the cap is reached, the agent raises `BudgetExceededError` and returns a graceful
message to the user instead of continuing.

```json
{
  "agent": {
    "max_session_cost_usd": 0.50
  }
}
```

### Option B — Model downgrade

Route all traffic to a cheaper model until the incident is resolved:

```json
{
  "provider": {
    "default_model": "claude-haiku-4-5-20251001",
    "classifier_model": "claude-haiku-4-5-20251001"
  }
}
```

### Option C — Disable background missions

If a background mission is the culprit:

```bash
nanobot mission list
nanobot mission cancel <mission_id>
```

### Option D — Disable expensive skills

Remove or rename a skill directory to prevent it loading:

```bash
mv nanobot/skills/expensive-skill/ nanobot/skills/_disabled_expensive-skill/
```

---

## Recovery

1. Confirm spend has returned to baseline in provider dashboard (allow 5–10 min lag).
2. Re-enable any temporarily disabled features.
3. Update `max_session_cost_usd` if not already set — see Option A above.
4. File a post-mortem if the overrun exceeded 2× expected daily budget.

---

## Post-Mortem Template

```markdown
## Cost Overrun Incident — <DATE>

**Duration**: <start> → <end>
**Estimated overspend**: $<amount>
**Root cause**: <one sentence>

### Timeline
- HH:MM — first anomalous signal
- HH:MM — incident acknowledged
- HH:MM — mitigation applied
- HH:MM — spend returned to baseline

### Root Cause Analysis
<detailed explanation>

### Prevention
- [ ] <specific action to prevent recurrence>
- [ ] <config change / code fix / monitoring improvement>
```

---

## Related

- `docs/adr/ADR-007` — provider cost observability strategy
- `nanobot/providers/litellm.py` — LiteLLM provider (cost tracking integration point)
- `nanobot/config/schema.py` — `AgentConfig.max_session_cost_usd` field
- Prometheus dashboard: `nanobot_llm_calls_total`, `nanobot_llm_latency_seconds`
