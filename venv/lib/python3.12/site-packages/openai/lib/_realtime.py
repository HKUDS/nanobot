from __future__ import annotations

import json
from typing_extensions import override

import httpx

from openai import _legacy_response
from openai._types import Body, Omit, Query, Headers, NotGiven, omit, not_given
from openai._utils import maybe_transform, async_maybe_transform
from openai._base_client import make_request_options
from openai.resources.realtime.calls import Calls, AsyncCalls
from openai.types.realtime.realtime_session_create_request_param import RealtimeSessionCreateRequestParam

__all__ = ["_Calls", "_AsyncCalls"]


# Custom code to override the `create` method to have correct behavior with
# application/sdp and multipart/form-data.
# Ideally we can cutover to the generated code this overrides eventually and remove this.
class _Calls(Calls):
    @override
    def create(
        self,
        *,
        sdp: str,
        session: RealtimeSessionCreateRequestParam | Omit = omit,
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> _legacy_response.HttpxBinaryResponseContent:
        if session is omit:
            extra_headers = {"Accept": "application/sdp", "Content-Type": "application/sdp", **(extra_headers or {})}
            return self._post(
                "/realtime/calls",
                content=sdp.encode("utf-8"),
                options=make_request_options(extra_headers=extra_headers, extra_query=extra_query, timeout=timeout),
                cast_to=_legacy_response.HttpxBinaryResponseContent,
            )

        extra_headers = {"Accept": "application/sdp", "Content-Type": "multipart/form-data", **(extra_headers or {})}
        session_payload = maybe_transform(session, RealtimeSessionCreateRequestParam)
        files = [
            ("sdp", (None, sdp.encode("utf-8"), "application/sdp")),
            ("session", (None, json.dumps(session_payload).encode("utf-8"), "application/json")),
        ]
        return self._post(
            "/realtime/calls",
            files=files,
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=_legacy_response.HttpxBinaryResponseContent,
        )


class _AsyncCalls(AsyncCalls):
    @override
    async def create(
        self,
        *,
        sdp: str,
        session: RealtimeSessionCreateRequestParam | Omit = omit,
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> _legacy_response.HttpxBinaryResponseContent:
        if session is omit:
            extra_headers = {"Accept": "application/sdp", "Content-Type": "application/sdp", **(extra_headers or {})}
            return await self._post(
                "/realtime/calls",
                content=sdp.encode("utf-8"),
                options=make_request_options(extra_headers=extra_headers, extra_query=extra_query, timeout=timeout),
                cast_to=_legacy_response.HttpxBinaryResponseContent,
            )

        extra_headers = {"Accept": "application/sdp", "Content-Type": "multipart/form-data", **(extra_headers or {})}
        session_payload = await async_maybe_transform(session, RealtimeSessionCreateRequestParam)
        files = [
            ("sdp", (None, sdp.encode("utf-8"), "application/sdp")),
            ("session", (None, json.dumps(session_payload).encode("utf-8"), "application/json")),
        ]
        return await self._post(
            "/realtime/calls",
            files=files,
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=_legacy_response.HttpxBinaryResponseContent,
        )
