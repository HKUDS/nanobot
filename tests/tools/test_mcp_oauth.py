from __future__ import annotations

import asyncio
import inspect
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken

from nanobot.agent.tools.mcp_oauth import (
    MCPAuthorizationRequiredError,
    MCPOAuthHandlers,
    MCPOAuthStorage,
    MCPTokenRefreshError,
    create_mcp_oauth_auth,
    delete_mcp_oauth_credentials,
    mcp_oauth_has_credentials,
)
from nanobot.config.schema import MCPServerConfig


def _use_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.agent.tools.mcp_oauth.get_data_dir", lambda: tmp_path)


def _oauth_metadata() -> OAuthMetadata:
    return OAuthMetadata.model_validate({
        "issuer": "https://auth.example.com",
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/oauth/token",
        "registration_endpoint": "https://auth.example.com/register",
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
    })


def test_refresh_provider_sdk_private_method_contract() -> None:
    """Fail dependency updates loudly while the SDK refresh workaround is needed."""
    expected_parameters = {
        "_initialize": ("self",),
        "_refresh_token": ("self",),
        "_handle_refresh_response": ("self", "response"),
        "_perform_authorization": ("self",),
        "async_auth_flow": ("self", "request"),
    }

    for method_name, expected in expected_parameters.items():
        method = getattr(OAuthClientProvider, method_name)
        assert tuple(inspect.signature(method).parameters) == expected


def test_mcp_server_config_accepts_explicit_oauth() -> None:
    config = MCPServerConfig.model_validate({
        "type": "streamableHttp",
        "url": "https://mcp.example.com/mcp",
        "auth": "oauth",
    })

    assert config.auth == "oauth"
    assert config.model_dump(by_alias=True)["auth"] == "oauth"


@pytest.mark.asyncio
async def test_mcp_oauth_storage_isolates_name_and_server_url(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    storage = MCPOAuthStorage("notion-work", "https://mcp.example.com/mcp")
    tokens = OAuthToken(access_token="access-secret", refresh_token="refresh-secret")
    client_info = OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="client-id",
        client_secret="client-secret",
    )

    await storage.prepare_redirect_uri("https://agent.example/auth/mcp/callback")
    await storage.set_tokens(tokens)
    await storage.set_client_info(client_info)

    assert await storage.get_tokens() == tokens
    assert await storage.get_client_info() == client_info
    assert await storage.redirect_uri() == "https://agent.example/auth/mcp/callback"
    assert mcp_oauth_has_credentials("notion-work", "https://mcp.example.com/mcp")
    assert not mcp_oauth_has_credentials("notion-home", "https://mcp.example.com/mcp")
    assert not mcp_oauth_has_credentials("notion-work", "https://other.example.com/mcp")

    payload = json.loads((tmp_path / "auth" / "mcp.json").read_text(encoding="utf-8"))
    assert "https://mcp.example.com/mcp" not in str(payload)
    assert "access-secret" in str(payload)


