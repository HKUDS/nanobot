# CRM Opportunity Intelligence Specification

Change id: `crm-opportunity-intelligence`

## Requirements

### 1. Sales Daily Report Generation

The system MUST generate a sales daily report from CRM data for a caller-provided business date.

If the caller does not provide a business date, the system MUST either use an explicitly configured default business date/window or return a validation error; it MUST NOT ask the LLM to choose the date/window.

The daily report MUST include only values produced by deterministic metrics or direct CRM source fields.

The LLM MAY summarize the daily report and improve wording, and MAY mention risks only when risk labels or risk metrics are present in deterministic metrics or explicit CRM fields. It MUST NOT compute counts, totals, rankings, percentages, stage distributions, or other numeric values.

The daily report MUST include these fixed sections:

- Reporting date or window.
- Scope of included CRM data.
- Deterministic metrics produced by the v1 metric set for the report scope.
- Key opportunity changes or risks only when derived from deterministic metrics or explicit CRM fields included in the v1 CRM data contract.
- Evidence trace entries for key conclusions.

If a v1 metric is unavailable because its required CRM fields are not present, the report MUST mark that metric as unavailable and identify the missing inputs instead of omitting it silently or asking the LLM to infer it.

Acceptance criteria:

- Given synthetic CRM data for one reporting date, the system produces a daily report.
- Every number in the daily report is present in deterministic metric output or directly copied from CRM source data.
- Every key business conclusion has an evidence trace.
- If no CRM records match the date/window, the report states that no matching data was found instead of inventing activity.
- If no business date/window is supplied and no configured default exists, report generation returns a validation error before CRM read or LLM summarization.

### 2. Sales Weekly Report Generation

The system MUST generate a sales weekly report from CRM data for a caller-provided business week or date range.

If the caller does not provide a business week/date range, the system MUST either use an explicitly configured default weekly window or return a validation error; it MUST NOT ask the LLM to choose the week/date range.

The weekly report MUST use deterministic metrics for all numeric and comparative statements.

The LLM MAY summarize trends, risks, and management-facing narrative using only supplied metric outputs and evidence traces. It MUST NOT label an opportunity as high-risk, stalled, progressed, won, lost, or otherwise changed unless that label is present in deterministic metrics or explicit CRM fields.

The weekly report MUST include these fixed sections:

- Reporting week or date range.
- Scope of included CRM data.
- Pipeline movement summary from deterministic metrics, or an unavailable marker with missing inputs.
- Opportunity stage distribution from deterministic metrics, or an unavailable marker with missing inputs.
- Stalled or high-risk opportunity summary from deterministic metrics, or an unavailable marker with missing inputs.
- Won/lost or closed opportunity summary from deterministic metrics, or an unavailable marker with missing inputs.
- Evidence trace entries for key conclusions.

Acceptance criteria:

- Given synthetic CRM data for one reporting week, the system produces a weekly report.
- Numeric comparisons and trend statements are based on deterministic metrics.
- The report does not claim week-over-week or trend behavior unless deterministic metrics provide that comparison.
- Every key business conclusion has an evidence trace.
- If no business week/date range is supplied and no configured default exists, report generation returns a validation error before CRM read or LLM summarization.

### 3. Opportunity Dashboard Summary

The system MUST generate a cross-sales opportunity dashboard summary from CRM data.

The dashboard summary MUST aggregate pipeline and opportunity state through deterministic metrics.

The LLM MAY explain the dashboard, summarize risks, and produce readable management narrative using only supplied metrics and evidence traces. It MUST NOT create rankings, drill-down groupings, forecasts, risk labels, or priority labels unless those outputs are present in deterministic metrics or explicit CRM fields.

The dashboard summary MUST include these fixed sections:

- Included sales scope.
- Pipeline status summary.
- Opportunity stage/status summary.
- Risk or stagnation summary from deterministic metrics, or an unavailable marker with missing inputs.
- Notable opportunity movements from deterministic metrics or explicit CRM fields, or an unavailable marker with missing inputs.
- Evidence trace entries for key conclusions.

Acceptance criteria:

