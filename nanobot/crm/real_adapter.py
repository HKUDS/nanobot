"""Superseded reference adapter for the old in-process CRM GraphQL route.

Production real CRM access is owned by the CRM MCP Server. Keep this adapter as
reference material unless the direct Nanobot GraphQL route is explicitly reopened.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import TypeVar

from nanobot.crm.adapters import CRMAdapterError, CRMAdapterErrorCode
from nanobot.crm.graphql_client import CRMGraphQLClient, CRMGraphQLClientError
from nanobot.crm.models import (
    ActivityRecord,
    BusinessChanceRecord,
    CRMSourceRef,
    CustomerRecord,
    OpportunityRecord,
    ReportRecord,
    ReportRequest,
)

T = TypeVar("T")

_PROJECT_QUERY = """
query listProject($search: ProjectSearchParam!, $pagination: PaginationParam, $sortBy: SortBy!) {
  listProject(search: $search, pagination: $pagination, sort_by: $sortBy) {
    total skip limit
    data {
      id name updated_at created_at stage deal_date estimated_deal_date sign_date estimated_sign_date win_rate
      claimBy { user { id name username } }
      company { id name }
      amount
      actual_amount
    }
  }
}
"""

_ACTIVITY_QUERY = """
query listActivity($search: [ActivitySearchParam!], $pagination: PaginationParam) {
  listActivity(search: $search, pagination: $pagination) {
    total skip limit
    data { type domain desc description link extraDesc created_at updated_at creator { id name username } }
  }
}
"""

_REPORT_QUERY = """
query listReport($search: [ReportSearchParam!], $pagination: PaginationParam) {
  listReport(search: $search, pagination: $pagination) {
    total skip limit
    data { id type created_at updated_at target content creator { id name username } }
  }
}
"""

_COMPANY_QUERY = """
query listCompany($search: [CompanySearchParam!], $pagination: PaginationParam) {
  listCompany(search: $search, pagination: $pagination) {
    total skip limit
    data { id name common_name valid created_at updated_at claim_by { id name username } industry { id name } region { id name } rank }
  }
}
"""

_BUSINESS_CHANCE_QUERY = """
query list_business_chance($search: BusinessChanceSearchParam, $pagination: PaginationParam) {
  list_business_chance(search: $search, pagination: $pagination) {
    total skip limit
    data { id company_name project_name due_at info status apply_status source commit_at created_at updated_at claim_by { id name username } company { id name } }
  }
}
"""


class RealCRMAdapter:
    """Normalize mocked GraphQL read responses into v1 CRM records."""

    def __init__(self, client: CRMGraphQLClient, page_limit: int = 100) -> None:
        self._client = client
        self._page_limit = page_limit

    def read_opportunities(self, request: ReportRequest) -> tuple[OpportunityRecord, ...]:
        return self._read_connection(
            operation_name="listProject",
            query=_PROJECT_QUERY,
            variables={
                "search": self._project_search(request),
                "sortBy": {"by": "updatedAt", "order": -1},
            },
            normalize=self._normalize_project,
        )

    def read_activities(self, request: ReportRequest) -> tuple[ActivityRecord, ...]:
        return self._read_connection(
            operation_name="listActivity",
            query=_ACTIVITY_QUERY,
            variables={"search": [self._activity_search(request)]},
            normalize=self._normalize_activity,
        )

    def read_reports(self, request: ReportRequest) -> tuple[ReportRecord, ...]:
        return self._read_connection(
            operation_name="listReport",
            query=_REPORT_QUERY,
            variables={"search": [self._report_search(request)]},
            normalize=self._normalize_report,
        )

    def read_customers(self, request: ReportRequest) -> tuple[CustomerRecord, ...]:
        return self._read_connection(
            operation_name="listCompany",
            query=_COMPANY_QUERY,
            variables={"search": [self._company_search(request)]},
            normalize=self._normalize_company,
        )

    def read_business_chances(self, request: ReportRequest) -> tuple[BusinessChanceRecord, ...]:
        return self._read_connection(
            operation_name="list_business_chance",
            query=_BUSINESS_CHANCE_QUERY,
            variables={"search": self._business_chance_search(request)},
            normalize=self._normalize_business_chance,
        )

    def _read_connection(
        self,
        *,
        operation_name: str,
        query: str,
        variables: dict[str, object],
        normalize: Callable[[dict[str, object]], T],
    ) -> tuple[T, ...]:
        records: list[T] = []
        skip = 0
        while True:
            page_variables = {**variables, "pagination": {"skip": skip, "limit": self._page_limit}}
            try:
                data = self._client.query(operation_name, query, page_variables)
                connection = data[operation_name]
            except CRMGraphQLClientError as exc:
                raise CRMAdapterError(exc.code, self._sanitize_error_message(str(exc))) from exc
            except Exception as exc:
                raise CRMAdapterError(
                    CRMAdapterErrorCode.CRM_UNAVAILABLE,
                    self._sanitize_error_message(f"CRM GraphQL read failed: {exc}"),
                ) from exc

            if not isinstance(connection, dict):
                raise CRMAdapterError(CRMAdapterErrorCode.MISSING_DATA, "missing CRM connection data")

            page_data = connection.get("data")
            if not isinstance(page_data, list):
                raise CRMAdapterError(CRMAdapterErrorCode.MISSING_DATA, "missing CRM connection records")

            for item in page_data:
                if not isinstance(item, dict):
                    raise CRMAdapterError(CRMAdapterErrorCode.MISSING_DATA, "invalid CRM connection record")
                try:
                    records.append(normalize(item))
                except KeyError as exc:
                    raise CRMAdapterError(
                        CRMAdapterErrorCode.MISSING_DATA,
                        f"missing required CRM field: {exc.args[0]}",
                    ) from exc
                except (TypeError, ValueError) as exc:
                    raise CRMAdapterError(
                        CRMAdapterErrorCode.MISSING_DATA,
                        self._sanitize_error_message(f"invalid CRM record shape: {exc}"),
                    ) from exc

            total = int(connection.get("total", len(records)))
            if not page_data or len(records) >= total:
                return tuple(records)
            skip += len(page_data)

    @staticmethod
    def _project_search(request: ReportRequest) -> dict[str, object]:
        search: dict[str, object] = {
            "updated_at": {
                "from": request.window.start.isoformat(),
                "to": request.window.end.isoformat(),
            }
        }
        if request.scope.owner_ids:
            search["sales"] = list(request.scope.owner_ids)
        if request.scope.team_ids:
            search["sales_group"] = list(request.scope.team_ids)
        return search

    @staticmethod
    def _activity_search(request: ReportRequest) -> dict[str, object]:
        search: dict[str, object] = {
            "start": request.window.start.isoformat(),
            "end": request.window.end.isoformat(),
        }
        if request.scope.owner_ids:
            search["creator"] = list(request.scope.owner_ids)
        return search

    @staticmethod
    def _report_search(request: ReportRequest) -> dict[str, object]:
        search: dict[str, object] = {
            "start": request.window.start.isoformat(),
            "end": request.window.end.isoformat(),
            "type": request.report_type.value,
        }
        if request.scope.owner_ids:
            search["creator"] = list(request.scope.owner_ids)
        return search

    @staticmethod
    def _company_search(request: ReportRequest) -> dict[str, object]:
        search: dict[str, object] = {}
        if request.scope.owner_ids:
            search["claim_by"] = list(request.scope.owner_ids)
        if request.scope.team_ids:
            search["claim_by_group"] = list(request.scope.team_ids)
        return search

    @staticmethod
    def _business_chance_search(request: ReportRequest) -> dict[str, object]:
        search: dict[str, object] = {
            "created_at": {
                "from": request.window.start.isoformat(),
                "to": request.window.end.isoformat(),
            }
        }
        if request.scope.owner_ids:
            search["sales"] = list(request.scope.owner_ids)
        if request.scope.team_ids:
            search["sales_group"] = list(request.scope.team_ids)
        return search

    def _normalize_project(self, item: dict[str, object]) -> OpportunityRecord:
        owner = self._nested_dict(item.get("claimBy"), "user")
        company = self._as_dict(item.get("company"))
        project_id = self._required_str(item, "id")
        stage = self._required_str(item, "stage")
        return OpportunityRecord(
            opportunity_id=project_id,
            title=self._required_str(item, "name"),
            owner_id=self._optional_str(owner, "id") or "",
            owner_name=self._optional_str(owner, "name"),
            customer_id=self._optional_str(company, "id"),
            customer_name=self._optional_str(company, "name"),
            stage=stage,
            status=stage,
            amount=self._money_value(item.get("amount")) or self._money_value(item.get("actual_amount")),
            created_at=self._datetime(item, "created_at"),
            updated_at=self._datetime(item, "updated_at"),
            expected_close_date=self._optional_date(
                item.get("estimated_deal_date") or item.get("deal_date") or item.get("estimated_sign_date") or item.get("sign_date")
            ),
            source_ref=CRMSourceRef(
                entity_type="Project",
                source_id=project_id,
                fields=("id", "name", "stage", "amount", "actual_amount", "claimBy.user.id", "company.id"),
            ),
        )

    def _normalize_activity(self, item: dict[str, object]) -> ActivityRecord:
        creator = self._as_dict(item.get("creator"))
        created_at = self._datetime(item, "created_at")
        activity_id = self._optional_str(item, "id")
        return ActivityRecord(
            activity_id=activity_id,
            type=self._required_str(item, "type"),
            domain=self._required_str(item, "domain"),
            creator_id=self._optional_str(creator, "id"),
            creator_name=self._optional_str(creator, "name"),
            desc=self._required_str(item, "desc"),
            description=self._optional_str(item, "description"),
            link=self._optional_str(item, "link"),
            extra_desc=self._optional_str(item, "extraDesc"),
            created_at=created_at,
            updated_at=self._datetime(item, "updated_at"),
            source_ref=CRMSourceRef(
                entity_type="Activity",
                source_id=activity_id or f"activity:{created_at.isoformat()}",
                fields=("type", "domain", "creator.id", "created_at", "updated_at"),
            ),
        )

    def _normalize_report(self, item: dict[str, object]) -> ReportRecord:
        creator = self._as_dict(item.get("creator"))
        report_id = self._required_str(item, "id")
        return ReportRecord(
            report_id=report_id,
            report_type=self._required_str(item, "type"),
            target=self._datetime(item, "target"),
            creator_id=self._optional_str(creator, "id"),
            creator_name=self._optional_str(creator, "name"),
            content=self._required_str(item, "content"),
            created_at=self._datetime(item, "created_at"),
            updated_at=self._optional_datetime(item.get("updated_at")),
            source_ref=CRMSourceRef(
                entity_type="Report",
                source_id=report_id,
                fields=("id", "type", "target", "creator.id", "content"),
            ),
        )

    def _normalize_company(self, item: dict[str, object]) -> CustomerRecord:
        claim_by = self._as_dict(item.get("claim_by"))
        industry = self._as_dict(item.get("industry"))
        region = self._as_dict(item.get("region"))
        company_id = self._required_str(item, "id")
        return CustomerRecord(
            customer_id=company_id,
            name=self._required_str(item, "name"),
            common_name=self._optional_str(item, "common_name"),
            claim_by_id=self._optional_str(claim_by, "id"),
            claim_by_name=self._optional_str(claim_by, "name"),
            industry_name=self._optional_str(industry, "name"),
            region_name=self._optional_str(region, "name"),
            rank=self._optional_str(item, "rank"),
            valid=bool(item.get("valid")),
            created_at=self._datetime(item, "created_at"),
            updated_at=self._datetime(item, "updated_at"),
            source_ref=CRMSourceRef(
                entity_type="Company",
                source_id=company_id,
                fields=("id", "name", "claim_by.id", "industry.name", "region.name"),
            ),
        )

    def _normalize_business_chance(self, item: dict[str, object]) -> BusinessChanceRecord:
        claim_by = self._as_dict(item.get("claim_by"))
        company = self._as_dict(item.get("company"))
        chance_id = self._required_str(item, "id")
        return BusinessChanceRecord(
            chance_id=chance_id,
            company_id=self._optional_str(company, "id"),
            company_name=self._required_str(item, "company_name"),
            project_name=self._required_str(item, "project_name"),
            due_at=self._datetime(item, "due_at"),
            claim_by_id=self._optional_str(claim_by, "id"),
            claim_by_name=self._optional_str(claim_by, "name"),
            info=self._required_str(item, "info"),
            status=self._required_str(item, "status"),
            apply_status=self._required_str(item, "apply_status"),
            source=self._required_str(item, "source"),
            created_at=self._datetime(item, "created_at"),
            updated_at=self._datetime(item, "updated_at"),
            source_ref=CRMSourceRef(
                entity_type="BusinessChance",
                source_id=chance_id,
                fields=("id", "project_name", "claim_by.id", "status", "apply_status"),
            ),
        )

    @staticmethod
    def _required_str(item: dict[str, object], field: str) -> str:
        value = item[field]
        if value is None:
            raise KeyError(field)
        return str(value)

    @staticmethod
    def _optional_str(item: dict[str, object], field: str) -> str | None:
        value = item.get(field)
        return str(value) if value is not None else None

    @staticmethod
    def _datetime(item: dict[str, object], field: str) -> datetime:
        return RealCRMAdapter._parse_datetime(item[field])

    @staticmethod
    def _optional_datetime(value: object) -> datetime | None:
        return RealCRMAdapter._parse_datetime(value) if value is not None else None

    @staticmethod
    def _optional_date(value: object) -> date | None:
        parsed = RealCRMAdapter._optional_datetime(value)
        return parsed.date() if parsed is not None else None

    @staticmethod
    def _parse_datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise TypeError("expected datetime string")

    @staticmethod
    def _as_dict(value: object) -> dict[str, object]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _nested_dict(value: object, key: str) -> dict[str, object]:
        parent = RealCRMAdapter._as_dict(value)
        return RealCRMAdapter._as_dict(parent.get(key))

    @staticmethod
    def _money_value(value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int | str):
            return Decimal(str(value))
        if isinstance(value, dict) and value.get("value") is not None:
            return Decimal(str(value["value"]))
        return None

    @staticmethod
    def _sanitize_error_message(message: str) -> str:
        sanitized = message.replace("Authorization", "<redacted>").replace("Bearer", "<redacted>")
        return sanitized
