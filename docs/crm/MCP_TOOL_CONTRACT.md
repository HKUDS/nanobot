# CRM MCP Tool Contract

This document defines the first-version MCP tool contract for CRM opportunity intelligence and CRM Report Assistant workflows. It does not implement the tools.

## Contract Principles

- Tools are read-only except `crm_create_report_after_confirmation`, which is confirmation-gated report creation metadata and must not run without explicit confirmation.
- Tools return sanitized data only.
- Tools do not expose raw GraphQL payloads.
- Tools do not expose CRM credentials, endpoint auth headers, or runtime config.
- Tools return deterministic values or unavailable markers; the LLM must not infer missing metrics.
- Tools include evidence/source references for key business facts.
- Tools reject invalid date/window/scope before CRM access.
- Tools reject unconfirmed write-like actions and raw unsafe write tools by design; the only v1 write-like tool name allowed is `crm_create_report_after_confirmation`.

## Shared Input Types

### `ReportWindow`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `start` | ISO date string | Yes | Inclusive business date/window start. |
| `end` | ISO date string | Yes | Inclusive business date/window end. |

### `ReportScope`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `scope_id` | string | Yes | Logical scope label, for example a synthetic or configured team scope. |
| `owner_ids` | string array | No | Stable owner ids if caller is allowed to scope by owner. |
| `group_ids` | string array | No | Stable group ids if caller is allowed to scope by group. |

### `ReadOptions`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `include_source_refs` | boolean | No | Defaults to `true`. Source refs are sanitized. |
| `max_records` | integer | No | Must not exceed server-side cap. |
| `include_unavailable_metrics` | boolean | No | Defaults to `true`. |

## Shared Output Types

### `MetricRecord`

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Stable metric name. |
| `value` | string, number, or object | Deterministically computed value. |
| `unit` | string | Optional unit such as count or currency. |
| `window` | `ReportWindow` | Input window used for metric. |
| `scope_id` | string | Scope used for metric. |
| `source_ref_ids` | string array | Sanitized source reference ids. |

### `UnavailableMetric`

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Stable metric name. |
| `missing_inputs` | string array | Field or semantic inputs that are unavailable. |
| `reason` | string | Sanitized reason. |

### `SourceRef`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Report-local or response-local reference id. |
| `system` | string | Logical source system, for example `crm-graphql`. |
| `query` | string | Allow-listed query name. |
| `entity_type` | string | GraphQL entity type. |
| `source_id` | string | Stable source id. |
| `fields` | string array | Normalized field names used. |

### `ToolError`

| Field | Type | Notes |
| --- | --- | --- |
| `category` | string | Stable sanitized category. |
| `message` | string | Fixed safe human-readable message for the category; never copied from raw CRM errors. |
| `retryable` | boolean | Whether retry may be useful. |

`ToolError.message` must be selected from a server-owned safe message table. It must not include raw GraphQL error text, endpoint values, tokens, cookies, request headers, variables, raw responses, contact details, amount-like values, or raw CRM free-text dumps.

## Information Policy

Always forbidden in tool output, diagnostics, errors, logs, docs, fixtures, and memory:

- token
- cookie
- Authorization header
- endpoint auth
- raw GraphQL query/variables/response
- raw error stacks
- export/attachment contents

Allowed internal business context in generated reports/tables:

- customer names
- project names
- lead titles/names
- scenario names
- activity/follow-up content
- sales owner names
- business text from CRM reports needed to draft daily/weekly reports

Cautious/default-redacted unless later approved:

- phone
- email
- address
- contact details
- amounts
- contract/revenue/payment/commission details
- large raw free-text dumps

### Diagnostics Safety

Diagnostics objects are allow-list only. Tools may include only the fields explicitly documented for that tool.

Allowed diagnostic fields across v1 tools are:

- `read_only`
- `mutations_allowed`
- `mutation_used`
- `operation_name`
- `status`
- `reason`
- `auth_mode`
- `endpoint_configured`
- `http_status_category`
- `graphql_errors_count`
- `data_count`
- `records_returned`
- `normalized_count`
- `pages_read`
- `max_records`
- `pagination_limit_reached`
- `runtime_enabled`
- `status_code_category`
- `token_configured`
- `transport_error_category`
- `source_counts`

Diagnostics must not include endpoint values, tokens, Authorization headers, cookies, raw query text, raw variables, raw GraphQL responses, contact details, amount-like values, or large raw free-text dumps.

## V1 Live Stdio Tools

The mock-mode stdio server publishes only the seven report-assistant tools documented below. Earlier helper/library capabilities such as `crm_generate_daily_report_facts`, `crm_generate_weekly_report_facts`, `crm_generate_dashboard_facts`, `crm_list_projects`, `crm_list_business_chances`, `crm_check_read_boundary`, and `crm_smoke_check` are not live stdio tools in this contract.