- Given synthetic CRM data across multiple sales users, the system produces a dashboard summary.
- Cross-sales aggregation values come from deterministic metrics.
- The summary includes only the fixed sections listed in this requirement and does not expose ad hoc filters, interactive drill-downs, forecasts, or custom BI query functionality.
- Every key business conclusion has an evidence trace.

### 4. CLI Trigger Behavior

The system MUST provide a CLI-accessible path to generate or validate each first-version output type:

- Sales daily report.
- Sales weekly report.
- Opportunity dashboard summary.

The CLI path MAY be a dedicated command or may use the existing Nanobot agent CLI with configured CRM tools and instructions, but it MUST return deterministic exit status, sanitized terminal output, and enough report/evidence content for automated tests or manual developer verification.

CLI verification MUST be able to run with synthetic or mocked CRM data and without CRM secrets.

Acceptance criteria:

- A developer can trigger daily report generation through CLI using non-secret configuration and synthetic or mocked CRM data.
- A developer can trigger weekly report generation through CLI using non-secret configuration and synthetic or mocked CRM data.
- A developer can trigger opportunity dashboard summary generation through CLI using non-secret configuration and synthetic or mocked CRM data.
- CLI output for test/verification mode does not log or persist real CRM business data in `.dek`, fixtures, or development logs.

### 5. DingTalk Trigger Behavior

The system MUST support DingTalk as a daily usage entry point for first-version reports.

DingTalk support in v1 MUST be limited to receiving or manually requesting the three first-version report outputs: daily report, weekly report, and opportunity dashboard summary.

Scheduled DingTalk delivery MAY be included only if it sends those same report outputs and does not add CRM mutation, task creation, customer contact, approval workflow, interactive CRM operations, or ad hoc analytics behavior.

V1 MUST avoid CRM-specific changes to DingTalk transport behavior unless generic DingTalk capability is missing.

DingTalk output MUST follow the same deterministic metric and evidence trace constraints as CLI output.

Acceptance criteria:

- A configured DingTalk destination can receive or manually request a daily report, weekly report, or dashboard summary using synthetic or mocked CRM data in test mode.
- DingTalk output does not include data outside the configured report scope.
- DingTalk output includes trace ids inline or provides a report-local evidence trace section for every key conclusion.
- DingTalk behavior does not create CRM tasks, contact customers, or write back to CRM.
- DingTalk behavior does not expose CRM mutation controls, approval actions, customer-contact actions, or ad hoc BI query controls.

### 6. CRM Data Read Boundary

The system MUST access CRM in read-only mode for v1.

The system MUST NOT call or expose CRM operations that create, update, delete, assign, message, contact, or otherwise mutate CRM state.

CRM access MUST be constrained to the minimum data needed for daily report, weekly report, and dashboard summary generation.

The v1 CRM data contract MUST name the allowed read entities, allowed read fields, and required fields for each deterministic metric before implementation or test fixture creation.

Acceptance criteria:

- The CRM adapter or integration surface exposes only read operations in v1.
- Tests or configuration review can demonstrate that write, task-creation, assignment, and customer-contact operations are absent or disabled.
- Report generation can proceed using synthetic CRM data without any CRM write capability.
- The v1 CRM data contract can be reviewed to confirm that each allowed field is used by at least one report section, deterministic metric, or evidence trace.

### 7. LLM Usage Boundary

The LLM MUST NOT be responsible for numeric calculation, aggregation, sorting, filtering, ranking, date-window selection, metric availability decisions, risk classification, stage classification, or source-of-truth business logic.

The LLM MAY be used for:

- Summarizing deterministic metric outputs.
- Rewriting factual metric-backed statements into readable language.
- Highlighting risks or observations only when grounded in supplied metrics or CRM source references.
- Formatting report narrative.

The LLM MUST NOT invent missing metrics, unsupported trends, unsupported causes, or actions not present in supplied evidence.

The LLM input MUST distinguish deterministic metric values, direct CRM source fields, unavailable metrics, and evidence trace ids so generated narrative can be checked against those inputs.

Acceptance criteria:

