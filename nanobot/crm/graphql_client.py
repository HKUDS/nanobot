"""Superseded reference GraphQL client for the old in-process CRM route.

Production real CRM access is owned by the CRM MCP Server. Keep this module as
reference material unless the direct Nanobot GraphQL route is explicitly reopened.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from nanobot.crm.adapters import CRMAdapterErrorCode

DEFAULT_ALLOWED_OPERATIONS = frozenset(
    {
        "listReport",
        "reportInfo",
        "reportRelatedInfo",
        "listProject",
        "projectInfo",
        "listActivity",
        "listCompany",
        "companyInfo",
        "listUser",
        "list_business_chance",
        "business_chance",
    }
)

GraphQLTransport = Callable[..., dict[str, object]]


class CRMGraphQLClientError(Exception):
    """Sanitized GraphQL client error with adapter-compatible category."""

    def __init__(self, code: CRMAdapterErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CRMGraphQLClient:
    """Small read-only GraphQL shell with injected transport."""

    endpoint: str
    token: str
    transport: GraphQLTransport
    allowed_operations: frozenset[str] = field(default=DEFAULT_ALLOWED_OPERATIONS)

    def __init__(
        self,
        endpoint: str,
        token: str,
        transport: GraphQLTransport,
        allowed_operations: set[str] | frozenset[str] = DEFAULT_ALLOWED_OPERATIONS,
    ) -> None:
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "transport", transport)
        object.__setattr__(self, "allowed_operations", frozenset(allowed_operations))

    def query(
        self,
        operation_name: str,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, object]:
        """Execute an allow-listed read query through injected transport."""

        self._validate_query(operation_name, query)
        try:
            response = self.transport(
                endpoint=self.endpoint,
                token=self.token,
                operation_name=operation_name,
                query=query,
                variables=variables,
            )
        except Exception as exc:
            raise CRMGraphQLClientError(
                CRMAdapterErrorCode.CRM_UNAVAILABLE,
                self._redact(f"CRM GraphQL transport failed: {exc}"),
            ) from exc

        errors = response.get("errors")
        if errors:
            raise CRMGraphQLClientError(
                CRMAdapterErrorCode.CRM_UNAVAILABLE,
                self._redact(f"CRM GraphQL returned errors: {self._format_errors(errors)}"),
            )

        data = response.get("data")
        if not isinstance(data, dict):
            raise CRMGraphQLClientError(
                CRMAdapterErrorCode.MISSING_DATA,
                "CRM GraphQL response did not include data",
            )
        return data

    def _validate_query(self, operation_name: str, query: str) -> None:
        if self._contains_mutation(query):
            raise CRMGraphQLClientError(
                CRMAdapterErrorCode.INVALID_CONFIGURATION,
                f"CRM GraphQL mutation is forbidden for operation {operation_name}",
            )
        if operation_name not in self.allowed_operations:
            raise CRMGraphQLClientError(
                CRMAdapterErrorCode.INVALID_CONFIGURATION,
                f"CRM GraphQL operation is not allow-listed: {operation_name}",
            )

    @staticmethod
    def _contains_mutation(query: str) -> bool:
        return bool(re.search(r"(^|[\s{])mutation\b", query, flags=re.IGNORECASE))

    def _redact(self, message: str) -> str:
        sanitized = message
        if self.token:
            sanitized = sanitized.replace(self.token, "<redacted>")
        sanitized = re.sub(
            r"(?i)(bearer\s+)[^\s'\"]+",
            "<redacted>",
            sanitized,
        )
        sanitized = re.sub(r"(?i)authorization\s*:?", "<redacted>", sanitized)
        sanitized = re.sub(r"(?i)\bbearer\b", "<redacted>", sanitized)
        return sanitized

    @staticmethod
    def _format_errors(errors: object) -> tuple[str, ...]:
        if not isinstance(errors, list):
            return ("GraphQL error",)
        messages: list[str] = []
        for error in errors:
            if isinstance(error, dict) and error.get("message") is not None:
                messages.append(str(error["message"]))
            else:
                messages.append("GraphQL error")
        return tuple(messages)
