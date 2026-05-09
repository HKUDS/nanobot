# CRM GraphQL Contract

This document is the canonical CRM GraphQL contract for read-first sources plus the single confirmation-gated report write path exposed by the future CRM MCP Server.

It supersedes `docs/crm-graphql-contract.md`. The old file is kept temporarily for migration review.

This is documentation-only. It does not implement a GraphQL client, MCP server, Nanobot adapter, DingTalk integration, or real CRM smoke test.

## Boundary

The GraphQL contract belongs behind the CRM MCP Server boundary.

Nanobot should not call the CRM GraphQL API directly for production real CRM access. Nanobot should call approved CRM MCP tools: read tools for CRM sources plus the explicit confirmation-gated `createReport` path, with no arbitrary writeback or raw GraphQL passthrough.

Runtime endpoint and authentication details are deployment configuration. They must not be committed, logged, written to `.dek`, included in tests, or pasted into documentation.

## Transport Shape

The source CRM GraphQL API is expected to use an HTTP POST payload with:

- `query`
- `operationName`
- `variables`

The canonical docs intentionally do not include auth header examples.

## V1 Query Allow-List

Only these `Query` operations are allowed for v1. All other queries are denied until added to this document and covered by tests.

| Query | Purpose | Return Type |
| --- | --- | --- |
| `listReport` | Read daily/weekly reports for a user or window | `ReportConnection!` |
| `reportInfo` | Read one report by id | `Report` |
| `reportRelatedInfo` | Read deterministic CRM context related to a report date/creator/type | `ReportRelatedInfo!` |
| `listProject` | Read project/opportunity pipeline records | `ProjectConnection!` |
| `listProjectID` | Read visible project ids for scope estimation | `[String!]!` |
| `projectInfo` | Read one project/opportunity detail | `Project!` |
| `listActivity` | Read activity records for timeline/context metrics | `ActivityConnection!` |
| `listCompany` | Read customer/company records | `CompanyConnection!` |
| `companyInfo` | Read one company detail | `Company!` |
| `listUser` | Resolve users and sales owners | `UserConnection!` |
| `list_leads` | Read current user's leads with `list_type=claim_by` | `LeadsConnection!` |
| `list_leads_pool` | Read lead pool records with `list_type=leads` | `LeadsConnection!` |
| `list_opportunity_scenario` | Read scenario-map records | `OpportunityScenarioConnection!` |
| `listImmediatelySignProject` | Read pending-sign project records when present | `[ImmediatelySignProject!]!` |
| `list_business_chance` | Read partner business chances | `BusinessChanceConnection!` |
| `business_chance` | Read one partner business chance detail | `BusinessChance` |

## Confirmation-Gated Write Allow-List

V1 allows exactly one mutation, `createReport`, and only through `crm_create_report_after_confirmation` after explicit user confirmation. `updateReport` and all other mutations remain forbidden.

## Forbidden Mutation Policy

The CRM schema exposes a `Mutation` root. V1 CRM opportunity intelligence is read-first, with exactly one confirmation-gated mutation: `createReport` for `crm_create_report_after_confirmation`.

Rules:

- Do not send GraphQL operations whose operation type is `mutation` unless the operation name is exactly `createReport` and the MCP tool path has explicit confirmation.
- Do not include other `Mutation` fields in allow-lists, generated clients, fixtures, tests, examples, docs, or runtime configuration.
- Do not expose MCP tools that create, update, delete, remove, assign, claim, transfer, review, audit, sync, send, contact, message, task, export, or otherwise mutate CRM state except `crm_create_report_after_confirmation`.
- Reject any non-allow-listed operation before transport execution.
- Tests for MCP server GraphQL work must assert non-allow-listed mutation operation strings are rejected without a network call.
- Any additional writeback or mutation path requires a separate change proposal and cannot be added under this v1 contract.

## Query To Normalized Model Mapping

The existing Nanobot normalized model starts from `OpportunityRecord`, `ReportRequest`, `ReportWindow`, `ReportScope`, `MetricRecord`, `UnavailableMetricRecord`, `EvidenceTrace`, and `ReportOutput`.

The CRM MCP Server may use equivalent internal DTOs, but its public MCP outputs should remain report-oriented and sanitized. Raw GraphQL payloads must not cross the MCP boundary.

| GraphQL Source | Normalized Use | Initial Field Mapping |
| --- | --- | --- |
| `Project` from `listProject` / `projectInfo` | Primary project/opportunity source for pipeline metrics | `id` -> source id, `name` -> title, `stage` -> stage, `claimBy.user.id` or sales owner field -> owner id, amount candidate fields -> amount candidate, created timestamp -> created timestamp, updated timestamp -> updated timestamp, close-date candidates -> expected or actual close date candidates |
| `BusinessChance` from `list_business_chance` / `business_chance` | Partner business chance source when project records do not yet exist | `id` -> source id, `project_name` -> title, `claim_by.id` -> owner id, `status` -> status, `apply_status` -> review status, `due_at` -> expected close date, created timestamp -> created timestamp, updated timestamp -> updated timestamp, product chance prices -> amount candidates only after deterministic parsing rules exist |
| `Report` from `listReport` / `reportInfo` | Input context for daily/weekly report consistency, not authoritative metric math | `id` -> source id, `type` -> report type, `target` -> report date, `creator.id` -> owner/user id, `content` -> redactable narrative context, `related_info` -> linked entities |
| `ReportRelatedInfo` | Link report windows to projects, companies, business chances, and delivery context | Use contained entity ids only as references unless fields are explicitly normalized by later tasks |
| `Activity` from `listActivity` | Activity counts/timeline metrics after model extension | `type`, `domain`, `creator.id`, created timestamp, updated timestamp, and related metadata if explicitly allow-listed |
| `Company` from `listCompany` / `companyInfo` | Customer/company dimension for grouping and traceability | `id`, `name`, `rank`, `claim_by.id`, `claim_by_group.id`, created timestamp, updated timestamp; contact, phone, address, attachment, and sandbox details are sensitive and must be excluded unless explicitly required |
| `User` from `listUser` | Owner display and scope resolution | `id`, `username`, `name`, `enabled`; avatar and unrelated role/group details are not needed for v1 report math |

