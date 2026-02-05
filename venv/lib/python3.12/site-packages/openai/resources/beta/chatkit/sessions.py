# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

import httpx

from .... import _legacy_response
from ...._types import Body, Omit, Query, Headers, NotGiven, omit, not_given
from ...._utils import maybe_transform, async_maybe_transform
from ...._compat import cached_property
from ...._resource import SyncAPIResource, AsyncAPIResource
from ...._response import to_streamed_response_wrapper, async_to_streamed_response_wrapper
from ...._base_client import make_request_options
from ....types.beta.chatkit import (
    ChatSessionWorkflowParam,
    ChatSessionRateLimitsParam,
    ChatSessionExpiresAfterParam,
    ChatSessionChatKitConfigurationParam,
    session_create_params,
)
from ....types.beta.chatkit.chat_session import ChatSession
from ....types.beta.chatkit.chat_session_workflow_param import ChatSessionWorkflowParam
from ....types.beta.chatkit.chat_session_rate_limits_param import ChatSessionRateLimitsParam
from ....types.beta.chatkit.chat_session_expires_after_param import ChatSessionExpiresAfterParam
from ....types.beta.chatkit.chat_session_chatkit_configuration_param import ChatSessionChatKitConfigurationParam

__all__ = ["Sessions", "AsyncSessions"]


class Sessions(SyncAPIResource):
    @cached_property
    def with_raw_response(self) -> SessionsWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return SessionsWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> SessionsWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return SessionsWithStreamingResponse(self)

    def create(
        self,
        *,
        user: str,
        workflow: ChatSessionWorkflowParam,
        chatkit_configuration: ChatSessionChatKitConfigurationParam | Omit = omit,
        expires_after: ChatSessionExpiresAfterParam | Omit = omit,
        rate_limits: ChatSessionRateLimitsParam | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ChatSession:
        """
        Create a ChatKit session

        Args:
          user: A free-form string that identifies your end user; ensures this Session can
              access other objects that have the same `user` scope.

          workflow: Workflow that powers the session.

          chatkit_configuration: Optional overrides for ChatKit runtime configuration features

          expires_after: Optional override for session expiration timing in seconds from creation.
              Defaults to 10 minutes.

          rate_limits: Optional override for per-minute request limits. When omitted, defaults to 10.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return self._post(
            "/chatkit/sessions",
            body=maybe_transform(
                {
                    "user": user,
                    "workflow": workflow,
                    "chatkit_configuration": chatkit_configuration,
                    "expires_after": expires_after,
                    "rate_limits": rate_limits,
                },
                session_create_params.SessionCreateParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ChatSession,
        )

    def cancel(
        self,
        session_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ChatSession:
        """
        Cancel a ChatKit session

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not session_id:
            raise ValueError(f"Expected a non-empty value for `session_id` but received {session_id!r}")
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return self._post(
            f"/chatkit/sessions/{session_id}/cancel",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ChatSession,
        )


class AsyncSessions(AsyncAPIResource):
    @cached_property
    def with_raw_response(self) -> AsyncSessionsWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return AsyncSessionsWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> AsyncSessionsWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return AsyncSessionsWithStreamingResponse(self)

    async def create(
        self,
        *,
        user: str,
        workflow: ChatSessionWorkflowParam,
        chatkit_configuration: ChatSessionChatKitConfigurationParam | Omit = omit,
        expires_after: ChatSessionExpiresAfterParam | Omit = omit,
        rate_limits: ChatSessionRateLimitsParam | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ChatSession:
        """
        Create a ChatKit session

        Args:
          user: A free-form string that identifies your end user; ensures this Session can
              access other objects that have the same `user` scope.

          workflow: Workflow that powers the session.

          chatkit_configuration: Optional overrides for ChatKit runtime configuration features

          expires_after: Optional override for session expiration timing in seconds from creation.
              Defaults to 10 minutes.

          rate_limits: Optional override for per-minute request limits. When omitted, defaults to 10.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return await self._post(
            "/chatkit/sessions",
            body=await async_maybe_transform(
                {
                    "user": user,
                    "workflow": workflow,
                    "chatkit_configuration": chatkit_configuration,
                    "expires_after": expires_after,
                    "rate_limits": rate_limits,
                },
                session_create_params.SessionCreateParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ChatSession,
        )

    async def cancel(
        self,
        session_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ChatSession:
        """
        Cancel a ChatKit session

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not session_id:
            raise ValueError(f"Expected a non-empty value for `session_id` but received {session_id!r}")
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return await self._post(
            f"/chatkit/sessions/{session_id}/cancel",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ChatSession,
        )


class SessionsWithRawResponse:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

        self.create = _legacy_response.to_raw_response_wrapper(
            sessions.create,
        )
        self.cancel = _legacy_response.to_raw_response_wrapper(
            sessions.cancel,
        )


class AsyncSessionsWithRawResponse:
    def __init__(self, sessions: AsyncSessions) -> None:
        self._sessions = sessions

        self.create = _legacy_response.async_to_raw_response_wrapper(
            sessions.create,
        )
        self.cancel = _legacy_response.async_to_raw_response_wrapper(
            sessions.cancel,
        )


class SessionsWithStreamingResponse:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

        self.create = to_streamed_response_wrapper(
            sessions.create,
        )
        self.cancel = to_streamed_response_wrapper(
            sessions.cancel,
        )


class AsyncSessionsWithStreamingResponse:
    def __init__(self, sessions: AsyncSessions) -> None:
        self._sessions = sessions

        self.create = async_to_streamed_response_wrapper(
            sessions.create,
        )
        self.cancel = async_to_streamed_response_wrapper(
            sessions.cancel,
        )
