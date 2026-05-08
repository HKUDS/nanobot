# CRM Opportunity Intelligence Design

Change id: `crm-opportunity-intelligence`

## Context

The existing CRM remains the source of record. This change adds an analysis layer that reads CRM data, computes deterministic metrics, and asks the LLM to summarize those facts into daily reports, weekly reports, and opportunity dashboard summaries.

The first version prioritizes safety, traceability, and delivery through existing Nanobot surfaces: CLI for development validation, DingTalk for daily usage, and Docker for deployment.

## Design Principles

- Read-only CRM boundary.
- Deterministic metrics before LLM narrative.
- Evidence traces for key business conclusions.
- No real CRM data in `.dek`, test fixtures, logs, Claude-Mem, or long-term memory.
- Minimal first-version scope.
- Avoid CRM-specific changes to generic Nanobot core unless an existing extension seam is insufficient.

## Components

### CRM Read Adapter

Responsible for reading allowed CRM entities and returning scoped data for report generation.

Preferred boundary: an external or separately isolated read-only adapter, such as an MCP server, because Nanobot already supports MCP tool registration and allow-listing.

Responsibilities:

- Expose only read operations required by v1.
- Prevent access to CRM write, task creation, assignment, delete, or customer-contact operations.
- Return stable source references for evidence trace generation.
- Avoid logging raw CRM payloads.

### Deterministic Metrics Layer

Responsible for all numeric computation and business metric derivation.

Responsibilities:

- Filter by requested date/window/scope.
- Compute counts, totals, distributions, stage movements, and status summaries required by v1.
- Produce metric records with names, values, input scope, and evidence references.
- Return missing-input errors when metrics cannot be computed.

The LLM never performs this layer's responsibilities.

### Report Builder

Responsible for assembling report inputs and final output shape.

Responsibilities:

- Select report type: daily, weekly, or dashboard summary.
- Combine deterministic metrics, source references, and prompt-safe summary inputs.
- Ask the LLM for narrative only after metric computation.
- Attach evidence trace records to key conclusions.
- Provide structured fallback output if LLM summarization fails.

### CLI Entry

Responsible for development validation.

The CLI path can be either:

- Existing `nanobot agent -m ...` with configured CRM adapter and report instructions.
- A dedicated first-class CLI command if a structured developer command is required.

The first version should prefer the existing CLI path unless a dedicated command materially improves verification.

### DingTalk Entry

Responsible for daily usage.

DingTalk should use existing Nanobot message delivery rather than CRM-specific transport changes. Report generation should produce content and send it through existing DingTalk channel routing.

V1 may support manual trigger, scheduled delivery, or both, depending on unresolved product decisions. It must not introduce customer contact, CRM task creation, or CRM writeback.

### Docker Delivery

Responsible for deployment using existing Docker workflow.

If CRM access is externalized through MCP or another adapter, Docker/Compose may need an additional service or configuration wiring. Secrets must remain runtime configuration, not image contents.

## Data Flow

1. User or schedule triggers report generation from CLI or DingTalk.
2. Report request defines report type, date/window, and scope.
3. CRM read adapter reads only allowed CRM data for the requested scope.
4. Deterministic metrics layer computes all numbers and trace records.
5. Report builder sends only precomputed metrics, bounded source references, and formatting instructions to the LLM.
6. LLM returns narrative summary without computing numbers.
7. Report builder combines narrative, deterministic metrics, and evidence traces.
8. Output is returned to CLI or delivered to DingTalk.
9. No real CRM data is written to `.dek`, fixtures, logs, Claude-Mem, or long-term memory.

## Evidence Trace Model

Each key conclusion should reference a trace record.

Trace records should include:

- Trace id.
- Report type.
- Report window and scope.
- Metric name.
- Metric value when applicable.
- Metric input source references.
- CRM entity type and stable source identifiers when available.
- Fields used for deterministic calculation.

Trace records should not include secrets or unnecessary raw customer details.

## Error Handling Design

- CRM unavailable: return explicit CRM read failure and do not ask LLM to fill gaps.
- Empty CRM data: return no-data report for the requested scope/window.
- Missing metric inputs: identify missing inputs and suppress unsupported conclusions.
- LLM failure: return deterministic metrics and evidence traces with a structured fallback.
- DingTalk failure: surface delivery failure; do not retry CRM writes because no writes exist in v1.
- Invalid trigger parameters: return parameter validation guidance without CRM access.

## Safety Design

- Use read-only credentials or read-only adapter capabilities.
- Do not expose CRM write operations to Nanobot in v1.
- Use synthetic data for tests.
- Redact or omit sensitive CRM fields not required by report scope.
- Do not log raw CRM payloads.
- Do not store real CRM data in `.dek` artifacts.
- Do not store real CRM data in Claude-Mem or long-term memory.
- Do not bake credentials into Docker images.

## Tradeoffs

### MCP Adapter vs Native Nanobot Tool

MCP adapter advantages:

- Clear process boundary for CRM access.
- Natural allow-listing of exposed tools.
- Less CRM-specific code in Nanobot core.
- Easier to keep CRM credentials outside the Nanobot package.

Native tool advantages:

- Simpler single-process runtime.
- Easier direct unit testing inside Nanobot.

Recommendation for v1: prefer MCP or an external read-only adapter unless deployment constraints require native tools.

### Dedicated CLI Command vs Existing Agent CLI

Existing agent CLI advantages:

- No new CLI surface required.
- Fits current Nanobot usage.

Dedicated CLI advantages:

- More repeatable developer verification commands.
- Easier automation in tests or scripts.

Recommendation for v1: start with existing CLI unless acceptance testing requires dedicated commands.

### DingTalk Command vs Scheduled Delivery

Manual trigger advantages:

- Lower scheduling ambiguity.
- Easier to validate first.

Scheduled delivery advantages:

- Better daily operating value.

Recommendation for v1: support the smallest DingTalk path that satisfies daily use after schedule and recipient rules are clarified.

## Verification Strategy

- Unit tests for deterministic metric generation using synthetic data.
- Unit tests for report assembly using synthetic metrics and trace records.
- Tests proving LLM input receives precomputed metrics rather than raw calculation responsibility.
- Tests for no-data, missing metric input, CRM unavailable, LLM failure, invalid trigger, and DingTalk delivery failure behavior.
- CLI verification using synthetic or mocked CRM data.
- DingTalk delivery/routing tests using mocks or existing channel test patterns.
- Docker/Compose verification only if delivery configuration changes.

## Remaining Design Questions

- Which read-only CRM interface will be used?
- What exact CRM entity and field contract is allowed in v1?
- What fixed report templates should daily, weekly, and dashboard outputs follow?
- What evidence trace granularity is required?
- Which DingTalk interaction mode is in v1: scheduled push, manual command, private query, or a subset?
- What report schedule and timezone should be used?
- What memory isolation setting or policy should prevent CRM-derived content from becoming long-term memory?