Amount normalization remains a follow-up decision. The MCP server must define deterministic parsing rules before exposing amount-based metrics from real GraphQL responses.

## SearchParam To ReportRequest Mapping

`ReportRequest` has `report_type`, `window.start`, `window.end`, and `scope`. GraphQL variables should be built deterministically from that request.

| ReportRequest Field | GraphQL SearchParam Mapping |
| --- | --- |
| `report_type=daily` | `ReportSearchParam.type` for daily report lookups; `reportRelatedInfo.type`; project/activity/company/business-chance queries remain filtered by window and owner/scope only unless a report-specific field exists |
| `report_type=weekly` | `ReportSearchParam.type` for weekly report lookups; `ReportSearchParam.start` and `ReportSearchParam.end` cover the week |
| `window.start`, `window.end` | `ReportSearchParam.start/end`; project date filtering is unresolved; `ActivitySearchParam.start/end`; business chance created timestamp; company created timestamp only for company creation metrics |
| `scope.scope_id` | Internal report scope label; not sent directly unless mapped to explicit owner or group ids |
| `scope.owner_ids` | `ReportSearchParam.creator`, project owner fields, activity creator or related user, business chance sales owner, company owner, or `UserSearchParam.id` |
| `scope.group_ids` | Project, business chance, or company group fields after authoritative field choice is approved |

Open semantic choices:

- Which project date field defines daily and weekly pipeline inclusion.
- Which owner field is authoritative for sales scope.
- Whether partner business chances merge into the same opportunity model or remain a separate source category.

## Connection Pagination Rules

The schema uses connection objects with `total`, `skip`, `limit`, and `data` fields. Pagination input uses `skip` and `limit`.

Rules:

- First request starts with `skip=0`.
- Default page size should be conservative until CRM rate limits are confirmed.
- Continue while `skip + len(data) < total` and `data` is non-empty.
- Stop immediately if a page returns no `data` to avoid infinite loops.
- Enforce a maximum page count or maximum record count in MCP server runtime config.
- Preserve per-record source references across pages.
- Do not perform concurrent pagination against the real endpoint until rate-limit behavior is confirmed.

## Source Reference Rules

Every normalized record and metric must be traceable to source data without copying raw payloads.

Source reference shape:

- `system`: logical source system, for example `crm-graphql`.
- `endpoint`: logical endpoint name only; do not include credentials, auth headers, hostnames that are not approved for documentation, or request headers.
- `query`: allow-listed query name, for example `listProject`.
- `entity_type`: GraphQL object type, for example `Project`, `BusinessChance`, `Report`, `Activity`, `Company`, or `User`.
- `source_id`: stable GraphQL id field from the object.
- `fields`: normalized field names used by deterministic metrics.
- `window`: report window used to fetch the record when applicable.
- `page`: pagination metadata with `skip` and `limit` when the record came from a connection.

Evidence traces should reference normalized source reference ids and metric formula names, not raw GraphQL payloads.

## Redaction Rules

Do not write raw CRM payloads to `.dek`, docs, logs, errors, tests, report output, or memory. Redaction applies before errors are surfaced.

Always redact or omit:

- Credentials, tokens, cookies, API keys, secrets, and webhook or robot URLs.
- Request headers and authentication variables.
- Contact phone numbers, email addresses, physical addresses, attachment URLs, and free-text fields unless explicitly needed and sanitized.
- GraphQL variables that contain personal identifiers beyond stable ids needed for traceability.
- Schema examples that contain credentials, secrets, webhooks, robot URLs, or real business data.

Allowed in docs/evidence:

- Query names, type names, field names, and logical endpoint names.
- Synthetic ids and synthetic report output from mock-mode tests.
- Sanitized status categories and counts.

## MCP Server Runtime Config

Runtime config must be explicit and disabled by default.

Config rules:

- Do not read `.env.nanobot` in docs tasks or tests.
- Do not bake CRM config into Docker images.
- Do not log configuration values that may include credentials, endpoint auth headers, cookies, or raw CRM variables.
- MCP server startup should fail closed when real CRM access is disabled or required runtime config is absent.
- Tests must use mocked transport and synthetic GraphQL responses.
- Nanobot should receive only MCP tool outputs, not CRM GraphQL configuration.

## Open Questions

1. Which runtime authentication mechanism should the MCP server use internally?
2. Which project date field defines inclusion in daily and weekly pipeline metrics?
3. Which owner field is authoritative for sales scope?
4. What is the exact JSON shape of amount-like fields in real responses?
5. Should `BusinessChance` merge into the same normalized opportunity stream or remain a separate source category?
6. Which free-text fields, if any, are allowed in AI-readable summaries after redaction?
7. What page size and rate limits are safe for production CRM reads?
8. Should optional real CRM smoke tests run only behind explicit runtime flags and never in default CI?
