# Archived Superseded Reference

> Status: Superseded reference.
>
> This document is retained for migration review only. The canonical CRM GraphQL contract for the MCP-first route is `docs/crm/GRAPHQL_CONTRACT.md`. Do not use this file as the source of truth for new implementation work.

15K Option B status: archived-in-place superseded reference.

This file is retained only as a historical migration reference for the old direct Nanobot GraphQL / `RealCRMAdapter` route. It is not the production contract, not the MCP contract, and not an implementation guide for new work.

Do not use this file to add direct in-process CRM GraphQL access to Nanobot. Real CRM GraphQL access belongs behind the CRM MCP Server. Do not delete, move, or rename this file without explicit user approval.

# CRM GraphQL Read Contract

This document defines the v1 read-only GraphQL contract for CRM opportunity intelligence. It is derived from `/Users/yang/Desktop/CRM_schema.md` and is intentionally documentation-only: no real CRM endpoint access, adapter implementation, or DingTalk integration is included here.

## Endpoint

- GraphQL endpoint: `http://api.in.chaitin.net/crm/query`
- Transport: HTTP POST with a GraphQL `query`, `operationName`, and `variables` payload.
- Runtime authentication is configuration-only. Credentials must never be committed, logged, written to `.dek`, or included in tests.

## V1 Query Allow-List

Only these `Query` operations are allowed for v1. All other queries are denied until added to this document and covered by tests.

| Query | Purpose | Return Type |
| --- | --- | --- |
| `listReport` | Read daily/weekly reports for a user or window | `ReportConnection!` |
| `reportInfo` | Read one report by id | `Report` |
| `reportRelatedInfo` | Read deterministic CRM context related to a report date/creator/type | `ReportRelatedInfo!` |
| `listProject` | Read project/opportunity pipeline records | `ProjectConnection!` |
| `projectInfo` | Read one project/opportunity detail | `Project!` |
| `listActivity` | Read activity records for timeline/context metrics | `ActivityConnection!` |
| `listCompany` | Read customer/company records | `CompanyConnection!` |
| `companyInfo` | Read one company detail | `Company!` |
| `listUser` | Resolve users and sales owners | `UserConnection!` |
| `list_business_chance` | Read partner business chances | `BusinessChanceConnection!` |
| `business_chance` | Read one partner business chance detail | `BusinessChance` |

## Forbidden Mutation Policy

The CRM schema exposes a `Mutation` root and many mutation fields. V1 CRM opportunity intelligence is read-only, so mutation use is explicitly forbidden.

Rules:

- Do not send GraphQL operations whose operation type is `mutation`.
- Do not include `Mutation` fields in allow-lists, generated clients, fixtures, tests, examples, docs, or runtime configuration.
- Do not add methods named or shaped like `create`, `update`, `delete`, `remove`, `assign`, `claim`, `transfer`, `review`, `audit`, `sync`, `send`, `contact`, `message`, `task`, or `export` to the v1 adapter boundary.
- Reject any non-allow-listed operation before transport execution.
- Tests for real adapter work must assert that mutation operation strings are rejected without a network call.
- If future writeback is needed, it requires a separate change proposal and cannot be added under this v1 contract.

## Query To Normalized Model Mapping

The existing normalized model starts from `OpportunityRecord`, `ReportRequest`, `ReportWindow`, `ReportScope`, `MetricRecord`, `UnavailableMetricRecord`, `EvidenceTrace`, and `ReportOutput`. GraphQL-backed CRM reads should extend this model only where required by deterministic metrics.