- Report prompts or generation flow provide precomputed metrics to the LLM.
- Numeric report values are generated before LLM summarization.
- Tests can verify that metric computation is deterministic and separate from LLM narrative generation.
- If required metrics are missing, the LLM output indicates missing data instead of fabricating values.
- Tests can use a stubbed LLM response to verify that report assembly rejects or flags narrative containing numeric values, labels, or claims not present in deterministic metrics, direct CRM source fields, unavailable metric markers, or evidence traces.

### 8. Evidence Trace Requirements

Every key business conclusion in daily, weekly, and dashboard outputs MUST be traceable to CRM data or deterministic metrics.

A key business conclusion is any generated statement that asserts opportunity count, amount, stage/status distribution, progression, stagnation, win/loss, risk, priority, owner/team scope, trend, comparison, or notable movement.

An evidence trace MUST identify at least one of:

- Metric name and metric value.
- Metric input date/window and scope.
- CRM source entity type and stable source reference.
- CRM source field names used by the metric.
- Deterministic calculation or grouping identifier.

Evidence traces MUST NOT include secrets, tokens, or unnecessary raw customer details.

Acceptance criteria:

- Each report has an evidence trace section or equivalent inline trace markers.
- Each key conclusion references a trace id or trace record.
- Trace records can be generated from synthetic CRM data.
- Trace records do not require storing real CRM data in `.dek`, logs, test fixtures, or Claude-Mem.
- Tests can identify key conclusion statements in deterministic report sections and confirm each one references an existing trace id or trace record.

### 9. Error Handling

The system MUST handle expected failure modes without fabricating reports.

Expected failure modes include:

- CRM read interface unavailable.
- CRM read returns empty data for the requested window.
- Required metrics cannot be computed from available data.
- LLM summarization fails.
- DingTalk delivery fails.
- Invalid CLI or DingTalk trigger parameters.

Behavior requirements:

- If CRM data cannot be read, the system MUST return an explicit read failure message.
- If no data matches the requested scope, the system MUST return a no-data report or no-data message.
- If deterministic metrics cannot be computed, the system MUST identify missing inputs and avoid LLM-generated substitute numbers.
- If LLM summarization fails, the system MUST return deterministic metrics or a structured fallback without invented narrative.
- If DingTalk delivery fails, the system MUST surface delivery failure without retrying unsafe CRM operations.

Errors MUST be represented as bounded status outputs with sanitized messages and stable error categories; they MUST NOT include raw CRM payloads, credentials, tokens, or full LLM prompts.

Acceptance criteria:

- Synthetic failure tests can cover CRM unavailable, empty data, missing metrics, LLM failure, DingTalk failure, and invalid trigger inputs.
- Error outputs do not expose secrets or raw CRM payloads.
- Error handling never writes to CRM.
- Each expected failure mode maps to a deterministic error category that can be asserted in tests.

### 10. Safety And Redaction Requirements

The system MUST avoid writing real business data, customer data, tokens, or secrets to `.dek`, logs, test fixtures, Claude-Mem, or long-term memory.

The system MUST use synthetic data or mocks for tests and fixtures.

The system MUST avoid baking secrets into Docker images.

The system MUST redact or omit sensitive fields not required for the report.

DingTalk outputs MUST stay within the configured reporting scope and recipient context.

Report generation MUST NOT persist raw CRM records, generated report content containing real CRM business data, or CRM-derived conversation history to Nanobot long-term memory or Claude-Mem.

Acceptance criteria:

- Test fixtures are synthetic and labeled as such.
- Logs and errors avoid raw CRM payload dumps.
- `.dek` artifacts contain requirements, plans, specs, and evidence about development only, not real CRM data.
- Docker image build inputs do not require embedding CRM secrets.
- Reports include only fields required by v1 report scope.
- Tests or configuration review can demonstrate that CRM-derived report generation disables or bypasses long-term memory persistence for raw CRM records and real CRM-derived report content.

## Out Of Scope For This Spec

- CRM writeback.
- Automatic CRM task creation.
- Automatic customer contact.
- Automatic sales assignment.
- Complex BI dashboards.
- Complex role/permission management.
- Model training or fine-tuning.
