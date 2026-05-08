"""Optional real CRM smoke path with sanitized diagnostics only."""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from crm_mcp_server.diagnostics import crm_smoke_check

LOCAL_INSPECTION_WARNING = (
    "LOCAL ONLY: GraphQL error inspection may contain sensitive CRM details. "
    "do not paste output into chat; do not commit output."
)
AUTH_MODES = ("private_token", "bearer", "cookie")


@dataclass(frozen=True, repr=False)
class RealSmokeConfig:
    endpoint: str = field(repr=False)
    token: str = field(repr=False)
    auth_mode: str = "bearer"

    def __repr__(self) -> str:
        return f"RealSmokeConfig(endpoint=<redacted>, token=<redacted>, auth_mode={self.auth_mode!r})"


@dataclass(repr=False)
class RealGraphQLSmokeTransport:
    config: RealSmokeConfig = field(repr=False)
    timeout_seconds: float = 10.0
    http_status_category: str = "not_attempted"
    transport_error_category: str | None = None
    response_json_parsed: bool = False
    status_code_category: str | None = None
    last_response: Mapping[str, Any] | None = field(default=None, init=False, repr=False)

    def __repr__(self) -> str:
        return "RealGraphQLSmokeTransport(config=<redacted>)"

    @property
    def auth_mode(self) -> str:
        return self.config.auth_mode

    def execute(self, operation_name: str, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        self.transport_error_category = None
        self.response_json_parsed = False
        self.status_code_category = None
        self.last_response = None
        payload = json.dumps(
            {"operationName": operation_name, "query": query, "variables": variables},
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            request = urllib.request.Request(
                self.config.endpoint,
                data=payload,
                headers=_auth_headers(self.config),
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                self.http_status_category = _http_status_category(response.status)
                self.status_code_category = _status_code_category(response.status)
                body = response.read()
        except ValueError:
            self.http_status_category = "crm_unavailable"
            self.status_code_category = "not_available"
            self.transport_error_category = "invalid_url"
            return {}
        except urllib.error.HTTPError as exc:
            self.http_status_category = _http_status_category(exc.code)
            self.status_code_category = _status_code_category(exc.code)
            self.transport_error_category = _http_transport_error_category(exc.code)
            return {}
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            self.http_status_category = "crm_unavailable"
            self.status_code_category = "not_available"
            self.transport_error_category = _exception_transport_error_category(exc)
            return {}

        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.transport_error_category = "empty_response" if not body else "non_json_response"
            return {}
        if isinstance(parsed, Mapping):
            self.response_json_parsed = True
            self.last_response = parsed
            return parsed
        self.response_json_parsed = True
        self.transport_error_category = "non_json_response"
        return {}


def load_real_smoke_config_from_env(*, auth_mode: str = "bearer") -> RealSmokeConfig | None:
    endpoint = os.environ.get("CRM_GRAPHQL_ENDPOINT")
    token = os.environ.get("CRM_GRAPHQL_TOKEN")
    if not endpoint or not token:
        return None
    return RealSmokeConfig(endpoint=endpoint, token=token, auth_mode=auth_mode)


def run_real_crm_smoke(*, transport: Any | None = None, auth_mode: str = "bearer") -> dict[str, object]:
    config = load_real_smoke_config_from_env(auth_mode=auth_mode)
    if config is None:
        return crm_smoke_check(
            runtime_enabled=False,
            endpoint_configured=os.environ.get("CRM_GRAPHQL_ENDPOINT") is not None,
            token_configured=os.environ.get("CRM_GRAPHQL_TOKEN") is not None,
            proxy_configured=_proxy_configured(),
            auth_mode=auth_mode,
        )

    smoke_transport = transport if transport is not None else RealGraphQLSmokeTransport(config=config)
    return crm_smoke_check(
        runtime_enabled=True,
        transport=smoke_transport,
        endpoint_configured=True,
        token_configured=True,
        proxy_configured=_proxy_configured(),
        auth_mode=getattr(smoke_transport, "auth_mode", auth_mode),
    )


def run_real_crm_smoke_for_local_inspection(*, auth_mode: str = "bearer") -> tuple[dict[str, object], list[str]]:
    config = load_real_smoke_config_from_env(auth_mode=auth_mode)
    if config is None:
        return (
            crm_smoke_check(
                runtime_enabled=False,
                endpoint_configured=os.environ.get("CRM_GRAPHQL_ENDPOINT") is not None,
                token_configured=os.environ.get("CRM_GRAPHQL_TOKEN") is not None,
                proxy_configured=_proxy_configured(),
                auth_mode=auth_mode,
            ),
            [],
        )
    transport = RealGraphQLSmokeTransport(config=config)
    result = crm_smoke_check(
        runtime_enabled=True,
        transport=transport,
        endpoint_configured=True,
        token_configured=True,
        proxy_configured=_proxy_configured(),
        auth_mode=config.auth_mode,
    )
    return result, _redacted_graphql_error_messages(
        getattr(transport, "last_response", getattr(transport, "response", None)),
        config=config,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run sanitized CRM real smoke diagnostics.")
    parser.add_argument("--inspect-graphql-error-local", action="store_true")
    parser.add_argument("--auth-mode", choices=AUTH_MODES, default="bearer")
    args = parser.parse_args([] if argv is None else argv)
    if args.inspect_graphql_error_local:
        result, messages = run_real_crm_smoke_for_local_inspection(auth_mode=args.auth_mode)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        print(LOCAL_INSPECTION_WARNING)
        for index, message in enumerate(messages, start=1):
            print(f"graphql_error_message_{index}: {message}")
        return 0

    result = run_real_crm_smoke(auth_mode=args.auth_mode)
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


def _status_code_category(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "not_available"


def _http_transport_error_category(status_code: int) -> str | None:
    if 400 <= status_code < 500:
        return "http_4xx"
    if 500 <= status_code < 600:
        return "http_5xx"
    return None


def _exception_transport_error_category(exc: BaseException) -> str:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, socket.gaierror):
        return "dns_error"
    if isinstance(reason, TimeoutError) or isinstance(exc, TimeoutError):
        return "connect_timeout"
    if isinstance(reason, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(reason, ConnectionResetError):
        return "connection_reset"
    if isinstance(reason, ssl.SSLError):
        return "tls_error"
    if isinstance(reason, OSError) and getattr(reason, "errno", None) in {
        errno.ENETDOWN,
        errno.ENETUNREACH,
        errno.EHOSTDOWN,
        errno.EHOSTUNREACH,
    }:
        return "network_unreachable"
    return "unknown_transport_error"


def _proxy_configured() -> bool:
    return any(os.environ.get(name) for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"))


def _auth_headers(config: RealSmokeConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.auth_mode == "bearer":
        headers["Authorization"] = f"Bearer {config.token}"
    elif config.auth_mode == "cookie":
        headers["Cookie"] = config.token
    else:
        headers["Private-Token"] = config.token
    return headers


def _redacted_graphql_error_messages(response: Mapping[str, Any] | None, *, config: RealSmokeConfig) -> list[str]:
    if response is None:
        return []
    errors = response.get("errors")
    if not isinstance(errors, list):
        return []
    messages: list[str] = []
    for error in errors:
        if not isinstance(error, Mapping):
            continue
        message = error.get("message")
        if isinstance(message, str):
            messages.append(_redact_local_inspection_text(message, config=config))
    return messages


def _redact_local_inspection_text(text: str, *, config: RealSmokeConfig) -> str:
    redacted = text.replace(config.endpoint, "[REDACTED_ENDPOINT]").replace(config.token, "[REDACTED_AUTH]")
    redacted = re.sub(r"(?i)authorization\s*[:=]?\s*bearer\s+\S+", "[REDACTED_AUTH]", redacted)
    redacted = re.sub(r"(?i)bearer\s+\S+", "[REDACTED_AUTH]", redacted)
    redacted = re.sub(r"(?i)(private-token|token|cookie)\s*[:=]\s*\S+", "[REDACTED_AUTH]", redacted)
    redacted = re.sub(r"(?i)cookie\s+\S+", "[REDACTED_AUTH]", redacted)
    redacted = re.sub(r"https?://[^\s,)\]}]+", "[REDACTED_ENDPOINT]", redacted)
    forbidden_replacements = {
        "raw GraphQL request": "[REDACTED_GRAPHQL_REQUEST]",
        "raw GraphQL response": "[REDACTED_GRAPHQL_RESPONSE]",
        "variables": "[REDACTED_VARIABLES]",
        "Synthetic Customer Name": "[REDACTED_CRM_DATA]",
        "Synthetic Project Name": "[REDACTED_CRM_DATA]",
        "amount": "[REDACTED_CRM_DATA]",
        "contact": "[REDACTED_CRM_DATA]",
        "phone": "[REDACTED_CRM_DATA]",
        "email": "[REDACTED_CRM_DATA]",
        "address": "[REDACTED_CRM_DATA]",
        "free-text CRM note": "[REDACTED_CRM_DATA]",
    }
    for marker, replacement in forbidden_replacements.items():
        redacted = redacted.replace(marker, replacement)
    return redacted


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