| GraphQL Source | Normalized Use | Initial Field Mapping |
| --- | --- | --- |
| `Project` from `listProject` / `projectInfo` | Primary project/opportunity source for pipeline metrics | `id` -> source id, `name` -> title, `stage` -> stage, `claimBy.user.id` or sales owner field -> owner id, `amount` / `actual_amount` / `deal_amount` -> amount candidate, `created_at` -> created timestamp, `updated_at` -> updated timestamp, `estimated_deal_date` / `deal_date` / `sign_date` -> close-date candidates |
| `BusinessChance` from `list_business_chance` / `business_chance` | Partner business chance source when project records do not yet exist | `id` -> source id, `project_name` -> title, `claim_by.id` -> owner id, `status` -> status, `apply_status` -> review status, `due_at` -> expected close date, `created_at` -> created timestamp, `updated_at` -> updated timestamp, product chance prices -> amount candidates only after deterministic parsing rules exist |
| `Report` from `listReport` / `reportInfo` | Input context for daily/weekly report consistency, not authoritative metric math | `id` -> source id, `type` -> report type, `target` -> report date, `creator.id` -> owner/user id, `content` -> redactable narrative context, `related_info` -> linked entities |
| `ReportRelatedInfo` | Link report windows to projects, companies, business chances, and delivery context | Use contained entity ids only as references unless fields are explicitly normalized by later tasks |
| `Activity` from `listActivity` | Activity counts/timeline metrics after model extension | `type`, `domain`, `creator.id`, `created_at`, `updated_at`, and related metadata if explicitly allow-listed |
| `Company` from `listCompany` / `companyInfo` | Customer/company dimension for grouping and traceability | `id`, `name`, `rank`, `claim_by.id`, `claim_by_group.id`, `created_at`, `updated_at`; contact, phone, address, attachment, and sandbox details are sensitive and must be excluded unless explicitly required |
| `User` from `listUser` | Owner display and scope resolution | `id`, `username`, `name`, `enabled`; avatar and unrelated role/group details are not needed for v1 report math |

Amount normalization remains a follow-up task. The schema defines `Money` as a scalar, so 14B must define how mocked GraphQL responses represent money values before metrics consume them.

## SearchParam To ReportRequest Mapping

`ReportRequest` has `report_type`, `window.start`, `window.end`, and `scope`. GraphQL variables should be built deterministically from that request.

| ReportRequest Field | GraphQL SearchParam Mapping |
| --- | --- |
| `report_type=daily` | `ReportSearchParam.type` for daily report lookups; `reportRelatedInfo.type`; project/activity/company/business-chance queries remain filtered by window and owner/scope only unless a report-specific field exists |
| `report_type=weekly` | `ReportSearchParam.type` for weekly report lookups; `ReportSearchParam.start` and `ReportSearchParam.end` cover the week |
| `window.start`, `window.end` | `ReportSearchParam.start/end`; `ProjectSearchParam.updated_at`, `created_at`, `deal_date`, or `sign_date` after 14B chooses exact metric semantics; `ActivitySearchParam.start/end`; `BusinessChanceSearchParam.created_at`; `CompanySearchParam.created_at` only for company creation metrics |
| `scope.scope_id` | Internal Nanobot scope label; not sent directly unless mapped to explicit owner or group ids |
| `scope.owner_ids` | `ReportSearchParam.creator`, `ProjectSearchParam.sales` or `claim_by`, `ActivitySearchParam.creator` or `related_user`, `BusinessChanceSearchParam.sales`, `CompanySearchParam.claim_by`, `UserSearchParam.id` |
| `scope.group_ids` | `ProjectSearchParam.sales_group` or `claim_by_group`, `BusinessChanceSearchParam.sales_group`, `CompanySearchParam.claim_by_group` |

Open semantic choices for 14B:

- Whether pipeline metrics use `ProjectSearchParam.updated_at`, `deal_date`, `sign_date`, `created_at`, or a combination.
- Whether owner scope should prefer project `sales`, `claim_by`, or `claimBy.user.id`.
- Whether partner business chances are merged into the same opportunity model or kept as a distinct normalized source.

## Connection Pagination Rules

The schema uses connection objects with `total`, `skip`, `limit`, and `data` fields. `PaginationParam` has `skip` and `limit`.

Rules:

- First request starts with `skip=0`.
- Default page size should be conservative, for example `limit=100`, unless the CRM team confirms another value.
- Continue while `skip + len(data) < total` and `data` is non-empty.
- Stop immediately if a page returns no `data` to avoid infinite loops.
- Enforce a maximum page count or maximum record count in runtime config for safety.
- Preserve per-record source references across pages.
- Do not perform concurrent pagination against the real endpoint until rate-limit behavior is confirmed.

## Source Reference Rules

Every normalized record and metric must be traceable to source data without copying raw payloads.

Source reference shape:

- `system`: `crm-graphql`
- `endpoint`: logical endpoint name only, for example `crm/query`; do not include credentials or request headers.
- `query`: the allow-listed query name, for example `listProject`.
- `entity_type`: GraphQL object type, for example `Project`, `BusinessChance`, `Report`, `Activity`, `Company`, or `User`.
- `source_id`: stable GraphQL id field from the object.
- `fields`: normalized field names used by deterministic metrics.
- `window`: report window used to fetch the record when applicable.
- `page`: pagination metadata with `skip` and `limit` when the record came from a connection.

Evidence traces should reference the normalized source reference id and metric formula name, not raw GraphQL payloads.

## Redaction Rules

Do not write raw CRM payloads to `.dek`, logs, errors, tests, or report output. Redaction applies before errors are surfaced.

Always redact or omit:

- Credentials, bearer tokens, cookies, API keys, secrets, and webhook/robot URLs.
- Request headers and authentication variables.
- Contact phone numbers, email addresses, physical addresses, attachment URLs, and free-text fields unless explicitly needed and sanitized.
- GraphQL variables that contain personal identifiers beyond stable ids needed for traceability.
- Schema examples that contain token, secret, webhook, or robot URL text.

Allowed in docs/evidence:

- Schema file path and line numbers.
- Query names, type names, field names, and non-secret endpoint URL.
- Synthetic ids and synthetic report output from mock-mode tests.

## Runtime Config And Env Vars

Runtime config must be explicit and disabled by default.

Proposed environment variables:

| Env Var | Purpose | Secret |
| --- | --- | --- |
| `NANOBOT_CRM_GRAPHQL_ENABLED` | Enable real CRM GraphQL reads. Default `false`. | No |
| `NANOBOT_CRM_GRAPHQL_ENDPOINT` | GraphQL endpoint URL. Default empty; production can set the CRM endpoint externally. | No |
| `NANOBOT_CRM_GRAPHQL_TOKEN` | Bearer or internal auth token if required. | Yes |
| `NANOBOT_CRM_GRAPHQL_TIMEOUT_SECONDS` | Per-request timeout. | No |
| `NANOBOT_CRM_GRAPHQL_PAGE_LIMIT` | Connection page size. | No |
| `NANOBOT_CRM_GRAPHQL_MAX_PAGES` | Safety cap for pagination. | No |

Config rules:

- Do not read `.env.nanobot` in tests or docs tasks.
- Do not bake CRM config into Docker images.
- Do not log env var values.
- Adapter construction should fail closed when real CRM access is disabled or required config is absent.
- Tests must use mocked transport and synthetic GraphQL responses.

## Open Questions

1. Which auth mechanism should runtime use for GraphQL: bearer token, cookie, internal gateway header, mTLS, or another mechanism?
2. Which project date field defines inclusion in daily and weekly pipeline metrics: `updated_at`, `created_at`, `deal_date`, `sign_date`, or `estimated_deal_date`?
3. Which owner field is authoritative for sales scope: `sales`, `claim_by`, `claimBy.user.id`, `claim_by_group`, or another field?
4. What is the exact JSON shape of the `Money` scalar in real responses?
5. Should `BusinessChance` be merged into the same normalized opportunity stream as `Project`, or reported as a separate source category?
6. Which free-text fields, if any, are allowed in AI-readable summaries after redaction?
7. What page size and rate limits are safe for production CRM reads?
8. Should optional real CRM smoke tests run only behind an explicit environment flag and never in default CI?
