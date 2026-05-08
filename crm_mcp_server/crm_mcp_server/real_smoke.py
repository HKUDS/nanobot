"""Optional real CRM smoke path with sanitized diagnostics only."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from crm_mcp_server.diagnostics import crm_smoke_check


@dataclass(frozen=True, repr=False)
class RealSmokeConfig:
    endpoint: str = field(repr=False)
    token: str = field(repr=False)

    def __repr__(self) -> str:
        return "RealSmokeConfig(endpoint=<redacted>, token=<redacted>)"


@dataclass(repr=False)
class RealGraphQLSmokeTransport:
    config: RealSmokeConfig = field(repr=False)
    timeout_seconds: float = 10.0
    http_status_category: str = "not_attempted"

    def __repr__(self) -> str:
        return "RealGraphQLSmokeTransport(config=<redacted>)"

    def execute(self, operation_name: str, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = json.dumps(
            {"operationName": operation_name, "query": query, "variables": variables},
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.config.endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Private-Token": self.config.token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                self.http_status_category = _http_status_category(response.status)
                body = response.read()
        except urllib.error.HTTPError as exc:
            self.http_status_category = _http_status_category(exc.code)
            return {}
        except (OSError, TimeoutError, urllib.error.URLError):
            self.http_status_category = "crm_unavailable"
            return {}

        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if isinstance(parsed, Mapping):
            return parsed
        return {}


def load_real_smoke_config_from_env() -> RealSmokeConfig | None:
    endpoint = os.environ.get("CRM_GRAPHQL_ENDPOINT")
    token = os.environ.get("CRM_GRAPHQL_TOKEN")
    if not endpoint or not token:
        return None
    return RealSmokeConfig(endpoint=endpoint, token=token)


def run_real_crm_smoke(*, transport: Any | None = None) -> dict[str, object]:
    config = load_real_smoke_config_from_env()
    if config is None:
        return crm_smoke_check(runtime_enabled=False)

    smoke_transport = transport if transport is not None else RealGraphQLSmokeTransport(config=config)
    return crm_smoke_check(runtime_enabled=True, transport=smoke_transport)


def main() -> int:
    result = run_real_crm_smoke()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _http_status_category(status_code: int) -> str:
    if status_code in {401, 403}:
        return "unauthorized_or_forbidden"
    if status_code == 429:
        return "rate_limited"
    if 200 <= status_code < 300:
        return "success"
    return "crm_unavailable"


if __name__ == "__main__":
    raise SystemExit(main())