@pytest.mark.asyncio
async def test_changed_redirect_uri_discards_dynamic_registration_but_keeps_tokens(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    storage = MCPOAuthStorage("linear", "https://mcp.linear.example/mcp")
    await storage.prepare_redirect_uri("https://old.example/auth/mcp/callback")
    await storage.set_tokens(OAuthToken(access_token="access-secret"))
    await storage.set_client_info(OAuthClientInformationFull(
        redirect_uris=["https://old.example/auth/mcp/callback"],
        client_id="old-client",
    ))

    await storage.prepare_redirect_uri("https://new.example/auth/mcp/callback")

    assert await storage.get_tokens() is not None
    assert await storage.get_client_info() is None


@pytest.mark.asyncio
async def test_reset_and_delete_credentials_are_scoped_to_one_server(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    first = MCPOAuthStorage("first", "https://mcp.example.com/mcp")
    second = MCPOAuthStorage("second", "https://mcp.example.com/mcp")
    await first.set_tokens(OAuthToken(access_token="first-token", expires_in=3600))
    await second.set_tokens(OAuthToken(access_token="second-token"))

    await first.prepare_redirect_uri(
        "https://agent.example/auth/mcp/callback",
        reset=True,
    )

    assert await first.get_tokens() is None
    assert await first.get_token_expiry() is None
    assert await second.get_tokens() is not None
    assert delete_mcp_oauth_credentials("first")
    assert not delete_mcp_oauth_credentials("first")
    assert await second.get_tokens() is not None


@pytest.mark.asyncio
async def test_deleted_credentials_reject_late_writes_from_stale_oauth_flow(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.linear.example/mcp"
    stale = MCPOAuthStorage("linear", server_url)
    await stale.prepare_redirect_uri("https://old.example/auth/mcp/callback")

    assert delete_mcp_oauth_credentials("linear")
    await stale.set_tokens(OAuthToken(access_token="late-after-delete"))
    assert not mcp_oauth_has_credentials("linear", server_url)

    replacement = MCPOAuthStorage("linear", server_url)
    await replacement.prepare_redirect_uri("https://new.example/auth/mcp/callback")
    await stale.set_tokens(OAuthToken(access_token="late-after-replacement"))

    assert not mcp_oauth_has_credentials("linear", server_url)
    assert await replacement.get_tokens() is None

    await replacement.set_tokens(OAuthToken(access_token="fresh-token"))
    stored = await replacement.get_tokens()
    assert stored is not None
    assert stored.access_token == "fresh-token"


@pytest.mark.asyncio
async def test_delete_before_oauth_claim_rejects_late_credential_writes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.linear.example/mcp"
    stale = MCPOAuthStorage("linear", server_url)

    assert not delete_mcp_oauth_credentials("linear")
    with pytest.raises(MCPAuthorizationRequiredError, match="cancelled"):
        await stale.prepare_redirect_uri("https://old.example/auth/mcp/callback")
    await stale.set_tokens(OAuthToken(access_token="late-after-delete"))
    assert not mcp_oauth_has_credentials("linear", server_url)

    replacement = MCPOAuthStorage("linear", server_url)
    await replacement.prepare_redirect_uri("https://new.example/auth/mcp/callback")
    await replacement.set_tokens(OAuthToken(access_token="fresh-token"))
    assert mcp_oauth_has_credentials("linear", server_url)


@pytest.mark.asyncio
async def test_create_mcp_oauth_auth_uses_browser_handlers_and_persists_redirect(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)

    async def redirect(_url: str) -> None:
        return None

    async def callback() -> tuple[str, str | None]:
        return "code", "state"

    handlers = MCPOAuthHandlers(
        redirect_uri="https://agent.example/auth/mcp/callback",
        redirect_handler=redirect,
        callback_handler=callback,
    )

    auth = await create_mcp_oauth_auth(
        "xmind",
        "https://app.xmind.example/api/mcp",
        handlers,
    )

    assert str(auth.context.client_metadata.redirect_uris[0]) == (
        "https://agent.example/auth/mcp/callback"
    )
    assert str(auth.context.client_metadata.client_uri) == "https://github.com/HKUDS/nanobot"
    assert str(auth.context.client_metadata.logo_uri) == (
        "https://raw.githubusercontent.com/HKUDS/nanobot/main/"
        "webui/public/brand/nanobot_apple_touch.png"
    )
    assert auth.context.redirect_handler is redirect
    assert auth.context.callback_handler is callback
    storage = MCPOAuthStorage("xmind", "https://app.xmind.example/api/mcp")
    assert await storage.redirect_uri() == "https://agent.example/auth/mcp/callback"


@pytest.mark.asyncio
async def test_background_authorization_without_tokens_stops_locally(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)

    with pytest.raises(MCPAuthorizationRequiredError):
        await create_mcp_oauth_auth("notion", "https://mcp.notion.example/mcp")

    assert not (tmp_path / "auth" / "mcp.json").exists()


@pytest.mark.asyncio
async def test_background_authorization_request_clears_rejected_token(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    storage = MCPOAuthStorage("notion", server_url)
    client_info = OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="registered-client",
    )
    await storage.set_tokens(OAuthToken(access_token="rejected-token"))
    await storage.set_client_info(client_info)
    auth = await create_mcp_oauth_auth("notion", server_url)

    redirect_handler = auth.context.redirect_handler
    assert redirect_handler is not None
    with pytest.raises(MCPAuthorizationRequiredError):
        await redirect_handler("https://accounts.example.com/authorize?state=state")

    assert await storage.get_tokens() is None
    assert await storage.get_client_info() == client_info


@pytest.mark.asyncio
async def test_expired_token_refreshes_from_persisted_metadata_after_restart(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    storage = MCPOAuthStorage("linear", server_url)
    await storage.set_tokens(OAuthToken(
        access_token="expired-access",
        refresh_token="refresh-token",
        expires_in=-1,
    ))
    await storage.set_client_info(OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="registered-client",
    ))
    await storage.set_oauth_metadata(_oauth_metadata())
    auth = await create_mcp_oauth_auth("linear", server_url)
    requests: list[tuple[str, str]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        if request.url.path == "/oauth/token":
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == ["refresh-token"]
            return httpx.Response(200, json={
                "access_token": "fresh-access",
                "refresh_token": "rotated-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            })
        assert request.headers["Authorization"] == "Bearer fresh-access"
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), auth=auth) as client:
        response = await client.get(server_url)

    assert response.status_code == 200
    assert requests == [
        ("POST", "https://auth.example.com/oauth/token"),
        ("GET", server_url),
    ]
    stored = await MCPOAuthStorage("linear", server_url).get_tokens()
    assert stored is not None
    assert stored.access_token == "fresh-access"
    assert stored.refresh_token == "rotated-refresh"
    lock = storage.refresh_lock()
    await asyncio.wait_for(lock.acquire(), timeout=1)
    await lock.release()


@pytest.mark.asyncio
async def test_legacy_token_refreshes_after_401_discovers_endpoint(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    storage = MCPOAuthStorage("linear", server_url)
    await storage.set_tokens(OAuthToken(
        access_token="stale-access",
        refresh_token="refresh-token",
    ))
    await storage.set_client_info(OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="registered-client",
    ))
    auth = await create_mcp_oauth_auth("linear", server_url)
    resource_requests = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal resource_requests
        if str(request.url) == server_url:
            resource_requests += 1
            if request.headers.get("Authorization") == "Bearer fresh-access":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(401, headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="https://mcp.example.com/'
                    '.well-known/oauth-protected-resource"'
                )
            })
        if request.url.path == "/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={
                "resource": server_url,
                "authorization_servers": ["https://auth.example.com"],
            })
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=_oauth_metadata().model_dump(mode="json"))
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={
                "access_token": "fresh-access",
                "refresh_token": "rotated-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            })
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), auth=auth) as client:
        response = await client.get(server_url)

    assert response.status_code == 200
    assert resource_requests == 2
    reloaded = MCPOAuthStorage("linear", server_url)
    assert await reloaded.get_oauth_metadata() == _oauth_metadata()
    stored = await reloaded.get_tokens()
    assert stored is not None
    assert stored.refresh_token == "rotated-refresh"


