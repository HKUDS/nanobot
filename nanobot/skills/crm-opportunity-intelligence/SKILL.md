# CRM Opportunity Intelligence

Use this skill when generating CRM opportunity intelligence reports through the future CRM MCP server or the mock CLI verification path.

## Scope

- Generate sales daily report output.
- Generate sales weekly report output.
- Generate opportunity dashboard summary output.
- Use synthetic or mocked data for development verification.
- Use a future MCP server for real CRM reads after the mock path is verified.

## Boundaries

- Use deterministic metrics for all counts, amounts, distributions, rankings, date windows, and risk/status labels.
- Use evidence traces for key business conclusions.
- The LLM may summarize, explain, and suggest wording only from supplied metrics and evidence traces.
- The LLM must not compute numbers or infer missing metrics.
- There is no CRM writeback in v1.
- Do not create CRM tasks, contact customers, assign sales work, or mutate CRM state.
- Do not store real CRM data, generated production reports, tokens, or secrets in `.dek`, logs, fixtures, Claude-Mem, or long-term memory.

## Integration Approach

- The selected path is MCP-first for agent usage.
- do not register a native built-in CRM tool in `nanobot/agent/loop.py` for this change.
- Do not add CRM report logic to DingTalk transport code.
- Use the existing CLI mock path for local verification until the MCP server is implemented.

## Usage Notes

- For development, prefer `nanobot crm report daily --adapter mock --date <YYYY-MM-DD> --scope synthetic-team`.
- Weekly and dashboard reports require explicit `--start` and `--end` dates.
- Real CRM access requires a separate read-only MCP server and runtime configuration.
