"""Bounded HTTP GET execution for resources selected by a caller."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from urllib.parse import urljoin

import httpx

from nanobot.security.network import UnsafeURLRequestError

MAX_REDIRECTS = 5


class RedirectLimitError(ValueError):
    """The response did not reach its destination within the redirect budget."""


@asynccontextmanager
async def open_redirected_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    check_target: Callable[[str], tuple[bool, str]] | None,
    user_agent: str | None = None,
) -> AsyncGenerator[tuple[httpx.Response, tuple[str, ...]], None]:
    """Open the final response, closing every hop and retaining its URL chain.

    Provide a URL check for any route not guarded by the client's transport.
    Use None only when the transport itself validates and pins every request.
    """
    chain = [url]
    headers = {"User-Agent": user_agent} if user_agent is not None else None
    for _ in range(MAX_REDIRECTS + 1):
        target = chain[-1]
        if check_target is not None:
            ok, error = check_target(target)
            if not ok:
                raise UnsafeURLRequestError(error)
        async with client.stream("GET", target, headers=headers, follow_redirects=False) as response:
            location = response.headers.get("location") if 300 <= response.status_code < 400 else None
            if not location:
                yield response, tuple(chain)
                return
            chain.append(urljoin(str(response.url), location))
    raise RedirectLimitError(f"Too many redirects: exceeded limit of {MAX_REDIRECTS}")
