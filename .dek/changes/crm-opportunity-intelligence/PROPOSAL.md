# CRM Opportunity Intelligence Proposal

Change id: `crm-opportunity-intelligence`

## Summary

Build a first-version AI analysis layer on top of the existing self-developed CRM. The system reads CRM data, derives deterministic metrics, and uses the LLM only to summarize and express sales daily reports, sales weekly reports, and cross-sales opportunity dashboard summaries.

This change does not replace CRM and does not write back to CRM.

## Problem

Sales daily reports, sales weekly reports, and cross-sales opportunity summaries currently require manual collection and formatting. This creates repeated work, inconsistent metric definitions, and management overhead.

The team needs an AI-assisted layer that turns existing CRM data into useful reports without making the LLM responsible for arithmetic or business-critical metric calculation.

## Goals

- Generate sales daily reports from CRM data.
- Generate sales weekly reports from CRM data.
- Generate cross-sales pipeline and opportunity dashboard summaries.
- Support CLI as the development verification entry point.
- Support DingTalk as the daily usage entry point.
- Deliver through the existing Docker deployment model.
- Ensure every key business conclusion can be traced back to CRM data or deterministic metrics.
- Keep CRM access read-only in the first version.

## Non-Goals

- Do not write back to CRM.
- Do not automatically create CRM tasks.
- Do not automatically assign work to sales users.
- Do not automatically contact customers.
- Do not build a replacement CRM.
- Do not build complex BI dashboards or ad hoc analytics tooling.
- Do not build a complex permission system in v1.
- Do not store real CRM business data in `.dek`, logs, test fixtures, Claude-Mem, or long-term memory.
- Do not use the LLM for numeric calculation, sorting, grouping, metric computation, or source-of-truth business logic.

## Proposed Change

Add a bounded CRM opportunity intelligence workflow with these capabilities:

- Read-only CRM data access boundary.
- Deterministic metric generation for report inputs.
- LLM summarization over precomputed metrics and source references.
- Report output formats for daily report, weekly report, and opportunity dashboard summary.
- CLI trigger path for development validation.
- DingTalk trigger or delivery path for daily usage.
- Evidence trace metadata attached to key business conclusions.
- Safety and redaction rules for outputs and development artifacts.

## Success Criteria

- Synthetic CRM data can produce daily report, weekly report, and dashboard summary outputs.
- All numeric values in reports come from deterministic metrics, not LLM-generated calculations.
- Key conclusions include evidence traces to metric outputs or CRM source references.
- CLI can trigger report generation for development validation.
- DingTalk can trigger or receive report outputs for daily usage.
- CRM read boundary is demonstrably read-only.
- No real CRM data, tokens, secrets, or customer data are written into `.dek`, logs, fixtures, or memory.

## Risks

- CRM-derived data may leak into Nanobot memory or logs if not explicitly controlled.
- LLM output may overstate conclusions if prompts do not constrain it to supplied metrics and evidence.
- DingTalk may expose data to the wrong audience if destination and redaction rules are unclear.
- Open questions remain around exact CRM interface, report structure, evidence granularity, and schedules.

## Open Questions

- What CRM read-only interface will v1 use?
- Which CRM entities and fields are allowed in v1?
- What fixed output templates are required for daily, weekly, and dashboard outputs?
- What evidence trace granularity is required: metric-level, opportunity-level, record-level, or CRM-link-level?
- Should DingTalk support scheduled push, manual command trigger, private query, or a smaller v1 subset?
- What timezone and schedule should daily and weekly reports use?