@pytest.mark.asyncio
async def test_transient_refresh_failure_preserves_credentials(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    storage = MCPOAuthStorage("linear", server_url)
    original = OAuthToken(
        access_token="expired-access",
        refresh_token="refresh-token",
        expires_in=-1,
    )
    await storage.set_tokens(original)
    await storage.set_client_info(OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="registered-client",
    ))
    await storage.set_oauth_metadata(_oauth_metadata())
    auth = await create_mcp_oauth_auth("linear", server_url)

    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="temporarily unavailable")

    with pytest.raises(MCPTokenRefreshError, match="will retry later"):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            auth=auth,
        ) as client:
            await client.get(server_url)

    stored = await MCPOAuthStorage("linear", server_url).get_tokens()
    assert stored == original


@pytest.mark.asyncio
async def test_stale_token_endpoint_is_rediscovered_once(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    storage = MCPOAuthStorage("linear", server_url)
    await storage.set_tokens(OAuthToken(
        access_token="expired-access",
        refresh_token="refresh-token",
        expires_in=-1,
    ))
    await storage.set_client_info(OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="registered-client",
    ))
    stale_payload = _oauth_metadata().model_dump(mode="json")
    stale_payload["token_endpoint"] = "https://auth.example.com/old/token"
    stale_metadata = OAuthMetadata.model_validate(stale_payload)
    await storage.set_oauth_metadata(stale_metadata)
    auth = await create_mcp_oauth_auth("linear", server_url)
    refresh_urls: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old/token":
            refresh_urls.append(str(request.url))
            return httpx.Response(404)
        if str(request.url) == server_url:
            if request.headers.get("Authorization") == "Bearer fresh-access":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(401, headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="https://mcp.example.com/'
                    '.well-known/oauth-protected-resource"'
                )
            })
        if request.url.path == "/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={
                "resource": server_url,
                "authorization_servers": ["https://auth.example.com"],
            })
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=_oauth_metadata().model_dump(mode="json"))
        if request.url.path == "/oauth/token":
            refresh_urls.append(str(request.url))
            return httpx.Response(200, json={
                "access_token": "fresh-access",
                "refresh_token": "rotated-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            })
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), auth=auth) as client:
        response = await client.get(server_url)

    assert response.status_code == 200
    assert refresh_urls == [
        "https://auth.example.com/old/token",
        "https://auth.example.com/oauth/token",
    ]
    assert await MCPOAuthStorage("linear", server_url).get_oauth_metadata() == _oauth_metadata()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "clears_client"),
    [("invalid_grant", False), ("invalid_client", True)],
)
async def test_unrecoverable_refresh_error_requires_authorization(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    error: str,
    clears_client: bool,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    storage = MCPOAuthStorage("linear", server_url)
    await storage.set_tokens(OAuthToken(
        access_token="expired-access",
        refresh_token="rejected-refresh",
        expires_in=-1,
    ))
    await storage.set_client_info(OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="registered-client",
    ))
    await storage.set_oauth_metadata(_oauth_metadata())
    auth = await create_mcp_oauth_auth("linear", server_url)

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(400, json={"error": error})
        if str(request.url) == server_url:
            return httpx.Response(401, headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="https://mcp.example.com/'
                    '.well-known/oauth-protected-resource"'
                )
            })
        if request.url.path == "/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={
                "resource": server_url,
                "authorization_servers": ["https://auth.example.com"],
            })
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=_oauth_metadata().model_dump(mode="json"))
        if request.url.path == "/register":
            return httpx.Response(201, json={
                "client_id": "replacement-client",
                "redirect_uris": ["http://127.0.0.1/auth/mcp/callback"],
                "token_endpoint_auth_method": "none",
            })
        return httpx.Response(404)

    with pytest.raises(MCPAuthorizationRequiredError):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            auth=auth,
        ) as client:
            await client.get(server_url)

    reloaded = MCPOAuthStorage("linear", server_url)
    assert await reloaded.get_tokens() is None
    client_info = await reloaded.get_client_info()
    assert client_info is not None
    assert client_info.client_id == (
        "replacement-client" if clears_client else "registered-client"
    )
    lock = storage.refresh_lock()
    await asyncio.wait_for(lock.acquire(), timeout=1)
    await lock.release()


