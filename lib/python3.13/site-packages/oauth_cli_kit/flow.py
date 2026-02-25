"""OAuth login and token management."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import urllib.parse
import webbrowser
from typing import Callable

import httpx

from oauth_cli_kit.models import OAuthProviderConfig, OAuthToken
from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
from oauth_cli_kit.pkce import (
    _create_state,
    _decode_account_id,
    _generate_pkce,
    _parse_authorization_input,
    _parse_token_payload,
)
from oauth_cli_kit.server import _start_local_server
from oauth_cli_kit.storage import FileTokenStorage, TokenStorage, _FileLock


def _exchange_code_for_token_async(
    code: str,
    verifier: str,
    provider: OAuthProviderConfig,
) -> Callable[[], OAuthToken]:
    async def _run() -> OAuthToken:
        data = {
            "grant_type": "authorization_code",
            "client_id": provider.client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": provider.redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                provider.token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code != 200:
            raise RuntimeError(f"Token exchange failed: {response.status_code} {response.text}")

        payload = response.json()
        access, refresh, expires_in = _parse_token_payload(payload, "Token response missing fields")

        account_id = _decode_account_id(access, provider.jwt_claim_path, provider.account_id_claim)
        return OAuthToken(
            access=access,
            refresh=refresh,
            expires=int(time.time() * 1000 + expires_in * 1000),
            account_id=account_id,
        )

    return _run


def _refresh_token(refresh_token: str, provider: OAuthProviderConfig) -> OAuthToken:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": provider.client_id,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            provider.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Token refresh failed: {response.status_code} {response.text}")

    payload = response.json()
    access, refresh, expires_in = _parse_token_payload(payload, "Token refresh response missing fields")

    account_id = _decode_account_id(access, provider.jwt_claim_path, provider.account_id_claim)
    return OAuthToken(
        access=access,
        refresh=refresh,
        expires=int(time.time() * 1000 + expires_in * 1000),
        account_id=account_id,
    )


def get_token(
    provider: OAuthProviderConfig = OPENAI_CODEX_PROVIDER,
    storage: TokenStorage | None = None,
    min_ttl_seconds: int = 60,
) -> OAuthToken:
    """Get an available token (refresh if needed)."""
    storage = storage or FileTokenStorage(token_filename=provider.token_filename)
    token = storage.load()
    if not token:
        raise RuntimeError("OAuth credentials not found. Please run the login command.")

    # Refresh early.
    now_ms = int(time.time() * 1000)
    if token.expires - now_ms > min_ttl_seconds * 1000:
        return token

    lock_path = storage.get_token_path().with_suffix(".lock")
    with _FileLock(lock_path):
        # Re-read to avoid stale token if another process refreshed it.
        token = storage.load() or token
        now_ms = int(time.time() * 1000)
        if token.expires - now_ms > min_ttl_seconds * 1000:
            return token
        try:
            refreshed = _refresh_token(token.refresh, provider)
            storage.save(refreshed)
            return refreshed
        except Exception:
            # If refresh fails, re-read the file to avoid false negatives.
            latest = storage.load()
            if latest and latest.expires - now_ms > 0:
                return latest
            raise


async def _read_stdin_line() -> str:
    loop = asyncio.get_running_loop()
    if hasattr(loop, "add_reader") and sys.stdin:
        future: asyncio.Future[str] = loop.create_future()

        def _on_readable() -> None:
            line = sys.stdin.readline()
            if not future.done():
                future.set_result(line)

        try:
            loop.add_reader(sys.stdin, _on_readable)
        except Exception:
            return await loop.run_in_executor(None, sys.stdin.readline)

        try:
            return await future
        finally:
            try:
                loop.remove_reader(sys.stdin)
            except Exception:
                pass

    return await loop.run_in_executor(None, sys.stdin.readline)


async def _await_manual_input(print_fn: Callable[[str], None]) -> str:
    print_fn("[cyan]Paste the authorization code (or full redirect URL), or wait for the browser callback:[/cyan]")
    return await _read_stdin_line()


def login_oauth_interactive(
    print_fn: Callable[[str], None],
    prompt_fn: Callable[[str], str],
    provider: OAuthProviderConfig = OPENAI_CODEX_PROVIDER,
    originator: str | None = None,
    storage: TokenStorage | None = None,
) -> OAuthToken:
    """Interactive login flow."""

    async def _login_async() -> OAuthToken:
        verifier, challenge = _generate_pkce()
        state = _create_state()

        params = {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": provider.redirect_uri,
            "scope": provider.scope,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": originator or provider.default_originator,
        }
        url = f"{provider.authorize_url}?{urllib.parse.urlencode(params)}"

        loop = asyncio.get_running_loop()
        code_future: asyncio.Future[str] = loop.create_future()

        def _notify(code_value: str) -> None:
            if code_future.done():
                return
            loop.call_soon_threadsafe(code_future.set_result, code_value)

        server, server_error = _start_local_server(state, on_code=_notify)
        print_fn("[cyan]A browser window will open for login. If it doesn't, open this URL manually:[/cyan]")
        print_fn(url)
        try:
            webbrowser.open(url)
        except Exception:
            pass

        if not server and server_error:
            print_fn(
                "[yellow]"
                f"Local callback server could not start ({server_error}). "
                "You will need to paste the callback URL or authorization code."
                "[/yellow]"
            )

        code: str | None = None
        try:
            if server:
                print_fn("[dim]Waiting for browser callback...[/dim]")

                tasks: list[asyncio.Task[object]] = []
                callback_task = asyncio.create_task(asyncio.wait_for(code_future, timeout=120))
                tasks.append(callback_task)
                manual_task = asyncio.create_task(_await_manual_input(print_fn))
                tasks.append(manual_task)

                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()

                for task in done:
                    try:
                        result = task.result()
                    except asyncio.TimeoutError:
                        result = None
                    if not result:
                        continue
                    if task is manual_task:
                        parsed_code, parsed_state = _parse_authorization_input(result)
                        if parsed_state and parsed_state != state:
                            raise RuntimeError("State validation failed.")
                        code = parsed_code
                    else:
                        code = result
                    if code:
                        break

            if not code:
                prompt = "Please paste the callback URL or authorization code:"
                raw = await loop.run_in_executor(None, prompt_fn, prompt)
                parsed_code, parsed_state = _parse_authorization_input(raw)
                if parsed_state and parsed_state != state:
                    raise RuntimeError("State validation failed.")
                code = parsed_code

            if not code:
                raise RuntimeError("Authorization code not found.")

            print_fn("[dim]Exchanging authorization code for tokens...[/dim]")
            token = await _exchange_code_for_token_async(code, verifier, provider)()
            (storage or FileTokenStorage(token_filename=provider.token_filename)).save(token)
            return token
        finally:
            if server:
                server.shutdown()
                server.server_close()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_login_async())

    result: list[OAuthToken] = []
    error: list[Exception] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(_login_async()))
        except Exception as exc:
            error.append(exc)

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


# Backward-compatible aliases.
login_codex_oauth_interactive = login_oauth_interactive
get_codex_token = get_token
