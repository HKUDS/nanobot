# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Iterable, Optional
from typing_extensions import Literal

import httpx

from ... import _legacy_response
from ..._types import Body, Omit, Query, Headers, NotGiven, omit, not_given
from ..._utils import maybe_transform, async_maybe_transform
from ..._compat import cached_property
from ..._resource import SyncAPIResource, AsyncAPIResource
from ..._response import to_streamed_response_wrapper, async_to_streamed_response_wrapper
from ..._base_client import make_request_options
from ...types.responses import input_token_count_params
from ...types.responses.tool_param import ToolParam
from ...types.shared_params.reasoning import Reasoning
from ...types.responses.response_input_item_param import ResponseInputItemParam
from ...types.responses.input_token_count_response import InputTokenCountResponse

__all__ = ["InputTokens", "AsyncInputTokens"]


class InputTokens(SyncAPIResource):
    @cached_property
    def with_raw_response(self) -> InputTokensWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return InputTokensWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> InputTokensWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return InputTokensWithStreamingResponse(self)

    def count(
        self,
        *,
        conversation: Optional[input_token_count_params.Conversation] | Omit = omit,
        input: Union[str, Iterable[ResponseInputItemParam], None] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        model: Optional[str] | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        text: Optional[input_token_count_params.Text] | Omit = omit,
        tool_choice: Optional[input_token_count_params.ToolChoice] | Omit = omit,
        tools: Optional[Iterable[ToolParam]] | Omit = omit,
        truncation: Literal["auto", "disabled"] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> InputTokenCountResponse:
        """
        Get input token counts

        Args:
          conversation: The conversation that this response belongs to. Items from this conversation are
              prepended to `input_items` for this response request. Input items and output
              items from this response are automatically added to this conversation after this
              response completes.

          input: Text, image, or file inputs to the model, used to generate a response

          instructions: A system (or developer) message inserted into the model's context. When used
              along with `previous_response_id`, the instructions from a previous response
              will not be carried over to the next response. This makes it simple to swap out
              system (or developer) messages in new responses.

          model: Model ID used to generate the response, like `gpt-4o` or `o3`. OpenAI offers a
              wide range of models with different capabilities, performance characteristics,
              and price points. Refer to the
              [model guide](https://platform.openai.com/docs/models) to browse and compare
              available models.

          parallel_tool_calls: Whether to allow the model to run tool calls in parallel.

          previous_response_id: The unique ID of the previous response to the model. Use this to create
              multi-turn conversations. Learn more about
              [conversation state](https://platform.openai.com/docs/guides/conversation-state).
              Cannot be used in conjunction with `conversation`.

          reasoning: **gpt-5 and o-series models only** Configuration options for
              [reasoning models](https://platform.openai.com/docs/guides/reasoning).

          text: Configuration options for a text response from the model. Can be plain text or
              structured JSON data. Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

          tool_choice: Controls which tool the model should use, if any.

          tools: An array of tools the model may call while generating a response. You can
              specify which tool to use by setting the `tool_choice` parameter.

          truncation: The truncation strategy to use for the model response. - `auto`: If the input to
              this Response exceeds the model's context window size, the model will truncate
              the response to fit the context window by dropping items from the beginning of
              the conversation. - `disabled` (default): If the input size will exceed the
              context window size for a model, the request will fail with a 400 error.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        return self._post(
            "/responses/input_tokens",
            body=maybe_transform(
                {
                    "conversation": conversation,
                    "input": input,
                    "instructions": instructions,
                    "model": model,
                    "parallel_tool_calls": parallel_tool_calls,
                    "previous_response_id": previous_response_id,
                    "reasoning": reasoning,
                    "text": text,
                    "tool_choice": tool_choice,
                    "tools": tools,
                    "truncation": truncation,
                },
                input_token_count_params.InputTokenCountParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=InputTokenCountResponse,
        )


class AsyncInputTokens(AsyncAPIResource):
    @cached_property
    def with_raw_response(self) -> AsyncInputTokensWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return AsyncInputTokensWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> AsyncInputTokensWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return AsyncInputTokensWithStreamingResponse(self)

    async def count(
        self,
        *,
        conversation: Optional[input_token_count_params.Conversation] | Omit = omit,
        input: Union[str, Iterable[ResponseInputItemParam], None] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        model: Optional[str] | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        text: Optional[input_token_count_params.Text] | Omit = omit,
        tool_choice: Optional[input_token_count_params.ToolChoice] | Omit = omit,
        tools: Optional[Iterable[ToolParam]] | Omit = omit,
        truncation: Literal["auto", "disabled"] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> InputTokenCountResponse:
        """
        Get input token counts

        Args:
          conversation: The conversation that this response belongs to. Items from this conversation are
              prepended to `input_items` for this response request. Input items and output
              items from this response are automatically added to this conversation after this
              response completes.

          input: Text, image, or file inputs to the model, used to generate a response

          instructions: A system (or developer) message inserted into the model's context. When used
              along with `previous_response_id`, the instructions from a previous response
              will not be carried over to the next response. This makes it simple to swap out
              system (or developer) messages in new responses.

          model: Model ID used to generate the response, like `gpt-4o` or `o3`. OpenAI offers a
              wide range of models with different capabilities, performance characteristics,
              and price points. Refer to the
              [model guide](https://platform.openai.com/docs/models) to browse and compare
              available models.

          parallel_tool_calls: Whether to allow the model to run tool calls in parallel.

          previous_response_id: The unique ID of the previous response to the model. Use this to create
              multi-turn conversations. Learn more about
              [conversation state](https://platform.openai.com/docs/guides/conversation-state).
              Cannot be used in conjunction with `conversation`.

          reasoning: **gpt-5 and o-series models only** Configuration options for
              [reasoning models](https://platform.openai.com/docs/guides/reasoning).

          text: Configuration options for a text response from the model. Can be plain text or
              structured JSON data. Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

          tool_choice: Controls which tool the model should use, if any.

          tools: An array of tools the model may call while generating a response. You can
              specify which tool to use by setting the `tool_choice` parameter.

          truncation: The truncation strategy to use for the model response. - `auto`: If the input to
              this Response exceeds the model's context window size, the model will truncate
              the response to fit the context window by dropping items from the beginning of
              the conversation. - `disabled` (default): If the input size will exceed the
              context window size for a model, the request will fail with a 400 error.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        return await self._post(
            "/responses/input_tokens",
            body=await async_maybe_transform(
                {
                    "conversation": conversation,
                    "input": input,
                    "instructions": instructions,
                    "model": model,
                    "parallel_tool_calls": parallel_tool_calls,
                    "previous_response_id": previous_response_id,
                    "reasoning": reasoning,
                    "text": text,
                    "tool_choice": tool_choice,
                    "tools": tools,
                    "truncation": truncation,
                },
                input_token_count_params.InputTokenCountParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=InputTokenCountResponse,
        )


class InputTokensWithRawResponse:
    def __init__(self, input_tokens: InputTokens) -> None:
        self._input_tokens = input_tokens

        self.count = _legacy_response.to_raw_response_wrapper(
            input_tokens.count,
        )


class AsyncInputTokensWithRawResponse:
    def __init__(self, input_tokens: AsyncInputTokens) -> None:
        self._input_tokens = input_tokens

        self.count = _legacy_response.async_to_raw_response_wrapper(
            input_tokens.count,
        )


class InputTokensWithStreamingResponse:
    def __init__(self, input_tokens: InputTokens) -> None:
        self._input_tokens = input_tokens

        self.count = to_streamed_response_wrapper(
            input_tokens.count,
        )


class AsyncInputTokensWithStreamingResponse:
    def __init__(self, input_tokens: AsyncInputTokens) -> None:
        self._input_tokens = input_tokens

        self.count = async_to_streamed_response_wrapper(
            input_tokens.count,
        )
