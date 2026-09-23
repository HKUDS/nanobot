"""Minimal async Linear OAuth and GraphQL client."""

from __future__ import annotations

import asyncio
import mimetypes
import time
from pathlib import Path
from typing import Any, cast

import httpx

from nanobot.channels.linear.config import LinearConfig
from nanobot.channels.linear.oauth import LINEAR_SCOPES
from nanobot.channels.linear.state import LinearInstallation, LinearStateStore
from nanobot.security.network import validate_url_target

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
LINEAR_TOKEN_URL = "https://api.linear.app/oauth/token"
LINEAR_REVOKE_URL = "https://api.linear.app/oauth/revoke"
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024


class LinearApiError(RuntimeError):
    """Linear returned a transport, authentication, or GraphQL error."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


class LinearClient:
    def __init__(
        self,
        config: LinearConfig,
        state: LinearStateStore,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._owns_http = http is None
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def exchange_code(self, code: str, verifier: str) -> LinearInstallation:
        token = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "code_verifier": verifier,
            }
        )
        access_token = _required_string(token, "access_token")
        identity = await self._graphql_with_token(
            access_token,
            "query NanobotLinearIdentity { viewer { id organization { id name } } }",
            {},
        )
        viewer = _required_mapping(identity, "viewer")
        organization = _required_mapping(viewer, "organization")
        scopes = _scopes(token.get("scope"))
        missing_scopes = set(LINEAR_SCOPES) - set(scopes)
        if missing_scopes:
            raise LinearApiError(
                "Linear authorization is missing required scope(s): "
                + ", ".join(sorted(missing_scopes))
            )
        installation = LinearInstallation(
            organization_id=_required_string(organization, "id"),
            oauth_client_id=self.config.client_id,
            organization_name=str(organization.get("name") or ""),
            app_user_id=_required_string(viewer, "id"),
            access_token=access_token,
            refresh_token=_required_string(token, "refresh_token"),
            expires_at=time.time() + _expires_in(token),
            scope=scopes,
        )
        self.state.save_installation(installation)
        return installation

    async def graphql(
        self,
        organization_id: str,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        installation = await self._fresh_installation(organization_id)
        try:
            return await self._graphql_with_token(installation.access_token, query, variables)
        except LinearApiError as exc:
            if "authentication" not in str(exc).lower():
                raise
        installation = await self._refresh(organization_id, force=True)
        return await self._graphql_with_token(installation.access_token, query, variables)

    async def create_activity(
        self,
        organization_id: str,
        agent_session_id: str,
        content: dict[str, Any],
        *,
        activity_id: str,
        ephemeral: bool = False,
        signal: str | None = None,
        signal_metadata: dict[str, Any] | None = None,
    ) -> None:
        activity_input: dict[str, Any] = {
            "id": activity_id,
            "agentSessionId": agent_session_id,
            "content": content,
            "ephemeral": ephemeral,
        }
        if signal:
            activity_input["signal"] = signal
        if signal_metadata:
            activity_input["signalMetadata"] = signal_metadata
        data = await self.graphql(
            organization_id,
            """
            mutation NanobotAgentActivityCreate($input: AgentActivityCreateInput!) {
              agentActivityCreate(input: $input) { success agentActivity { id } }
            }
            """,
            {"input": activity_input},
        )
        result = _required_mapping(data, "agentActivityCreate")
        if result.get("success") is not True:
            raise LinearApiError("Linear did not accept the agent activity")

    async def revoke_installation(self, installation: LinearInstallation) -> None:
        """Revoke both tokens for an installation before removing local state."""
        tokens = (
            (installation.access_token, "access_token"),
            (installation.refresh_token, "refresh_token"),
        )
        revoked: set[str] = set()
        for token, token_type in tokens:
            if not token or token in revoked:
                continue
            revoked.add(token)
            try:
                response = await self._http.post(
                    LINEAR_REVOKE_URL,
                    data={"token": token, "token_type_hint": token_type},
                )
            except httpx.HTTPError as exc:
                raise LinearApiError(
                    f"Linear authorization revocation failed: {exc}", retryable=True
                ) from exc
            # Linear returns 400/401 for tokens that are already unusable. In
            # either case there is no remaining credential for nanobot to keep.
            if response.status_code not in {200, 400, 401}:
                raise LinearApiError(
                    f"Linear authorization revocation failed with HTTP {response.status_code}",
                    retryable=response.status_code == 429 or response.status_code >= 500,
                    retry_after=_retry_after_seconds(response),
                )

    async def upload_file(self, organization_id: str, file_path: Path) -> str:
        """Upload a local outbound attachment and return its Linear asset URL."""
        try:
            size = file_path.stat().st_size
        except OSError as exc:
            raise LinearApiError(f"Unable to read attachment {file_path.name}: {exc}") from exc
        if not file_path.is_file():
            raise LinearApiError(f"Attachment is not a file: {file_path.name}")
        if size > MAX_UPLOAD_BYTES:
            raise LinearApiError(
                f"Attachment {file_path.name} is larger than the 40 MB Linear upload limit"
            )
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        data = await self.graphql(
            organization_id,
            """
            mutation NanobotFileUpload($filename: String!, $contentType: String!, $size: Int!) {
              fileUpload(filename: $filename, contentType: $contentType, size: $size) {
                success
                uploadFile { uploadUrl assetUrl headers { key value } }
              }
            }
            """,
            {"filename": file_path.name, "contentType": content_type, "size": size},
        )
        result = _required_mapping(data, "fileUpload")
        if result.get("success") is not True:
            raise LinearApiError("Linear did not create an attachment upload")
        upload = _required_mapping(result, "uploadFile")
        upload_url = _required_string(upload, "uploadUrl")
        asset_url = _required_string(upload, "assetUrl")
        safe, error = await asyncio.to_thread(validate_url_target, upload_url)
        if not safe:
            raise LinearApiError(f"Linear returned an unsafe upload URL: {error}")
        raw_headers = upload.get("headers")
        headers: dict[str, str] = {}
        if isinstance(raw_headers, list):
            for item in cast(list[object], raw_headers):
                if not isinstance(item, dict):
                    continue
                header = cast(dict[str, object], item)
                key = header.get("key")
                value = header.get("value")
                if isinstance(key, str) and isinstance(value, str):
                    headers[key] = value
        if not any(key.lower() == "content-type" for key in headers):
            headers["Content-Type"] = content_type
        if not any(key.lower() == "cache-control" for key in headers):
            headers["Cache-Control"] = "public, max-age=31536000"
        try:
            content = await asyncio.to_thread(file_path.read_bytes)
            response = await self._http.put(upload_url, headers=headers, content=content)
        except (OSError, httpx.HTTPError) as exc:
            raise LinearApiError(
                f"Linear attachment upload failed: {exc}",
                retryable=isinstance(exc, httpx.HTTPError),
            ) from exc
        if response.is_error:
            raise LinearApiError(
                f"Linear attachment upload failed with HTTP {response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
                retry_after=_retry_after_seconds(response),
            )
        return asset_url

    async def download_file(
        self,
        organization_id: str,
        url: str,
        *,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> tuple[bytes, str]:
        """Download one authenticated Linear storage object with a bounded size."""
        if max_bytes <= 0 or max_bytes > MAX_DOWNLOAD_BYTES:
            raise LinearApiError("Invalid Linear attachment download limit")
        parsed = httpx.URL(url)
        if parsed.scheme != "https" or parsed.host != "uploads.linear.app":
            raise LinearApiError("Linear attachment URL must use https://uploads.linear.app")
        installation = await self._fresh_installation(organization_id)
        try:
            return await self._download_file_with_token(
                url, installation.access_token, max_bytes=max_bytes
            )
        except LinearApiError as exc:
            if "authentication" not in str(exc).lower():
                raise
        installation = await self._refresh(organization_id, force=True)
        return await self._download_file_with_token(
            url, installation.access_token, max_bytes=max_bytes
        )

    async def _download_file_with_token(
        self,
        url: str,
        access_token: str,
        *,
        max_bytes: int,
    ) -> tuple[bytes, str]:
        try:
            async with self._http.stream(
                "GET",
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response:
                if response.status_code in {401, 403}:
                    raise LinearApiError("Linear attachment authentication failed")
                if response.is_error:
                    raise LinearApiError(
                        f"Linear attachment download failed with HTTP {response.status_code}",
                        retryable=response.status_code == 429 or response.status_code >= 500,
                        retry_after=_retry_after_seconds(response),
                    )
                raw_length = response.headers.get("Content-Length", "")
                try:
                    content_length = int(raw_length)
                except ValueError:
                    content_length = -1
                if content_length > max_bytes:
                    raise LinearApiError("Linear attachment exceeds the download budget")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise LinearApiError("Linear attachment exceeds the download budget")
                    chunks.append(chunk)
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                return b"".join(chunks), content_type.split(";", 1)[0].strip()
        except httpx.HTTPError as exc:
            raise LinearApiError(
                f"Linear attachment download failed: {exc}", retryable=True
            ) from exc

    async def _fresh_installation(self, organization_id: str) -> LinearInstallation:
        installation = self.state.installation(organization_id)
        if installation is None:
            raise LinearApiError(
                f"No Linear OAuth installation for organization {organization_id}"
            )
        if installation.oauth_client_id != self.config.client_id:
            raise LinearApiError(
                "The Linear workspace was authorized for a different OAuth Client ID; reconnect it"
            )
        if installation.expires_at <= time.time() + 60:
            return await self._refresh(organization_id)
        return installation

    async def _refresh(self, organization_id: str, *, force: bool = False) -> LinearInstallation:
        lock = self._refresh_locks.setdefault(organization_id, asyncio.Lock())
        async with lock:
            installation = self.state.installation(organization_id)
            if installation is None:
                raise LinearApiError(
                    f"No Linear OAuth installation for organization {organization_id}"
                )
            if not force and installation.expires_at > time.time() + 60:
                return installation
            token = await self._token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": installation.refresh_token,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                }
            )
            refreshed = LinearInstallation(
                organization_id=installation.organization_id,
                oauth_client_id=installation.oauth_client_id,
                organization_name=installation.organization_name,
                app_user_id=installation.app_user_id,
                access_token=_required_string(token, "access_token"),
                refresh_token=_required_string(token, "refresh_token"),
                expires_at=time.time() + _expires_in(token),
                scope=_scopes(token.get("scope")) or installation.scope,
            )
            missing_scopes = set(LINEAR_SCOPES) - set(refreshed.scope)
            if missing_scopes:
                raise LinearApiError(
                    "Refreshed Linear authorization is missing required scope(s): "
                    + ", ".join(sorted(missing_scopes))
                )
            self.state.save_installation(refreshed)
            return refreshed

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._http.post(LINEAR_TOKEN_URL, data=form)
        except httpx.HTTPError as exc:
            raise LinearApiError(f"Linear OAuth request failed: {exc}", retryable=True) from exc
        payload = _response_object(response)
        if response.is_error:
            detail = str(payload.get("error_description") or payload.get("error") or response.status_code)
            raise LinearApiError(
                f"Linear OAuth request failed: {detail}",
                retryable=response.status_code == 429 or response.status_code >= 500,
                retry_after=_retry_after_seconds(response),
            )
        return payload

    async def _graphql_with_token(
        self,
        access_token: str,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = await self._http.post(
                LINEAR_GRAPHQL_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"query": query, "variables": variables},
            )
        except httpx.HTTPError as exc:
            raise LinearApiError(f"Linear API request failed: {exc}", retryable=True) from exc
        if response.status_code in {401, 403}:
            raise LinearApiError("Linear authentication failed")
        payload = _response_object(response)
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            messages: list[str] = []
            retryable = False
            for raw_error in cast(list[object], errors):
                if isinstance(raw_error, dict):
                    error = cast(dict[str, Any], raw_error)
                    message = str(error.get("message") or "GraphQL error")
                    messages.append(message)
                    extensions = error.get("extensions")
                    code = (
                        str(cast(dict[str, Any], extensions).get("code") or "").upper()
                        if isinstance(extensions, dict)
                        else ""
                    )
                    retryable = retryable or code in {
                        "INTERNAL_ERROR",
                        "INTERNAL_SERVER_ERROR",
                        "RATELIMITED",
                        "SERVICE_UNAVAILABLE",
                    } or "internal" in message.lower()
            message = "; ".join(messages) or "GraphQL error"
            raise LinearApiError(
                message,
                retryable=retryable,
                retry_after=_retry_after_seconds(response) if retryable else None,
            )
        if response.is_error:
            raise LinearApiError(
                f"Linear API request failed with HTTP {response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
                retry_after=_retry_after_seconds(response),
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise LinearApiError("Linear API response did not contain data")
        return cast(dict[str, Any], data)


def _response_object(response: httpx.Response) -> dict[str, Any]:
    retryable = response.status_code == 429 or response.status_code >= 500
    try:
        value: object = response.json()
    except ValueError as exc:
        raise LinearApiError(
            "Linear returned a non-JSON response",
            retryable=retryable,
            retry_after=_retry_after_seconds(response) if retryable else None,
        ) from exc
    if not isinstance(value, dict):
        raise LinearApiError(
            "Linear returned an invalid JSON response",
            retryable=retryable,
            retry_after=_retry_after_seconds(response) if retryable else None,
        )
    return cast(dict[str, Any], value)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw_retry_after = response.headers.get("Retry-After", "").strip()
    try:
        retry_after = float(raw_retry_after)
    except ValueError:
        retry_after = -1.0
    if retry_after >= 0:
        return retry_after
    for header in (
        "X-RateLimit-Endpoint-Requests-Reset",
        "X-RateLimit-Requests-Reset",
        "X-RateLimit-Complexity-Reset",
    ):
        raw_reset = response.headers.get(header, "").strip()
        try:
            reset = float(raw_reset)
        except ValueError:
            continue
        reset_seconds = reset / 1000 if reset > 10_000_000_000 else reset
        return max(0.0, reset_seconds - time.time())
    return None


def _required_mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise LinearApiError(f"Linear response is missing {key}")
    return cast(dict[str, Any], item)


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise LinearApiError(f"Linear response is missing {key}")
    return item


def _expires_in(value: dict[str, Any]) -> float:
    expires = value.get("expires_in")
    if isinstance(expires, int | float) and not isinstance(expires, bool):
        return max(60.0, float(expires))
    return 86400.0


def _scopes(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item for item in value.replace(",", " ").split() if item)
    if isinstance(value, list):
        return tuple(str(item) for item in cast(list[object], value))
    return ()
