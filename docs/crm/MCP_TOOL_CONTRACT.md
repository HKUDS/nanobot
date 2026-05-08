# CRM MCP Tool Contract

This document defines the first-version MCP tool contract for CRM opportunity intelligence. It does not implement the tools.

## Contract Principles

- Tools are read-only.
- Tools return sanitized data only.
- Tools do not expose raw GraphQL payloads.
- Tools do not expose CRM credentials, endpoint auth headers, or runtime config.
- Tools return deterministic values or unavailable markers; the LLM must not infer missing metrics.
- Tools include evidence/source references for key business facts.
- Tools reject invalid date/window/scope before CRM access.
- Tools reject write-like actions by design; no write-like tool names exist in v1.

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

`ToolError.message` must be selected from a server-owned safe message table. It must not include raw GraphQL error text, endpoint values, tokens, cookies, request headers, variables, raw responses, customer details, project details, contact details, amount-like values, or free-text CRM notes.

### Diagnostics Safety

Diagnostics objects are allow-list only. Tools may include only the fields explicitly documented for that tool.

Allowed diagnostic fields across v1 tools are:

- `read_only`
- `mutations_allowed`
- `mutation_used`
- `operation_name`
- `status`
- `reason`
- `http_status_category`
- `graphql_errors_count`
- `data_count`
- `records_returned`
- `normalized_count`
- `pages_read`
- `max_records`
- `pagination_limit_reached`

Diagnostics must not include endpoint values, tokens, Authorization headers, cookies, raw query text, raw variables, raw GraphQL responses, customer names, project names, contact details, amount-like values, or free-text CRM notes.

## V1 Tools

### `crm_generate_daily_report_facts`

Purpose: read CRM source data for one business date and return daily report facts for Nanobot report assembly.

Input:

| Field | Type | Required |
| --- | --- | --- |
| `window` | `ReportWindow` | Yes |
| `scope` | `ReportScope` | Yes |
| `options` | `ReadOptions` | No |

Output:

| Field | Type | Notes |
| --- | --- | --- |
| `report_type` | string | Always `daily`. |
| `window` | `ReportWindow` | Echoes validated window. |
| `scope` | `ReportScope` | Sanitized scope. |
| `metrics` | `MetricRecord[]` | Deterministic daily metrics. |
| `unavailable_metrics` | `UnavailableMetric[]` | Metrics that could not be computed. |
| `source_refs` | `SourceRef[]` | Sanitized source references. |
| `errors` | `ToolError[]` | Empty on success. |

### `crm_generate_weekly_report_facts`

Purpose: read CRM source data for a week/date range and return weekly report facts for Nanobot report assembly.

Input and output match `crm_generate_daily_report_facts`, except `report_type` is `weekly` and weekly metrics may include movement, stage distribution, stalled/high-risk, and won/lost markers only when deterministic inputs exist.

### `crm_generate_dashboard_facts`

Purpose: read CRM source data for a cross-sales scope and return dashboard summary facts.

Input and output match the shared report-facts shape, except `report_type` is `dashboard` and metrics focus on included sales scope, pipeline status, opportunity stage/status, risk/stagnation, and notable movements.

### `crm_list_projects`

Purpose: read allow-listed `listProject` data and return sanitized minimal project records for report facts and evidence traces. Current implementation tasks use mocked GraphQL responses only.

Input:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `window.start` | ISO date string | Yes | Validated before transport. |
| `window.end` | ISO date string | Yes | Must be greater than or equal to `window.start`. |
| `scope.scope_id` | string | Yes | Logical scope label. |
| `scope.owner_ids` | string array | No | Stable owner ids only. |
| `scope.group_ids` | string array | No | Stable group ids only. |
| `options.max_records` | integer | No | Must be positive and no greater than the server cap. |

Output:

| Field | Type | Notes |
| --- | --- | --- |
| `records` | object array | Sanitized project records only. |
| `source_refs` | `SourceRef[]` | Sanitized source references. |
| `errors` | `ToolError[]` | Sanitized categories only. |
| `diagnostics` | object | Read-only, pagination, and status counters only. |

Allowed record fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Stable project source id. |
| `stage` | string | Sanitized stage/status value. |
| `owner.id` | string | Stable owner id. |
| `owner.name` | string | Owner display name only. |
| `created_at` | string | Timestamp from allow-listed selection set. |
| `updated_at` | string | Timestamp from allow-listed selection set. |
| `source_ref_ids` | string array | References into `source_refs`. |

Diagnostics fields are restricted to `read_only`, `mutations_allowed`, `mutation_used`, `operation_name`, `graphql_errors_count`, `records_returned`, `pages_read`, `max_records`, `pagination_limit_reached`, `status`, and `reason`.

Forbidden output for `crm_list_projects` includes project names, customer names, amount-like fields, phone, email, contact, address, notes/free text, raw CRM fields outside the allowed record shape, endpoint values, tokens, Authorization headers, cookies, and raw GraphQL request or response payloads.

### `crm_list_business_chances`

Purpose: read allow-listed `list_business_chance` data and return sanitized minimal business chance records for report facts and evidence traces. Current implementation tasks use mocked GraphQL responses only.