@pytest.mark.asyncio
async def test_concurrent_expired_requests_share_one_refresh(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    storage = MCPOAuthStorage("linear", server_url)
    await storage.set_tokens(OAuthToken(
        access_token="expired-access",
        refresh_token="refresh-token",
        expires_in=-1,
    ))
    await storage.set_client_info(OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="registered-client",
    ))
    await storage.set_oauth_metadata(_oauth_metadata())
    auth = await create_mcp_oauth_auth("linear", server_url)
    refresh_requests = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_requests
        if request.url.path == "/oauth/token":
            refresh_requests += 1
            await asyncio.sleep(0.01)
            return httpx.Response(200, json={
                "access_token": "fresh-access",
                "refresh_token": "rotated-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            })
        assert request.headers["Authorization"] == "Bearer fresh-access"
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), auth=auth) as client:
        responses = await asyncio.gather(client.get(server_url), client.get(server_url))

    assert [response.status_code for response in responses] == [200, 200]
    assert refresh_requests == 1


@pytest.mark.asyncio
async def test_separate_providers_share_storage_refresh_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    storage = MCPOAuthStorage("linear", server_url)
    await storage.set_tokens(OAuthToken(
        access_token="expired-access",
        refresh_token="refresh-token",
        expires_in=-1,
    ))
    await storage.set_client_info(OAuthClientInformationFull(
        redirect_uris=["https://agent.example/auth/mcp/callback"],
        client_id="registered-client",
    ))
    await storage.set_oauth_metadata(_oauth_metadata())
    first_auth = await create_mcp_oauth_auth("linear", server_url)
    second_auth = await create_mcp_oauth_auth("linear", server_url)
    refresh_requests = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_requests
        if request.url.path == "/oauth/token":
            refresh_requests += 1
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={
                "access_token": "fresh-access",
                "refresh_token": "rotated-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            })
        assert request.headers["Authorization"] == "Bearer fresh-access"
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(respond)
    async with (
        httpx.AsyncClient(transport=transport, auth=first_auth) as first_client,
        httpx.AsyncClient(transport=transport, auth=second_auth) as second_client,
    ):
        responses = await asyncio.gather(
            first_client.get(server_url),
            second_client.get(server_url),
        )

    assert [response.status_code for response in responses] == [200, 200]
    assert refresh_requests == 1
    stored = await MCPOAuthStorage("linear", server_url).get_tokens()
    assert stored is not None
    assert stored.refresh_token == "rotated-refresh"


@pytest.mark.asyncio
async def test_official_mcp_sdk_completes_discovery_registration_and_token_exchange(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_data_dir(tmp_path, monkeypatch)
    server_url = "https://mcp.example.com/mcp"
    authorization_url = ""
    requests: list[tuple[str, str]] = []

    async def redirect(url: str) -> None:
        nonlocal authorization_url
        authorization_url = url

    async def callback() -> tuple[str, str | None]:
        state = parse_qs(urlsplit(authorization_url).query)["state"][0]
        return "authorization-code", state

    auth = await create_mcp_oauth_auth(
        "company-mcp",
        server_url,
        MCPOAuthHandlers(
            redirect_uri="https://agent.example/auth/mcp/callback",
            redirect_handler=redirect,
            callback_handler=callback,
        ),
    )

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        if str(request.url) == server_url:
            if request.headers.get("Authorization") == "Bearer access-token":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata="https://mcp.example.com/'
                        '.well-known/oauth-protected-resource"'
                    )
                },
            )
        if request.url.path == "/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={
                "resource": server_url,
                "authorization_servers": ["https://auth.example.com"],
            })
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "registration_endpoint": "https://auth.example.com/register",
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
            })
        if request.url.path == "/register":
            registration = json.loads(request.content)
            assert registration["client_uri"] == "https://github.com/HKUDS/nanobot"
            assert registration["logo_uri"].endswith(
                "/webui/public/brand/nanobot_apple_touch.png"
            )
            return httpx.Response(201, json={
                "client_id": "nanobot-client",
                "redirect_uris": ["https://agent.example/auth/mcp/callback"],
                "token_endpoint_auth_method": "none",
            })
        if request.url.path == "/token":
            return httpx.Response(200, json={
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            })
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        auth=auth,
    ) as client:
        response = await client.get(server_url)

    assert response.status_code == 200
    assert urlsplit(authorization_url)._replace(query="").geturl() == (
        "https://auth.example.com/authorize"
    )
    assert ("POST", "https://auth.example.com/register") in requests
    assert ("POST", "https://auth.example.com/token") in requests
    stored = await MCPOAuthStorage("company-mcp", server_url).get_tokens()
    assert stored is not None
    assert stored.access_token == "access-token"
    assert stored.refresh_token == "refresh-token"
