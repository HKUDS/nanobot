# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

import httpx

from ... import _legacy_response
from ..._types import Body, Omit, Query, Headers, NotGiven, omit, not_given
from ..._utils import maybe_transform, async_maybe_transform
from ..._compat import cached_property
from ..._resource import SyncAPIResource, AsyncAPIResource
from ..._response import to_streamed_response_wrapper, async_to_streamed_response_wrapper
from ..._base_client import make_request_options
from ...types.realtime import client_secret_create_params
from ...types.realtime.client_secret_create_response import ClientSecretCreateResponse

__all__ = ["ClientSecrets", "AsyncClientSecrets"]


class ClientSecrets(SyncAPIResource):
    @cached_property
    def with_raw_response(self) -> ClientSecretsWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return ClientSecretsWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> ClientSecretsWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return ClientSecretsWithStreamingResponse(self)

    def create(
        self,
        *,
        expires_after: client_secret_create_params.ExpiresAfter | Omit = omit,
        session: client_secret_create_params.Session | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ClientSecretCreateResponse:
        """
        Create a Realtime client secret with an associated session configuration.

        Args:
          expires_after: Configuration for the client secret expiration. Expiration refers to the time
              after which a client secret will no longer be valid for creating sessions. The
              session itself may continue after that time once started. A secret can be used
              to create multiple sessions until it expires.

          session: Session configuration to use for the client secret. Choose either a realtime
              session or a transcription session.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        return self._post(
            "/realtime/client_secrets",
            body=maybe_transform(
                {
                    "expires_after": expires_after,
                    "session": session,
                },
                client_secret_create_params.ClientSecretCreateParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ClientSecretCreateResponse,
        )


class AsyncClientSecrets(AsyncAPIResource):
    @cached_property
    def with_raw_response(self) -> AsyncClientSecretsWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return AsyncClientSecretsWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> AsyncClientSecretsWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return AsyncClientSecretsWithStreamingResponse(self)

    async def create(
        self,
        *,
        expires_after: client_secret_create_params.ExpiresAfter | Omit = omit,
        session: client_secret_create_params.Session | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> ClientSecretCreateResponse:
        """
        Create a Realtime client secret with an associated session configuration.

        Args:
          expires_after: Configuration for the client secret expiration. Expiration refers to the time
              after which a client secret will no longer be valid for creating sessions. The
              session itself may continue after that time once started. A secret can be used
              to create multiple sessions until it expires.

          session: Session configuration to use for the client secret. Choose either a realtime
              session or a transcription session.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        return await self._post(
            "/realtime/client_secrets",
            body=await async_maybe_transform(
                {
                    "expires_after": expires_after,
                    "session": session,
                },
                client_secret_create_params.ClientSecretCreateParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=ClientSecretCreateResponse,
        )


class ClientSecretsWithRawResponse:
    def __init__(self, client_secrets: ClientSecrets) -> None:
        self._client_secrets = client_secrets

        self.create = _legacy_response.to_raw_response_wrapper(
            client_secrets.create,
        )


class AsyncClientSecretsWithRawResponse:
    def __init__(self, client_secrets: AsyncClientSecrets) -> None:
        self._client_secrets = client_secrets

        self.create = _legacy_response.async_to_raw_response_wrapper(
            client_secrets.create,
        )


class ClientSecretsWithStreamingResponse:
    def __init__(self, client_secrets: ClientSecrets) -> None:
        self._client_secrets = client_secrets

        self.create = to_streamed_response_wrapper(
            client_secrets.create,
        )


class AsyncClientSecretsWithStreamingResponse:
    def __init__(self, client_secrets: AsyncClientSecrets) -> None:
        self._client_secrets = client_secrets

        self.create = async_to_streamed_response_wrapper(
            client_secrets.create,
        )