Input:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `window.start` | ISO date string | Yes | Validated before transport. |
| `window.end` | ISO date string | Yes | Must be greater than or equal to `window.start`. |
| `scope.scope_id` | string | Yes | Logical scope label. |
| `scope.owner_ids` | string array | No | Stable owner ids only. |
| `scope.group_ids` | string array | No | Stable group ids only. |
| `options.max_records` | integer | No | Must be positive and no greater than the server cap. |

Output:

| Field | Type | Notes |
| --- | --- | --- |
| `records` | object array | Sanitized business chance records only. |
| `source_refs` | `SourceRef[]` | Sanitized source references. |
| `errors` | `ToolError[]` | Sanitized categories only. |
| `diagnostics` | object | Read-only, pagination, and status counters only. |

Allowed record fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Stable business chance source id. |
| `project_id` | string | Stable project id only when present; project name remains forbidden. |
| `status` | string | Sanitized business chance status. |
| `apply_status` | string | Sanitized review/application status. |
| `owner.id` | string | Stable owner id. |
| `owner.name` | string | Owner display name only. |
| `due_at` | string | Due timestamp from allow-listed response data. |
| `created_at` | string | Timestamp from allow-listed response data. |
| `updated_at` | string | Timestamp from allow-listed response data. |
| `source_ref_ids` | string array | References into `source_refs`. |

Diagnostics fields are restricted to `read_only`, `mutations_allowed`, `mutation_used`, `operation_name`, `graphql_errors_count`, `records_returned`, `pages_read`, `max_records`, `pagination_limit_reached`, `status`, and `reason`.

Forbidden output for `crm_list_business_chances` includes project names, customer names, amount-like fields, phone, email, contact, address, notes/free text, raw CRM fields outside the allowed record shape, endpoint values, tokens, Authorization headers, cookies, and raw GraphQL request or response payloads.

### `crm_check_read_boundary`

Purpose: verify that the MCP server is configured for read-only operation without exposing sensitive runtime values.

Input:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `include_allowed_operations` | boolean | No | Defaults to `true`; returns operation names only. |

Output:

| Field | Type | Notes |
| --- | --- | --- |
| `read_only` | boolean | Must be `true` for healthy v1 config. |
| `mutations_allowed` | boolean | Must be `false`. |
| `allowed_operations` | string array | Query names only, no variables or auth data. |
| `runtime_enabled` | boolean | Whether real CRM access is enabled in this process. |
| `errors` | `ToolError[]` | Sanitized categories only. |

### `crm_smoke_check`

Purpose: run a read-only diagnostic path for the future real CRM smoke check without exposing runtime values or raw CRM payloads. During current implementation tasks this tool uses mocked transport only.

Input:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `operation_name` | string | No | Defaults to an allow-listed Query such as `listProject`; operation names only, no raw query text. |

Output is restricted to these fields only:

| Field | Type | Notes |
| --- | --- | --- |
| `status` | string | Sanitized status such as `OK`, `INCONCLUSIVE`, or `ERROR`. |
| `read_only` | boolean | Must be `true`. |
| `mutations_allowed` | boolean | Must be `false`. |
| `runtime_enabled` | boolean | Whether smoke runtime is enabled; default is `false`. |
| `allowed_operations` | string array | Query names only, no variables or auth data. |
| `operation_name` | string | Allow-listed Query name used for the smoke path. |
| `mutation_used` | boolean | Must be `false`. |
| `http_status_category` | string | Sanitized category such as `not_attempted`, `success`, `unauthorized_or_forbidden`, `crm_unavailable`, or `rate_limited`. |
| `graphql_errors_count` | integer | Count only, no GraphQL error text or extensions. |
| `data_count` | integer | Count only, no records. |
| `normalized_count` | integer | Count only, no normalized record content. |
| `reason` | string | Sanitized reason such as `config_missing`, `empty_result`, `ok`, `graphql_error`, or `unauthorized_or_forbidden`. |
| `errors` | `ToolError[]` | Sanitized categories only. |

Forbidden output:

- Endpoint values.
- Tokens, cookies, credentials, or Authorization headers.
- Raw GraphQL requests or responses.
- Customer names, project names, amounts, contact details, phone numbers, email addresses, or free-text CRM notes.

## Explicitly Forbidden Tools

Do not add v1 tools with names or behavior involving:

- `create`
- `update`
- `delete`
- `remove`
- `assign`
- `claim`
- `transfer`
- `review`
- `audit`
- `sync`
- `send`
- `contact`
- `message`
- `task`
- `export`
- `writeback`

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
- `internal_error`

Errors must use the fixed `ToolError` shape: `category`, `message`, and `retryable`. Error messages must be safe static text and must not contain credentials, auth headers, raw GraphQL payloads, customer details, project details, contact details, amount-like values, free text, or full request variables.

No tool output may contain raw GraphQL requests, raw GraphQL responses, endpoint values, tokens, cookies, Authorization headers, project names, customer names, amount-like values, phone numbers, email addresses, contact details, physical addresses, or free-text CRM notes.

## Open Questions

1. Should report facts include normalized records for Nanobot-side metrics, or should the MCP server compute all real-CRM metrics before returning?
2. Should the read-boundary check tool be available in production or only in diagnostics mode?
3. Which tool names should be exposed to the model after Nanobot MCP wrapping prefixes are applied?
