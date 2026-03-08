---
name: cost-report
description: "Analyze and report on LLM usage costs. Summarize spend by model, channel, task, or time period. Use when asked about costs, spending, budgets, or token usage — or when proactively reporting costs to Paperclip."
---

# Cost Reporting

Analyze and present LLM usage costs.

## Data Sources

Cost data comes from nanobot's cost tracking system (Phase 3). Each LLM call records a `CostEvent` with:
- `timestamp` — when the call was made
- `model` — which model was used
- `provider` — which provider served the request
- `input_tokens` / `output_tokens` — token counts
- `cost_usd` — calculated cost in USD
- `session_key` — which session/conversation
- `channel` — which channel originated the request
- `task_id` — associated task (if any)

## Report Types

### Summary by Period
When asked "how much did we spend today/this week/this month":
```
mcp_paperclip_report_cost(period="today", group_by="model")
```
Present as a table: model, calls, tokens, cost.

### Summary by Channel
When asked about per-channel spend:
- Group by channel, then by model within each channel
- Highlight which channels are most expensive

### Summary by Task
When asked about a specific task's cost:
- Show total cost, model breakdown, token counts
- Compare to average task cost if data is available

### Budget Check
When asked "are we within budget" or proactively checking:
- Compare current spend against configured budget limits
- Alert if spend exceeds 80% of budget for the period
- Report to Paperclip if over budget

## Presentation

- Always show costs in USD with 4 decimal places for small amounts, 2 for larger
- Include token counts alongside costs for context
- Use tables for multi-row data
- Include the time period covered
- Note any data gaps or estimation caveats

## Proactive Reporting

When configured, report costs to Paperclip on schedule:
```
mcp_paperclip_report_cost(
  period="daily",
  agent_id="<self>",
  total_usd=<amount>,
  breakdown={<model: cost>}
)
```