### `crm_collect_sales_daily_context`

Purpose: collect CRM context needed to draft one sales daily report for the current user or approved scope.

The tool may read allow-listed report, project, lead, activity, scenario, and pending-sign sources. Output may include internal business context allowed by the information policy, including customer names, project names, lead names/titles, scenario names, activity/follow-up content, sales owner names, and relevant prior report text.

It must not expose transport secrets, raw GraphQL payloads, raw error stacks, export/attachment contents, contact details, amount-like details, or large raw free-text dumps.

### `crm_collect_sales_weekly_context`

Purpose: collect CRM context needed to draft one sales weekly report for the current user or approved scope.

The tool follows the same information policy as `crm_collect_sales_daily_context`, with a weekly window and aggregation-friendly source references.

### `crm_collect_presales_weekly_context`

Purpose: collect CRM context needed to prepare a presales weekly table for an approved scope.

The tool may return internal business names and concise activity/scenario/report summaries needed for table generation, while redacting transport secrets, raw GraphQL payloads, contact details, sensitive amount/contract/payment/commission details, and large raw free-text dumps.

### `crm_generate_sales_daily_draft`

Purpose: generate a sales daily report draft from collected CRM context without writing to CRM.

Output includes fallback draft content and `requires_confirmation=true`. The draft may include allowed internal business context from the source context. To prepare writeback, call `crm_create_report_after_confirmation` with the draft and no confirmation text; that preflight returns the confirmation package tied to the same draft and must not include raw GraphQL payloads or transport secrets.

### `crm_generate_sales_weekly_draft`

Purpose: generate a sales weekly report draft from collected CRM context without writing to CRM.

Output includes fallback draft content and `requires_confirmation=true`. The draft may include allowed internal business context from the source context. To prepare writeback, call `crm_create_report_after_confirmation` with the draft and no confirmation text; that preflight returns the confirmation package tied to the same draft and must not include raw GraphQL payloads or transport secrets.

### `crm_generate_presales_weekly_table`

Purpose: generate a presales weekly table from collected CRM context without writing to CRM.

Output may include allowed internal business context needed for the table. It must not include transport secrets, raw GraphQL payloads, contact details, sensitive amount/contract/payment/commission details, export/attachment contents, or large raw free-text dumps.

### `crm_create_report_after_confirmation`

Purpose: create a CRM report only after the user explicitly confirms a generated draft.

The tool must not call `createReport` unless the caller provides an approved confirmation phrase and the confirmation package generated for the same draft. If confirmation text is missing or not approved, return `confirmation_required` and the fallback draft content. If the confirmation package is mismatched or tampered, return `confirmation_mismatch` and the fallback draft content.

Approved confirmation phrases for v1 are `确认提交这份日报` for daily reports and `确认提交这份周报` for weekly reports.

Successful output records sanitized status, reason, report id, report type, target, mutation name, mutation-used flag, and errors list. The only mutation name allowed is `createReport`.

## Explicitly Forbidden Tools

V1 allows exactly one write-like tool name: `crm_create_report_after_confirmation`.
It is confirmation-gated report creation only. Do not add unconfirmed writes,
destructive writes, raw GraphQL passthrough, or unsafe tools with names or behavior
involving `create`, `update`, `delete`, `remove`, `assign`, `claim`, `transfer`,
`review`, `audit`, `sync`, `send`, `contact`, `message`, `task`, `export`, or
`writeback`.

## Error Categories

Allowed error categories:

- `invalid_request`
- `config_missing`
- `crm_unavailable`
- `unauthorized_or_forbidden`
- `graphql_error`
- `pagination_limit_reached`
- `normalization_failed`
- `missing_required_fields`
- `empty_result`
- `rate_limited`
- `confirmation_required`
- `confirmation_mismatch`
- `write_permission_denied`
- `write_failed`
- `internal_error`

Errors must use the fixed `ToolError` shape: `category`, `message`, and `retryable`. Error messages must be safe static text and must not contain credentials, auth headers, raw GraphQL payloads, contact details, amount-like values, large raw free-text dumps, or full request variables.

No tool output may contain raw GraphQL requests, raw GraphQL responses, endpoint values, tokens, cookies, Authorization headers, amount-like values, phone numbers, email addresses, contact details, physical addresses, export/attachment contents, raw error stacks, or large raw free-text dumps.

## Open Questions

1. Should report facts include normalized records for Nanobot-side metrics, or should the MCP server compute all real-CRM metrics before returning?
2. Should the read-boundary check tool be available in production or only in diagnostics mode?
3. Which tool names should be exposed to the model after Nanobot MCP wrapping prefixes are applied?
