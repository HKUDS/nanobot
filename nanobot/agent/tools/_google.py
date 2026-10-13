"""Google service-account helpers: load the client libraries and build an API client."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import NamedTuple, Protocol, cast

from nanobot.config.paths import get_data_dir


class _CredentialsFactory(Protocol):
    def from_service_account_file(
        self,
        filename: str,
        *,
        scopes: list[str],
    ) -> object: ...


class _ServiceBuilder(Protocol):
    def __call__(self, service_name: str, version: str, **kwargs: object) -> object: ...


class _HttpFactory(Protocol):
    def __call__(self, *, timeout: float) -> object: ...


class _AuthorizedHttpFactory(Protocol):
    def __call__(self, credentials: object, *, http: object) -> object: ...


class GoogleDeps(NamedTuple):
    credentials: _CredentialsFactory
    build: _ServiceBuilder
    http: _HttpFactory
    authorized_http: _AuthorizedHttpFactory


def require_google_deps(label: str, extra: str) -> GoogleDeps:
    try:
        service_account = importlib.import_module("google.oauth2.service_account")
        discovery = importlib.import_module("googleapiclient.discovery")
        httplib2 = importlib.import_module("httplib2")
        google_auth_httplib2 = importlib.import_module("google_auth_httplib2")
    except ImportError as exc:
        raise RuntimeError(
            f"{label} support is not installed. Run: nanobot plugins enable {extra}"
        ) from exc
    credentials = getattr(service_account, "Credentials", None)
    build = getattr(discovery, "build", None)
    http = getattr(httplib2, "Http", None)
    authorized_http = getattr(google_auth_httplib2, "AuthorizedHttp", None)
    if credentials is None or not callable(build) or not callable(http) or not callable(authorized_http):
        raise RuntimeError(f"{label} support is installed but could not be loaded")
    return GoogleDeps(
        cast(_CredentialsFactory, credentials),
        cast(_ServiceBuilder, build),
        cast(_HttpFactory, http),
        cast(_AuthorizedHttpFactory, authorized_http),
    )


def build_google_service(
    deps: GoogleDeps,
    api: str,
    version: str,
    *,
    credentials_path: Path,
    scope: str,
    timeout: float,
) -> object:
    credentials = deps.credentials.from_service_account_file(
        str(credentials_path),
        scopes=[scope],
    )
    http = deps.authorized_http(credentials, http=deps.http(timeout=timeout))
    return deps.build(api, version, http=http, cache_discovery=False)


def resolve_credentials_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = get_data_dir() / path
    return path.resolve(strict=False)


def _validated_service_account_values(parsed: object) -> dict[str, object]:
    if not isinstance(parsed, dict):
        raise ValueError("JSON must be a Google service account key (type: service_account)")
    values = cast(dict[str, object], parsed)
    if values.get("type") != "service_account":
        raise ValueError("JSON must be a Google service account key (type: service_account)")
    if not isinstance(values.get("client_email"), str) or not str(values["client_email"]).strip():
        raise ValueError("service account JSON is missing client_email")
    if not isinstance(values.get("private_key"), str) or not str(values["private_key"]).strip():
        raise ValueError("service account JSON is missing private_key")
    return values


def service_account_email_hint(credentials_path: str | Path) -> str | None:
    path = resolve_credentials_path(credentials_path)
    try:
        values = _validated_service_account_values(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    email = values.get("client_email")
    return email if isinstance(email, str) else None
