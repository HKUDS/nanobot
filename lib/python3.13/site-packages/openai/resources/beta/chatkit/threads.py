# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Any, cast
from typing_extensions import Literal

import httpx

from .... import _legacy_response
from ...._types import Body, Omit, Query, Headers, NotGiven, omit, not_given
from ...._utils import maybe_transform
from ...._compat import cached_property
from ...._resource import SyncAPIResource, AsyncAPIResource
from ...._response import to_streamed_response_wrapper, async_to_streamed_response_wrapper
from ....pagination import SyncConversationCursorPage, AsyncConversationCursorPage
from ...._base_client import AsyncPaginator, make_request_options
from ....types.beta.chatkit import thread_list_params, thread_list_items_params
from ....types.beta.chatkit.chatkit_thread import ChatKitThread
from ....types.beta.chatkit.thread_delete_response import ThreadDeleteResponse
from ....types.beta.chatkit.chatkit_thread_item_list import Data

__all__ = ["Threads", "AsyncThreads"]


class Threads(SyncAPIResource):
    @cached_property
    def with_raw_response(self) -> ThreadsWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return ThreadsWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> ThreadsWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return ThreadsWithStreamingResponse(self)

    def retrieve(
        self,
        thread_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ChatKitThread:
        """
        Retrieve a ChatKit thread

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not thread_id:
            raise ValueError(f"Expected a non-empty value for `thread_id` but received {thread_id!r}")
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return self._get(
            f"/chatkit/threads/{thread_id}",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ChatKitThread,
        )

    def list(
        self,
        *,
        after: str | Omit = omit,
        before: str | Omit = omit,
        limit: int | Omit = omit,
        order: Literal["asc", "desc"] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> SyncConversationCursorPage[ChatKitThread]:
        """
        List ChatKit threads

        Args:
          after: List items created after this thread item ID. Defaults to null for the first
              page.

          before: List items created before this thread item ID. Defaults to null for the newest
              results.

          limit: Maximum number of thread items to return. Defaults to 20.

          order: Sort order for results by creation time. Defaults to `desc`.

          user: Filter threads that belong to this user identifier. Defaults to null to return
              all users.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return self._get_api_list(
            "/chatkit/threads",
            page=SyncConversationCursorPage[ChatKitThread],
            options=make_request_options(
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
                query=maybe_transform(
                    {
                        "after": after,
                        "before": before,
                        "limit": limit,
                        "order": order,
                        "user": user,
                    },
                    thread_list_params.ThreadListParams,
                ),
            ),
            model=ChatKitThread,
        )

    def delete(
        self,
        thread_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ThreadDeleteResponse:
        """
        Delete a ChatKit thread

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not thread_id:
            raise ValueError(f"Expected a non-empty value for `thread_id` but received {thread_id!r}")
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return self._delete(
            f"/chatkit/threads/{thread_id}",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ThreadDeleteResponse,
        )

    def list_items(
        self,
        thread_id: str,
        *,
        after: str | Omit = omit,
        before: str | Omit = omit,
        limit: int | Omit = omit,
        order: Literal["asc", "desc"] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> SyncConversationCursorPage[Data]:
        """
        List ChatKit thread items

        Args:
          after: List items created after this thread item ID. Defaults to null for the first
              page.

          before: List items created before this thread item ID. Defaults to null for the newest
              results.

          limit: Maximum number of thread items to return. Defaults to 20.

          order: Sort order for results by creation time. Defaults to `desc`.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not thread_id:
            raise ValueError(f"Expected a non-empty value for `thread_id` but received {thread_id!r}")
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return self._get_api_list(
            f"/chatkit/threads/{thread_id}/items",
            page=SyncConversationCursorPage[Data],
            options=make_request_options(
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
                query=maybe_transform(
                    {
                        "after": after,
                        "before": before,
                        "limit": limit,
                        "order": order,
                    },
                    thread_list_items_params.ThreadListItemsParams,
                ),
            ),
            model=cast(Any, Data),  # Union types cannot be passed in as arguments in the type system
        )


class AsyncThreads(AsyncAPIResource):
    @cached_property
    def with_raw_response(self) -> AsyncThreadsWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return AsyncThreadsWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> AsyncThreadsWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return AsyncThreadsWithStreamingResponse(self)

    async def retrieve(
        self,
        thread_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ChatKitThread:
        """
        Retrieve a ChatKit thread

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not thread_id:
            raise ValueError(f"Expected a non-empty value for `thread_id` but received {thread_id!r}")
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return await self._get(
            f"/chatkit/threads/{thread_id}",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ChatKitThread,
        )

    def list(
        self,
        *,
        after: str | Omit = omit,
        before: str | Omit = omit,
        limit: int | Omit = omit,
        order: Literal["asc", "desc"] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> AsyncPaginator[ChatKitThread, AsyncConversationCursorPage[ChatKitThread]]:
        """
        List ChatKit threads

        Args:
          after: List items created after this thread item ID. Defaults to null for the first
              page.

          before: List items created before this thread item ID. Defaults to null for the newest
              results.

          limit: Maximum number of thread items to return. Defaults to 20.

          order: Sort order for results by creation time. Defaults to `desc`.

          user: Filter threads that belong to this user identifier. Defaults to null to return
              all users.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return self._get_api_list(
            "/chatkit/threads",
            page=AsyncConversationCursorPage[ChatKitThread],
            options=make_request_options(
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
                query=maybe_transform(
                    {
                        "after": after,
                        "before": before,
                        "limit": limit,
                        "order": order,
                        "user": user,
                    },
                    thread_list_params.ThreadListParams,
                ),
            ),
            model=ChatKitThread,
        )

    async def delete(
        self,
        thread_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ThreadDeleteResponse:
        """
        Delete a ChatKit thread

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not thread_id:
            raise ValueError(f"Expected a non-empty value for `thread_id` but received {thread_id!r}")
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return await self._delete(
            f"/chatkit/threads/{thread_id}",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ThreadDeleteResponse,
        )

    def list_items(
        self,
        thread_id: str,
        *,
        after: str | Omit = omit,
        before: str | Omit = omit,
        limit: int | Omit = omit,
        order: Literal["asc", "desc"] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> AsyncPaginator[Data, AsyncConversationCursorPage[Data]]:
        """
        List ChatKit thread items

        Args:
          after: List items created after this thread item ID. Defaults to null for the first
              page.

          before: List items created before this thread item ID. Defaults to null for the newest
              results.

          limit: Maximum number of thread items to return. Defaults to 20.

          order: Sort order for results by creation time. Defaults to `desc`.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not thread_id:
            raise ValueError(f"Expected a non-empty value for `thread_id` but received {thread_id!r}")
        extra_headers = {"OpenAI-Beta": "chatkit_beta=v1", **(extra_headers or {})}
        return self._get_api_list(
            f"/chatkit/threads/{thread_id}/items",
            page=AsyncConversationCursorPage[Data],
            options=make_request_options(
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
                query=maybe_transform(
                    {
                        "after": after,
                        "before": before,
                        "limit": limit,
                        "order": order,
                    },
                    thread_list_items_params.ThreadListItemsParams,
                ),
            ),
            model=cast(Any, Data),  # Union types cannot be passed in as arguments in the type system
        )


class ThreadsWithRawResponse:
    def __init__(self, threads: Threads) -> None:
        self._threads = threads

        self.retrieve = _legacy_response.to_raw_response_wrapper(
            threads.retrieve,
        )
        self.list = _legacy_response.to_raw_response_wrapper(
            threads.list,
        )
        self.delete = _legacy_response.to_raw_response_wrapper(
            threads.delete,
        )
        self.list_items = _legacy_response.to_raw_response_wrapper(
            threads.list_items,
        )


class AsyncThreadsWithRawResponse:
    def __init__(self, threads: AsyncThreads) -> None:
        self._threads = threads

        self.retrieve = _legacy_response.async_to_raw_response_wrapper(
            threads.retrieve,
        )
        self.list = _legacy_response.async_to_raw_response_wrapper(
            threads.list,
        )
        self.delete = _legacy_response.async_to_raw_response_wrapper(
            threads.delete,
        )
        self.list_items = _legacy_response.async_to_raw_response_wrapper(
            threads.list_items,
        )


class ThreadsWithStreamingResponse:
    def __init__(self, threads: Threads) -> None:
        self._threads = threads

        self.retrieve = to_streamed_response_wrapper(
            threads.retrieve,
        )
        self.list = to_streamed_response_wrapper(
            threads.list,
        )
        self.delete = to_streamed_response_wrapper(
            threads.delete,
        )
        self.list_items = to_streamed_response_wrapper(
            threads.list_items,
        )


class AsyncThreadsWithStreamingResponse:
    def __init__(self, threads: AsyncThreads) -> None:
        self._threads = threads

        self.retrieve = async_to_streamed_response_wrapper(
            threads.retrieve,
        )
        self.list = async_to_streamed_response_wrapper(
            threads.list,
        )
        self.delete = async_to_streamed_response_wrapper(
            threads.delete,
        )
        self.list_items = async_to_streamed_response_wrapper(
            threads.list_items,
        )
