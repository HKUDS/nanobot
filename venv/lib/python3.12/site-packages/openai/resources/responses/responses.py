# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from copy import copy
from typing import Any, List, Type, Union, Iterable, Optional, cast
from functools import partial
from typing_extensions import Literal, overload

import httpx

from ... import _legacy_response
from ..._types import NOT_GIVEN, Body, Omit, Query, Headers, NoneType, NotGiven, omit, not_given
from ..._utils import is_given, maybe_transform, async_maybe_transform
from ..._compat import cached_property
from ..._resource import SyncAPIResource, AsyncAPIResource
from ..._response import to_streamed_response_wrapper, async_to_streamed_response_wrapper
from .input_items import (
    InputItems,
    AsyncInputItems,
    InputItemsWithRawResponse,
    AsyncInputItemsWithRawResponse,
    InputItemsWithStreamingResponse,
    AsyncInputItemsWithStreamingResponse,
)
from ..._streaming import Stream, AsyncStream
from ...lib._tools import PydanticFunctionTool, ResponsesPydanticFunctionTool
from .input_tokens import (
    InputTokens,
    AsyncInputTokens,
    InputTokensWithRawResponse,
    AsyncInputTokensWithRawResponse,
    InputTokensWithStreamingResponse,
    AsyncInputTokensWithStreamingResponse,
)
from ..._base_client import make_request_options
from ...types.responses import (
    response_create_params,
    response_compact_params,
    response_retrieve_params,
)
from ...lib._parsing._responses import (
    TextFormatT,
    parse_response,
    type_to_text_format_param as _type_to_text_format_param,
)
from ...types.responses.response import Response
from ...types.responses.tool_param import ToolParam, ParseableToolParam
from ...types.shared_params.metadata import Metadata
from ...types.shared_params.reasoning import Reasoning
from ...types.responses.parsed_response import ParsedResponse
from ...lib.streaming.responses._responses import ResponseStreamManager, AsyncResponseStreamManager
from ...types.responses.compacted_response import CompactedResponse
from ...types.responses.response_includable import ResponseIncludable
from ...types.shared_params.responses_model import ResponsesModel
from ...types.responses.response_input_param import ResponseInputParam
from ...types.responses.response_prompt_param import ResponsePromptParam
from ...types.responses.response_stream_event import ResponseStreamEvent
from ...types.responses.response_input_item_param import ResponseInputItemParam
from ...types.responses.response_text_config_param import ResponseTextConfigParam

__all__ = ["Responses", "AsyncResponses"]


class Responses(SyncAPIResource):
    @cached_property
    def input_items(self) -> InputItems:
        return InputItems(self._client)

    @cached_property
    def input_tokens(self) -> InputTokens:
        return InputTokens(self._client)

    @cached_property
    def with_raw_response(self) -> ResponsesWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return ResponsesWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> ResponsesWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return ResponsesWithStreamingResponse(self)

    @overload
    def create(
        self,
        *,
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream: Optional[Literal[False]] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response:
        """Creates a model response.

        Provide
        [text](https://platform.openai.com/docs/guides/text) or
        [image](https://platform.openai.com/docs/guides/images) inputs to generate
        [text](https://platform.openai.com/docs/guides/text) or
        [JSON](https://platform.openai.com/docs/guides/structured-outputs) outputs. Have
        the model call your own
        [custom code](https://platform.openai.com/docs/guides/function-calling) or use
        built-in [tools](https://platform.openai.com/docs/guides/tools) like
        [web search](https://platform.openai.com/docs/guides/tools-web-search) or
        [file search](https://platform.openai.com/docs/guides/tools-file-search) to use
        your own data as input for the model's response.

        Args:
          background: Whether to run the model response in the background.
              [Learn more](https://platform.openai.com/docs/guides/background).

          conversation: The conversation that this response belongs to. Items from this conversation are
              prepended to `input_items` for this response request. Input items and output
              items from this response are automatically added to this conversation after this
              response completes.

          include: Specify additional output data to include in the model response. Currently
              supported values are:

              - `web_search_call.action.sources`: Include the sources of the web search tool
                call.
              - `code_interpreter_call.outputs`: Includes the outputs of python code execution
                in code interpreter tool call items.
              - `computer_call_output.output.image_url`: Include image urls from the computer
                call output.
              - `file_search_call.results`: Include the search results of the file search tool
                call.
              - `message.input_image.image_url`: Include image urls from the input message.
              - `message.output_text.logprobs`: Include logprobs with assistant messages.
              - `reasoning.encrypted_content`: Includes an encrypted version of reasoning
                tokens in reasoning item outputs. This enables reasoning items to be used in
                multi-turn conversations when using the Responses API statelessly (like when
                the `store` parameter is set to `false`, or when an organization is enrolled
                in the zero data retention program).

          input: Text, image, or file inputs to the model, used to generate a response.

              Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Image inputs](https://platform.openai.com/docs/guides/images)
              - [File inputs](https://platform.openai.com/docs/guides/pdf-files)
              - [Conversation state](https://platform.openai.com/docs/guides/conversation-state)
              - [Function calling](https://platform.openai.com/docs/guides/function-calling)

          instructions: A system (or developer) message inserted into the model's context.

              When using along with `previous_response_id`, the instructions from a previous
              response will not be carried over to the next response. This makes it simple to
              swap out system (or developer) messages in new responses.

          max_output_tokens: An upper bound for the number of tokens that can be generated for a response,
              including visible output tokens and
              [reasoning tokens](https://platform.openai.com/docs/guides/reasoning).

          max_tool_calls: The maximum number of total calls to built-in tools that can be processed in a
              response. This maximum number applies across all built-in tool calls, not per
              individual tool. Any further attempts to call a tool by the model will be
              ignored.

          metadata: Set of 16 key-value pairs that can be attached to an object. This can be useful
              for storing additional information about the object in a structured format, and
              querying for objects via API or the dashboard.

              Keys are strings with a maximum length of 64 characters. Values are strings with
              a maximum length of 512 characters.

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

          prompt: Reference to a prompt template and its variables.
              [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).

          prompt_cache_key: Used by OpenAI to cache responses for similar requests to optimize your cache
              hit rates. Replaces the `user` field.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching).

          prompt_cache_retention: The retention policy for the prompt cache. Set to `24h` to enable extended
              prompt caching, which keeps cached prefixes active for longer, up to a maximum
              of 24 hours.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching#prompt-cache-retention).

          reasoning: **gpt-5 and o-series models only**

              Configuration options for
              [reasoning models](https://platform.openai.com/docs/guides/reasoning).

          safety_identifier: A stable identifier used to help detect users of your application that may be
              violating OpenAI's usage policies. The IDs should be a string that uniquely
              identifies each user. We recommend hashing their username or email address, in
              order to avoid sending us any identifying information.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          service_tier: Specifies the processing type used for serving the request.

              - If set to 'auto', then the request will be processed with the service tier
                configured in the Project settings. Unless otherwise configured, the Project
                will use 'default'.
              - If set to 'default', then the request will be processed with the standard
                pricing and performance for the selected model.
              - If set to '[flex](https://platform.openai.com/docs/guides/flex-processing)' or
                '[priority](https://openai.com/api-priority-processing/)', then the request
                will be processed with the corresponding service tier.
              - When not set, the default behavior is 'auto'.

              When the `service_tier` parameter is set, the response body will include the
              `service_tier` value based on the processing mode actually used to serve the
              request. This response value may be different from the value set in the
              parameter.

          store: Whether to store the generated model response for later retrieval via API.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          stream_options: Options for streaming responses. Only set this when you set `stream: true`.

          temperature: What sampling temperature to use, between 0 and 2. Higher values like 0.8 will
              make the output more random, while lower values like 0.2 will make it more
              focused and deterministic. We generally recommend altering this or `top_p` but
              not both.

          text: Configuration options for a text response from the model. Can be plain text or
              structured JSON data. Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

          tool_choice: How the model should select which tool (or tools) to use when generating a
              response. See the `tools` parameter to see how to specify which tools the model
              can call.

          tools: An array of tools the model may call while generating a response. You can
              specify which tool to use by setting the `tool_choice` parameter.

              We support the following categories of tools:

              - **Built-in tools**: Tools that are provided by OpenAI that extend the model's
                capabilities, like
                [web search](https://platform.openai.com/docs/guides/tools-web-search) or
                [file search](https://platform.openai.com/docs/guides/tools-file-search).
                Learn more about
                [built-in tools](https://platform.openai.com/docs/guides/tools).
              - **MCP Tools**: Integrations with third-party systems via custom MCP servers or
                predefined connectors such as Google Drive and SharePoint. Learn more about
                [MCP Tools](https://platform.openai.com/docs/guides/tools-connectors-mcp).
              - **Function calls (custom tools)**: Functions that are defined by you, enabling
                the model to call your own code with strongly typed arguments and outputs.
                Learn more about
                [function calling](https://platform.openai.com/docs/guides/function-calling).
                You can also use custom tools to call your own code.

          top_logprobs: An integer between 0 and 20 specifying the number of most likely tokens to
              return at each token position, each with an associated log probability.

          top_p: An alternative to sampling with temperature, called nucleus sampling, where the
              model considers the results of the tokens with top_p probability mass. So 0.1
              means only the tokens comprising the top 10% probability mass are considered.

              We generally recommend altering this or `temperature` but not both.

          truncation: The truncation strategy to use for the model response.

              - `auto`: If the input to this Response exceeds the model's context window size,
                the model will truncate the response to fit the context window by dropping
                items from the beginning of the conversation.
              - `disabled` (default): If the input size will exceed the context window size
                for a model, the request will fail with a 400 error.

          user: This field is being replaced by `safety_identifier` and `prompt_cache_key`. Use
              `prompt_cache_key` instead to maintain caching optimizations. A stable
              identifier for your end-users. Used to boost cache hit rates by better bucketing
              similar requests and to help OpenAI detect and prevent abuse.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @overload
    def create(
        self,
        *,
        stream: Literal[True],
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Stream[ResponseStreamEvent]:
        """Creates a model response.

        Provide
        [text](https://platform.openai.com/docs/guides/text) or
        [image](https://platform.openai.com/docs/guides/images) inputs to generate
        [text](https://platform.openai.com/docs/guides/text) or
        [JSON](https://platform.openai.com/docs/guides/structured-outputs) outputs. Have
        the model call your own
        [custom code](https://platform.openai.com/docs/guides/function-calling) or use
        built-in [tools](https://platform.openai.com/docs/guides/tools) like
        [web search](https://platform.openai.com/docs/guides/tools-web-search) or
        [file search](https://platform.openai.com/docs/guides/tools-file-search) to use
        your own data as input for the model's response.

        Args:
          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          background: Whether to run the model response in the background.
              [Learn more](https://platform.openai.com/docs/guides/background).

          conversation: The conversation that this response belongs to. Items from this conversation are
              prepended to `input_items` for this response request. Input items and output
              items from this response are automatically added to this conversation after this
              response completes.

          include: Specify additional output data to include in the model response. Currently
              supported values are:

              - `web_search_call.action.sources`: Include the sources of the web search tool
                call.
              - `code_interpreter_call.outputs`: Includes the outputs of python code execution
                in code interpreter tool call items.
              - `computer_call_output.output.image_url`: Include image urls from the computer
                call output.
              - `file_search_call.results`: Include the search results of the file search tool
                call.
              - `message.input_image.image_url`: Include image urls from the input message.
              - `message.output_text.logprobs`: Include logprobs with assistant messages.
              - `reasoning.encrypted_content`: Includes an encrypted version of reasoning
                tokens in reasoning item outputs. This enables reasoning items to be used in
                multi-turn conversations when using the Responses API statelessly (like when
                the `store` parameter is set to `false`, or when an organization is enrolled
                in the zero data retention program).

          input: Text, image, or file inputs to the model, used to generate a response.

              Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Image inputs](https://platform.openai.com/docs/guides/images)
              - [File inputs](https://platform.openai.com/docs/guides/pdf-files)
              - [Conversation state](https://platform.openai.com/docs/guides/conversation-state)
              - [Function calling](https://platform.openai.com/docs/guides/function-calling)

          instructions: A system (or developer) message inserted into the model's context.

              When using along with `previous_response_id`, the instructions from a previous
              response will not be carried over to the next response. This makes it simple to
              swap out system (or developer) messages in new responses.

          max_output_tokens: An upper bound for the number of tokens that can be generated for a response,
              including visible output tokens and
              [reasoning tokens](https://platform.openai.com/docs/guides/reasoning).

          max_tool_calls: The maximum number of total calls to built-in tools that can be processed in a
              response. This maximum number applies across all built-in tool calls, not per
              individual tool. Any further attempts to call a tool by the model will be
              ignored.

          metadata: Set of 16 key-value pairs that can be attached to an object. This can be useful
              for storing additional information about the object in a structured format, and
              querying for objects via API or the dashboard.

              Keys are strings with a maximum length of 64 characters. Values are strings with
              a maximum length of 512 characters.

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

          prompt: Reference to a prompt template and its variables.
              [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).

          prompt_cache_key: Used by OpenAI to cache responses for similar requests to optimize your cache
              hit rates. Replaces the `user` field.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching).

          prompt_cache_retention: The retention policy for the prompt cache. Set to `24h` to enable extended
              prompt caching, which keeps cached prefixes active for longer, up to a maximum
              of 24 hours.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching#prompt-cache-retention).

          reasoning: **gpt-5 and o-series models only**

              Configuration options for
              [reasoning models](https://platform.openai.com/docs/guides/reasoning).

          safety_identifier: A stable identifier used to help detect users of your application that may be
              violating OpenAI's usage policies. The IDs should be a string that uniquely
              identifies each user. We recommend hashing their username or email address, in
              order to avoid sending us any identifying information.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          service_tier: Specifies the processing type used for serving the request.

              - If set to 'auto', then the request will be processed with the service tier
                configured in the Project settings. Unless otherwise configured, the Project
                will use 'default'.
              - If set to 'default', then the request will be processed with the standard
                pricing and performance for the selected model.
              - If set to '[flex](https://platform.openai.com/docs/guides/flex-processing)' or
                '[priority](https://openai.com/api-priority-processing/)', then the request
                will be processed with the corresponding service tier.
              - When not set, the default behavior is 'auto'.

              When the `service_tier` parameter is set, the response body will include the
              `service_tier` value based on the processing mode actually used to serve the
              request. This response value may be different from the value set in the
              parameter.

          store: Whether to store the generated model response for later retrieval via API.

          stream_options: Options for streaming responses. Only set this when you set `stream: true`.

          temperature: What sampling temperature to use, between 0 and 2. Higher values like 0.8 will
              make the output more random, while lower values like 0.2 will make it more
              focused and deterministic. We generally recommend altering this or `top_p` but
              not both.

          text: Configuration options for a text response from the model. Can be plain text or
              structured JSON data. Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

          tool_choice: How the model should select which tool (or tools) to use when generating a
              response. See the `tools` parameter to see how to specify which tools the model
              can call.

          tools: An array of tools the model may call while generating a response. You can
              specify which tool to use by setting the `tool_choice` parameter.

              We support the following categories of tools:

              - **Built-in tools**: Tools that are provided by OpenAI that extend the model's
                capabilities, like
                [web search](https://platform.openai.com/docs/guides/tools-web-search) or
                [file search](https://platform.openai.com/docs/guides/tools-file-search).
                Learn more about
                [built-in tools](https://platform.openai.com/docs/guides/tools).
              - **MCP Tools**: Integrations with third-party systems via custom MCP servers or
                predefined connectors such as Google Drive and SharePoint. Learn more about
                [MCP Tools](https://platform.openai.com/docs/guides/tools-connectors-mcp).
              - **Function calls (custom tools)**: Functions that are defined by you, enabling
                the model to call your own code with strongly typed arguments and outputs.
                Learn more about
                [function calling](https://platform.openai.com/docs/guides/function-calling).
                You can also use custom tools to call your own code.

          top_logprobs: An integer between 0 and 20 specifying the number of most likely tokens to
              return at each token position, each with an associated log probability.

          top_p: An alternative to sampling with temperature, called nucleus sampling, where the
              model considers the results of the tokens with top_p probability mass. So 0.1
              means only the tokens comprising the top 10% probability mass are considered.

              We generally recommend altering this or `temperature` but not both.

          truncation: The truncation strategy to use for the model response.

              - `auto`: If the input to this Response exceeds the model's context window size,
                the model will truncate the response to fit the context window by dropping
                items from the beginning of the conversation.
              - `disabled` (default): If the input size will exceed the context window size
                for a model, the request will fail with a 400 error.

          user: This field is being replaced by `safety_identifier` and `prompt_cache_key`. Use
              `prompt_cache_key` instead to maintain caching optimizations. A stable
              identifier for your end-users. Used to boost cache hit rates by better bucketing
              similar requests and to help OpenAI detect and prevent abuse.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @overload
    def create(
        self,
        *,
        stream: bool,
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response | Stream[ResponseStreamEvent]:
        """Creates a model response.

        Provide
        [text](https://platform.openai.com/docs/guides/text) or
        [image](https://platform.openai.com/docs/guides/images) inputs to generate
        [text](https://platform.openai.com/docs/guides/text) or
        [JSON](https://platform.openai.com/docs/guides/structured-outputs) outputs. Have
        the model call your own
        [custom code](https://platform.openai.com/docs/guides/function-calling) or use
        built-in [tools](https://platform.openai.com/docs/guides/tools) like
        [web search](https://platform.openai.com/docs/guides/tools-web-search) or
        [file search](https://platform.openai.com/docs/guides/tools-file-search) to use
        your own data as input for the model's response.

        Args:
          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          background: Whether to run the model response in the background.
              [Learn more](https://platform.openai.com/docs/guides/background).

          conversation: The conversation that this response belongs to. Items from this conversation are
              prepended to `input_items` for this response request. Input items and output
              items from this response are automatically added to this conversation after this
              response completes.

          include: Specify additional output data to include in the model response. Currently
              supported values are:

              - `web_search_call.action.sources`: Include the sources of the web search tool
                call.
              - `code_interpreter_call.outputs`: Includes the outputs of python code execution
                in code interpreter tool call items.
              - `computer_call_output.output.image_url`: Include image urls from the computer
                call output.
              - `file_search_call.results`: Include the search results of the file search tool
                call.
              - `message.input_image.image_url`: Include image urls from the input message.
              - `message.output_text.logprobs`: Include logprobs with assistant messages.
              - `reasoning.encrypted_content`: Includes an encrypted version of reasoning
                tokens in reasoning item outputs. This enables reasoning items to be used in
                multi-turn conversations when using the Responses API statelessly (like when
                the `store` parameter is set to `false`, or when an organization is enrolled
                in the zero data retention program).

          input: Text, image, or file inputs to the model, used to generate a response.

              Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Image inputs](https://platform.openai.com/docs/guides/images)
              - [File inputs](https://platform.openai.com/docs/guides/pdf-files)
              - [Conversation state](https://platform.openai.com/docs/guides/conversation-state)
              - [Function calling](https://platform.openai.com/docs/guides/function-calling)

          instructions: A system (or developer) message inserted into the model's context.

              When using along with `previous_response_id`, the instructions from a previous
              response will not be carried over to the next response. This makes it simple to
              swap out system (or developer) messages in new responses.

          max_output_tokens: An upper bound for the number of tokens that can be generated for a response,
              including visible output tokens and
              [reasoning tokens](https://platform.openai.com/docs/guides/reasoning).

          max_tool_calls: The maximum number of total calls to built-in tools that can be processed in a
              response. This maximum number applies across all built-in tool calls, not per
              individual tool. Any further attempts to call a tool by the model will be
              ignored.

          metadata: Set of 16 key-value pairs that can be attached to an object. This can be useful
              for storing additional information about the object in a structured format, and
              querying for objects via API or the dashboard.

              Keys are strings with a maximum length of 64 characters. Values are strings with
              a maximum length of 512 characters.

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

          prompt: Reference to a prompt template and its variables.
              [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).

          prompt_cache_key: Used by OpenAI to cache responses for similar requests to optimize your cache
              hit rates. Replaces the `user` field.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching).

          prompt_cache_retention: The retention policy for the prompt cache. Set to `24h` to enable extended
              prompt caching, which keeps cached prefixes active for longer, up to a maximum
              of 24 hours.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching#prompt-cache-retention).

          reasoning: **gpt-5 and o-series models only**

              Configuration options for
              [reasoning models](https://platform.openai.com/docs/guides/reasoning).

          safety_identifier: A stable identifier used to help detect users of your application that may be
              violating OpenAI's usage policies. The IDs should be a string that uniquely
              identifies each user. We recommend hashing their username or email address, in
              order to avoid sending us any identifying information.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          service_tier: Specifies the processing type used for serving the request.

              - If set to 'auto', then the request will be processed with the service tier
                configured in the Project settings. Unless otherwise configured, the Project
                will use 'default'.
              - If set to 'default', then the request will be processed with the standard
                pricing and performance for the selected model.
              - If set to '[flex](https://platform.openai.com/docs/guides/flex-processing)' or
                '[priority](https://openai.com/api-priority-processing/)', then the request
                will be processed with the corresponding service tier.
              - When not set, the default behavior is 'auto'.

              When the `service_tier` parameter is set, the response body will include the
              `service_tier` value based on the processing mode actually used to serve the
              request. This response value may be different from the value set in the
              parameter.

          store: Whether to store the generated model response for later retrieval via API.

          stream_options: Options for streaming responses. Only set this when you set `stream: true`.

          temperature: What sampling temperature to use, between 0 and 2. Higher values like 0.8 will
              make the output more random, while lower values like 0.2 will make it more
              focused and deterministic. We generally recommend altering this or `top_p` but
              not both.

          text: Configuration options for a text response from the model. Can be plain text or
              structured JSON data. Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

          tool_choice: How the model should select which tool (or tools) to use when generating a
              response. See the `tools` parameter to see how to specify which tools the model
              can call.

          tools: An array of tools the model may call while generating a response. You can
              specify which tool to use by setting the `tool_choice` parameter.

              We support the following categories of tools:

              - **Built-in tools**: Tools that are provided by OpenAI that extend the model's
                capabilities, like
                [web search](https://platform.openai.com/docs/guides/tools-web-search) or
                [file search](https://platform.openai.com/docs/guides/tools-file-search).
                Learn more about
                [built-in tools](https://platform.openai.com/docs/guides/tools).
              - **MCP Tools**: Integrations with third-party systems via custom MCP servers or
                predefined connectors such as Google Drive and SharePoint. Learn more about
                [MCP Tools](https://platform.openai.com/docs/guides/tools-connectors-mcp).
              - **Function calls (custom tools)**: Functions that are defined by you, enabling
                the model to call your own code with strongly typed arguments and outputs.
                Learn more about
                [function calling](https://platform.openai.com/docs/guides/function-calling).
                You can also use custom tools to call your own code.

          top_logprobs: An integer between 0 and 20 specifying the number of most likely tokens to
              return at each token position, each with an associated log probability.

          top_p: An alternative to sampling with temperature, called nucleus sampling, where the
              model considers the results of the tokens with top_p probability mass. So 0.1
              means only the tokens comprising the top 10% probability mass are considered.

              We generally recommend altering this or `temperature` but not both.

          truncation: The truncation strategy to use for the model response.

              - `auto`: If the input to this Response exceeds the model's context window size,
                the model will truncate the response to fit the context window by dropping
                items from the beginning of the conversation.
              - `disabled` (default): If the input size will exceed the context window size
                for a model, the request will fail with a 400 error.

          user: This field is being replaced by `safety_identifier` and `prompt_cache_key`. Use
              `prompt_cache_key` instead to maintain caching optimizations. A stable
              identifier for your end-users. Used to boost cache hit rates by better bucketing
              similar requests and to help OpenAI detect and prevent abuse.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    def create(
        self,
        *,
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream: Optional[Literal[False]] | Literal[True] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response | Stream[ResponseStreamEvent]:
        return self._post(
            "/responses",
            body=maybe_transform(
                {
                    "background": background,
                    "conversation": conversation,
                    "include": include,
                    "input": input,
                    "instructions": instructions,
                    "max_output_tokens": max_output_tokens,
                    "max_tool_calls": max_tool_calls,
                    "metadata": metadata,
                    "model": model,
                    "parallel_tool_calls": parallel_tool_calls,
                    "previous_response_id": previous_response_id,
                    "prompt": prompt,
                    "prompt_cache_key": prompt_cache_key,
                    "prompt_cache_retention": prompt_cache_retention,
                    "reasoning": reasoning,
                    "safety_identifier": safety_identifier,
                    "service_tier": service_tier,
                    "store": store,
                    "stream": stream,
                    "stream_options": stream_options,
                    "temperature": temperature,
                    "text": text,
                    "tool_choice": tool_choice,
                    "tools": tools,
                    "top_logprobs": top_logprobs,
                    "top_p": top_p,
                    "truncation": truncation,
                    "user": user,
                },
                response_create_params.ResponseCreateParamsStreaming
                if stream
                else response_create_params.ResponseCreateParamsNonStreaming,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=Response,
            stream=stream or False,
            stream_cls=Stream[ResponseStreamEvent],
        )

    @overload
    def stream(
        self,
        *,
        response_id: str,
        text_format: type[TextFormatT] | Omit = omit,
        starting_after: int | Omit = omit,
        tools: Iterable[ParseableToolParam] | Omit = omit,
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> ResponseStreamManager[TextFormatT]: ...

    @overload
    def stream(
        self,
        *,
        input: Union[str, ResponseInputParam],
        model: ResponsesModel,
        background: Optional[bool] | Omit = omit,
        text_format: type[TextFormatT] | Omit = omit,
        tools: Iterable[ParseableToolParam] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> ResponseStreamManager[TextFormatT]: ...

    def stream(
        self,
        *,
        response_id: str | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        background: Optional[bool] | Omit = omit,
        text_format: type[TextFormatT] | Omit = omit,
        tools: Iterable[ParseableToolParam] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> ResponseStreamManager[TextFormatT]:
        new_response_args = {
            "input": input,
            "model": model,
            "conversation": conversation,
            "include": include,
            "instructions": instructions,
            "max_output_tokens": max_output_tokens,
            "max_tool_calls": max_tool_calls,
            "metadata": metadata,
            "parallel_tool_calls": parallel_tool_calls,
            "previous_response_id": previous_response_id,
            "prompt": prompt,
            "prompt_cache_key": prompt_cache_key,
            "prompt_cache_retention": prompt_cache_retention,
            "reasoning": reasoning,
            "safety_identifier": safety_identifier,
            "service_tier": service_tier,
            "store": store,
            "stream_options": stream_options,
            "temperature": temperature,
            "text": text,
            "tool_choice": tool_choice,
            "top_logprobs": top_logprobs,
            "top_p": top_p,
            "truncation": truncation,
            "user": user,
            "background": background,
        }
        new_response_args_names = [k for k, v in new_response_args.items() if is_given(v)]

        if (is_given(response_id) or is_given(starting_after)) and len(new_response_args_names) > 0:
            raise ValueError(
                "Cannot provide both response_id/starting_after can't be provided together with "
                + ", ".join(new_response_args_names)
            )
        tools = _make_tools(tools)
        if len(new_response_args_names) > 0:
            if not is_given(input):
                raise ValueError("input must be provided when creating a new response")

            if not is_given(model):
                raise ValueError("model must be provided when creating a new response")

            if is_given(text_format):
                if not text:
                    text = {}

                if "format" in text:
                    raise TypeError("Cannot mix and match text.format with text_format")

                text = copy(text)
                text["format"] = _type_to_text_format_param(text_format)

            api_request: partial[Stream[ResponseStreamEvent]] = partial(
                self.create,
                input=input,
                model=model,
                tools=tools,
                conversation=conversation,
                include=include,
                instructions=instructions,
                max_output_tokens=max_output_tokens,
                max_tool_calls=max_tool_calls,
                metadata=metadata,
                parallel_tool_calls=parallel_tool_calls,
                previous_response_id=previous_response_id,
                prompt=prompt,
                prompt_cache_key=prompt_cache_key,
                prompt_cache_retention=prompt_cache_retention,
                store=store,
                stream_options=stream_options,
                stream=True,
                temperature=temperature,
                text=text,
                tool_choice=tool_choice,
                reasoning=reasoning,
                safety_identifier=safety_identifier,
                service_tier=service_tier,
                top_logprobs=top_logprobs,
                top_p=top_p,
                truncation=truncation,
                user=user,
                background=background,
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
            )

            return ResponseStreamManager(api_request, text_format=text_format, input_tools=tools, starting_after=None)
        else:
            if not is_given(response_id):
                raise ValueError("id must be provided when streaming an existing response")

            return ResponseStreamManager(
                lambda: self.retrieve(
                    response_id=response_id,
                    stream=True,
                    include=include or [],
                    extra_headers=extra_headers,
                    extra_query=extra_query,
                    extra_body=extra_body,
                    starting_after=omit,
                    timeout=timeout,
                ),
                text_format=text_format,
                input_tools=tools,
                starting_after=starting_after if is_given(starting_after) else None,
            )

    def parse(
        self,
        *,
        text_format: type[TextFormatT] | Omit = omit,
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream: Optional[Literal[False]] | Literal[True] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ParseableToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        verbosity: Optional[Literal["low", "medium", "high"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> ParsedResponse[TextFormatT]:
        if is_given(text_format):
            if not text:
                text = {}

            if "format" in text:
                raise TypeError("Cannot mix and match text.format with text_format")
            text = copy(text)
            text["format"] = _type_to_text_format_param(text_format)

        tools = _make_tools(tools)

        def parser(raw_response: Response) -> ParsedResponse[TextFormatT]:
            return parse_response(
                input_tools=tools,
                text_format=text_format,
                response=raw_response,
            )

        return self._post(
            "/responses",
            body=maybe_transform(
                {
                    "background": background,
                    "conversation": conversation,
                    "include": include,
                    "input": input,
                    "instructions": instructions,
                    "max_output_tokens": max_output_tokens,
                    "max_tool_calls": max_tool_calls,
                    "metadata": metadata,
                    "model": model,
                    "parallel_tool_calls": parallel_tool_calls,
                    "previous_response_id": previous_response_id,
                    "prompt": prompt,
                    "prompt_cache_key": prompt_cache_key,
                    "prompt_cache_retention": prompt_cache_retention,
                    "reasoning": reasoning,
                    "safety_identifier": safety_identifier,
                    "service_tier": service_tier,
                    "store": store,
                    "stream": stream,
                    "stream_options": stream_options,
                    "temperature": temperature,
                    "text": text,
                    "tool_choice": tool_choice,
                    "tools": tools,
                    "top_logprobs": top_logprobs,
                    "top_p": top_p,
                    "truncation": truncation,
                    "user": user,
                    "verbosity": verbosity,
                },
                response_create_params.ResponseCreateParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
                post_parser=parser,
            ),
            # we turn the `Response` instance into a `ParsedResponse`
            # in the `parser` function above
            cast_to=cast(Type[ParsedResponse[TextFormatT]], Response),
        )

    @overload
    def retrieve(
        self,
        response_id: str,
        *,
        include: List[ResponseIncludable] | Omit = omit,
        include_obfuscation: bool | Omit = omit,
        starting_after: int | Omit = omit,
        stream: Literal[False] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response: ...

    @overload
    def retrieve(
        self,
        response_id: str,
        *,
        stream: Literal[True],
        include: List[ResponseIncludable] | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> Stream[ResponseStreamEvent]: ...

    @overload
    def retrieve(
        self,
        response_id: str,
        *,
        stream: bool,
        include: List[ResponseIncludable] | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> Response | Stream[ResponseStreamEvent]: ...

    @overload
    def retrieve(
        self,
        response_id: str,
        *,
        stream: bool = False,
        include: List[ResponseIncludable] | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> Response | Stream[ResponseStreamEvent]:
        """
        Retrieves a model response with the given ID.

        Args:
          include: Additional fields to include in the response. See the `include` parameter for
              Response creation above for more information.

          include_obfuscation: When true, stream obfuscation will be enabled. Stream obfuscation adds random
              characters to an `obfuscation` field on streaming delta events to normalize
              payload sizes as a mitigation to certain side-channel attacks. These obfuscation
              fields are included by default, but add a small amount of overhead to the data
              stream. You can set `include_obfuscation` to false to optimize for bandwidth if
              you trust the network links between your application and the OpenAI API.

          starting_after: The sequence number of the event after which to start streaming.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @overload
    def retrieve(
        self,
        response_id: str,
        *,
        stream: Literal[True],
        include: List[ResponseIncludable] | Omit = omit,
        include_obfuscation: bool | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Stream[ResponseStreamEvent]:
        """
        Retrieves a model response with the given ID.

        Args:
          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          include: Additional fields to include in the response. See the `include` parameter for
              Response creation above for more information.

          include_obfuscation: When true, stream obfuscation will be enabled. Stream obfuscation adds random
              characters to an `obfuscation` field on streaming delta events to normalize
              payload sizes as a mitigation to certain side-channel attacks. These obfuscation
              fields are included by default, but add a small amount of overhead to the data
              stream. You can set `include_obfuscation` to false to optimize for bandwidth if
              you trust the network links between your application and the OpenAI API.

          starting_after: The sequence number of the event after which to start streaming.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @overload
    def retrieve(
        self,
        response_id: str,
        *,
        stream: bool,
        include: List[ResponseIncludable] | Omit = omit,
        include_obfuscation: bool | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response | Stream[ResponseStreamEvent]:
        """
        Retrieves a model response with the given ID.

        Args:
          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          include: Additional fields to include in the response. See the `include` parameter for
              Response creation above for more information.

          include_obfuscation: When true, stream obfuscation will be enabled. Stream obfuscation adds random
              characters to an `obfuscation` field on streaming delta events to normalize
              payload sizes as a mitigation to certain side-channel attacks. These obfuscation
              fields are included by default, but add a small amount of overhead to the data
              stream. You can set `include_obfuscation` to false to optimize for bandwidth if
              you trust the network links between your application and the OpenAI API.

          starting_after: The sequence number of the event after which to start streaming.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    def retrieve(
        self,
        response_id: str,
        *,
        include: List[ResponseIncludable] | Omit = omit,
        include_obfuscation: bool | Omit = omit,
        starting_after: int | Omit = omit,
        stream: Literal[False] | Literal[True] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response | Stream[ResponseStreamEvent]:
        if not response_id:
            raise ValueError(f"Expected a non-empty value for `response_id` but received {response_id!r}")
        return self._get(
            f"/responses/{response_id}",
            options=make_request_options(
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
                query=maybe_transform(
                    {
                        "include": include,
                        "include_obfuscation": include_obfuscation,
                        "starting_after": starting_after,
                        "stream": stream,
                    },
                    response_retrieve_params.ResponseRetrieveParams,
                ),
            ),
            cast_to=Response,
            stream=stream or False,
            stream_cls=Stream[ResponseStreamEvent],
        )

    def delete(
        self,
        response_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> None:
        """
        Deletes a model response with the given ID.

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not response_id:
            raise ValueError(f"Expected a non-empty value for `response_id` but received {response_id!r}")
        extra_headers = {"Accept": "*/*", **(extra_headers or {})}
        return self._delete(
            f"/responses/{response_id}",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=NoneType,
        )

    def cancel(
        self,
        response_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response:
        """Cancels a model response with the given ID.

        Only responses created with the
        `background` parameter set to `true` can be cancelled.
        [Learn more](https://platform.openai.com/docs/guides/background).

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not response_id:
            raise ValueError(f"Expected a non-empty value for `response_id` but received {response_id!r}")
        return self._post(
            f"/responses/{response_id}/cancel",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=Response,
        )

    def compact(
        self,
        *,
        model: Union[
            Literal[
                "gpt-5.2",
                "gpt-5.2-2025-12-11",
                "gpt-5.2-chat-latest",
                "gpt-5.2-pro",
                "gpt-5.2-pro-2025-12-11",
                "gpt-5.1",
                "gpt-5.1-2025-11-13",
                "gpt-5.1-codex",
                "gpt-5.1-mini",
                "gpt-5.1-chat-latest",
                "gpt-5",
                "gpt-5-mini",
                "gpt-5-nano",
                "gpt-5-2025-08-07",
                "gpt-5-mini-2025-08-07",
                "gpt-5-nano-2025-08-07",
                "gpt-5-chat-latest",
                "gpt-4.1",
                "gpt-4.1-mini",
                "gpt-4.1-nano",
                "gpt-4.1-2025-04-14",
                "gpt-4.1-mini-2025-04-14",
                "gpt-4.1-nano-2025-04-14",
                "o4-mini",
                "o4-mini-2025-04-16",
                "o3",
                "o3-2025-04-16",
                "o3-mini",
                "o3-mini-2025-01-31",
                "o1",
                "o1-2024-12-17",
                "o1-preview",
                "o1-preview-2024-09-12",
                "o1-mini",
                "o1-mini-2024-09-12",
                "gpt-4o",
                "gpt-4o-2024-11-20",
                "gpt-4o-2024-08-06",
                "gpt-4o-2024-05-13",
                "gpt-4o-audio-preview",
                "gpt-4o-audio-preview-2024-10-01",
                "gpt-4o-audio-preview-2024-12-17",
                "gpt-4o-audio-preview-2025-06-03",
                "gpt-4o-mini-audio-preview",
                "gpt-4o-mini-audio-preview-2024-12-17",
                "gpt-4o-search-preview",
                "gpt-4o-mini-search-preview",
                "gpt-4o-search-preview-2025-03-11",
                "gpt-4o-mini-search-preview-2025-03-11",
                "chatgpt-4o-latest",
                "codex-mini-latest",
                "gpt-4o-mini",
                "gpt-4o-mini-2024-07-18",
                "gpt-4-turbo",
                "gpt-4-turbo-2024-04-09",
                "gpt-4-0125-preview",
                "gpt-4-turbo-preview",
                "gpt-4-1106-preview",
                "gpt-4-vision-preview",
                "gpt-4",
                "gpt-4-0314",
                "gpt-4-0613",
                "gpt-4-32k",
                "gpt-4-32k-0314",
                "gpt-4-32k-0613",
                "gpt-3.5-turbo",
                "gpt-3.5-turbo-16k",
                "gpt-3.5-turbo-0301",
                "gpt-3.5-turbo-0613",
                "gpt-3.5-turbo-1106",
                "gpt-3.5-turbo-0125",
                "gpt-3.5-turbo-16k-0613",
                "o1-pro",
                "o1-pro-2025-03-19",
                "o3-pro",
                "o3-pro-2025-06-10",
                "o3-deep-research",
                "o3-deep-research-2025-06-26",
                "o4-mini-deep-research",
                "o4-mini-deep-research-2025-06-26",
                "computer-use-preview",
                "computer-use-preview-2025-03-11",
                "gpt-5-codex",
                "gpt-5-pro",
                "gpt-5-pro-2025-10-06",
                "gpt-5.1-codex-max",
            ],
            str,
            None,
        ],
        input: Union[str, Iterable[ResponseInputItemParam], None] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> CompactedResponse:
        """
        Compact conversation

        Args:
          model: Model ID used to generate the response, like `gpt-5` or `o3`. OpenAI offers a
              wide range of models with different capabilities, performance characteristics,
              and price points. Refer to the
              [model guide](https://platform.openai.com/docs/models) to browse and compare
              available models.

          input: Text, image, or file inputs to the model, used to generate a response

          instructions: A system (or developer) message inserted into the model's context. When used
              along with `previous_response_id`, the instructions from a previous response
              will not be carried over to the next response. This makes it simple to swap out
              system (or developer) messages in new responses.

          previous_response_id: The unique ID of the previous response to the model. Use this to create
              multi-turn conversations. Learn more about
              [conversation state](https://platform.openai.com/docs/guides/conversation-state).
              Cannot be used in conjunction with `conversation`.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        return self._post(
            "/responses/compact",
            body=maybe_transform(
                {
                    "model": model,
                    "input": input,
                    "instructions": instructions,
                    "previous_response_id": previous_response_id,
                },
                response_compact_params.ResponseCompactParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=CompactedResponse,
        )


class AsyncResponses(AsyncAPIResource):
    @cached_property
    def input_items(self) -> AsyncInputItems:
        return AsyncInputItems(self._client)

    @cached_property
    def input_tokens(self) -> AsyncInputTokens:
        return AsyncInputTokens(self._client)

    @cached_property
    def with_raw_response(self) -> AsyncResponsesWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return AsyncResponsesWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> AsyncResponsesWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return AsyncResponsesWithStreamingResponse(self)

    @overload
    async def create(
        self,
        *,
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream: Optional[Literal[False]] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response:
        """Creates a model response.

        Provide
        [text](https://platform.openai.com/docs/guides/text) or
        [image](https://platform.openai.com/docs/guides/images) inputs to generate
        [text](https://platform.openai.com/docs/guides/text) or
        [JSON](https://platform.openai.com/docs/guides/structured-outputs) outputs. Have
        the model call your own
        [custom code](https://platform.openai.com/docs/guides/function-calling) or use
        built-in [tools](https://platform.openai.com/docs/guides/tools) like
        [web search](https://platform.openai.com/docs/guides/tools-web-search) or
        [file search](https://platform.openai.com/docs/guides/tools-file-search) to use
        your own data as input for the model's response.

        Args:
          background: Whether to run the model response in the background.
              [Learn more](https://platform.openai.com/docs/guides/background).

          conversation: The conversation that this response belongs to. Items from this conversation are
              prepended to `input_items` for this response request. Input items and output
              items from this response are automatically added to this conversation after this
              response completes.

          include: Specify additional output data to include in the model response. Currently
              supported values are:

              - `web_search_call.action.sources`: Include the sources of the web search tool
                call.
              - `code_interpreter_call.outputs`: Includes the outputs of python code execution
                in code interpreter tool call items.
              - `computer_call_output.output.image_url`: Include image urls from the computer
                call output.
              - `file_search_call.results`: Include the search results of the file search tool
                call.
              - `message.input_image.image_url`: Include image urls from the input message.
              - `message.output_text.logprobs`: Include logprobs with assistant messages.
              - `reasoning.encrypted_content`: Includes an encrypted version of reasoning
                tokens in reasoning item outputs. This enables reasoning items to be used in
                multi-turn conversations when using the Responses API statelessly (like when
                the `store` parameter is set to `false`, or when an organization is enrolled
                in the zero data retention program).

          input: Text, image, or file inputs to the model, used to generate a response.

              Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Image inputs](https://platform.openai.com/docs/guides/images)
              - [File inputs](https://platform.openai.com/docs/guides/pdf-files)
              - [Conversation state](https://platform.openai.com/docs/guides/conversation-state)
              - [Function calling](https://platform.openai.com/docs/guides/function-calling)

          instructions: A system (or developer) message inserted into the model's context.

              When using along with `previous_response_id`, the instructions from a previous
              response will not be carried over to the next response. This makes it simple to
              swap out system (or developer) messages in new responses.

          max_output_tokens: An upper bound for the number of tokens that can be generated for a response,
              including visible output tokens and
              [reasoning tokens](https://platform.openai.com/docs/guides/reasoning).

          max_tool_calls: The maximum number of total calls to built-in tools that can be processed in a
              response. This maximum number applies across all built-in tool calls, not per
              individual tool. Any further attempts to call a tool by the model will be
              ignored.

          metadata: Set of 16 key-value pairs that can be attached to an object. This can be useful
              for storing additional information about the object in a structured format, and
              querying for objects via API or the dashboard.

              Keys are strings with a maximum length of 64 characters. Values are strings with
              a maximum length of 512 characters.

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

          prompt: Reference to a prompt template and its variables.
              [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).

          prompt_cache_key: Used by OpenAI to cache responses for similar requests to optimize your cache
              hit rates. Replaces the `user` field.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching).

          prompt_cache_retention: The retention policy for the prompt cache. Set to `24h` to enable extended
              prompt caching, which keeps cached prefixes active for longer, up to a maximum
              of 24 hours.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching#prompt-cache-retention).

          reasoning: **gpt-5 and o-series models only**

              Configuration options for
              [reasoning models](https://platform.openai.com/docs/guides/reasoning).

          safety_identifier: A stable identifier used to help detect users of your application that may be
              violating OpenAI's usage policies. The IDs should be a string that uniquely
              identifies each user. We recommend hashing their username or email address, in
              order to avoid sending us any identifying information.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          service_tier: Specifies the processing type used for serving the request.

              - If set to 'auto', then the request will be processed with the service tier
                configured in the Project settings. Unless otherwise configured, the Project
                will use 'default'.
              - If set to 'default', then the request will be processed with the standard
                pricing and performance for the selected model.
              - If set to '[flex](https://platform.openai.com/docs/guides/flex-processing)' or
                '[priority](https://openai.com/api-priority-processing/)', then the request
                will be processed with the corresponding service tier.
              - When not set, the default behavior is 'auto'.

              When the `service_tier` parameter is set, the response body will include the
              `service_tier` value based on the processing mode actually used to serve the
              request. This response value may be different from the value set in the
              parameter.

          store: Whether to store the generated model response for later retrieval via API.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          stream_options: Options for streaming responses. Only set this when you set `stream: true`.

          temperature: What sampling temperature to use, between 0 and 2. Higher values like 0.8 will
              make the output more random, while lower values like 0.2 will make it more
              focused and deterministic. We generally recommend altering this or `top_p` but
              not both.

          text: Configuration options for a text response from the model. Can be plain text or
              structured JSON data. Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

          tool_choice: How the model should select which tool (or tools) to use when generating a
              response. See the `tools` parameter to see how to specify which tools the model
              can call.

          tools: An array of tools the model may call while generating a response. You can
              specify which tool to use by setting the `tool_choice` parameter.

              We support the following categories of tools:

              - **Built-in tools**: Tools that are provided by OpenAI that extend the model's
                capabilities, like
                [web search](https://platform.openai.com/docs/guides/tools-web-search) or
                [file search](https://platform.openai.com/docs/guides/tools-file-search).
                Learn more about
                [built-in tools](https://platform.openai.com/docs/guides/tools).
              - **MCP Tools**: Integrations with third-party systems via custom MCP servers or
                predefined connectors such as Google Drive and SharePoint. Learn more about
                [MCP Tools](https://platform.openai.com/docs/guides/tools-connectors-mcp).
              - **Function calls (custom tools)**: Functions that are defined by you, enabling
                the model to call your own code with strongly typed arguments and outputs.
                Learn more about
                [function calling](https://platform.openai.com/docs/guides/function-calling).
                You can also use custom tools to call your own code.

          top_logprobs: An integer between 0 and 20 specifying the number of most likely tokens to
              return at each token position, each with an associated log probability.

          top_p: An alternative to sampling with temperature, called nucleus sampling, where the
              model considers the results of the tokens with top_p probability mass. So 0.1
              means only the tokens comprising the top 10% probability mass are considered.

              We generally recommend altering this or `temperature` but not both.

          truncation: The truncation strategy to use for the model response.

              - `auto`: If the input to this Response exceeds the model's context window size,
                the model will truncate the response to fit the context window by dropping
                items from the beginning of the conversation.
              - `disabled` (default): If the input size will exceed the context window size
                for a model, the request will fail with a 400 error.

          user: This field is being replaced by `safety_identifier` and `prompt_cache_key`. Use
              `prompt_cache_key` instead to maintain caching optimizations. A stable
              identifier for your end-users. Used to boost cache hit rates by better bucketing
              similar requests and to help OpenAI detect and prevent abuse.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @overload
    async def create(
        self,
        *,
        stream: Literal[True],
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> AsyncStream[ResponseStreamEvent]:
        """Creates a model response.

        Provide
        [text](https://platform.openai.com/docs/guides/text) or
        [image](https://platform.openai.com/docs/guides/images) inputs to generate
        [text](https://platform.openai.com/docs/guides/text) or
        [JSON](https://platform.openai.com/docs/guides/structured-outputs) outputs. Have
        the model call your own
        [custom code](https://platform.openai.com/docs/guides/function-calling) or use
        built-in [tools](https://platform.openai.com/docs/guides/tools) like
        [web search](https://platform.openai.com/docs/guides/tools-web-search) or
        [file search](https://platform.openai.com/docs/guides/tools-file-search) to use
        your own data as input for the model's response.

        Args:
          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          background: Whether to run the model response in the background.
              [Learn more](https://platform.openai.com/docs/guides/background).

          conversation: The conversation that this response belongs to. Items from this conversation are
              prepended to `input_items` for this response request. Input items and output
              items from this response are automatically added to this conversation after this
              response completes.

          include: Specify additional output data to include in the model response. Currently
              supported values are:

              - `web_search_call.action.sources`: Include the sources of the web search tool
                call.
              - `code_interpreter_call.outputs`: Includes the outputs of python code execution
                in code interpreter tool call items.
              - `computer_call_output.output.image_url`: Include image urls from the computer
                call output.
              - `file_search_call.results`: Include the search results of the file search tool
                call.
              - `message.input_image.image_url`: Include image urls from the input message.
              - `message.output_text.logprobs`: Include logprobs with assistant messages.
              - `reasoning.encrypted_content`: Includes an encrypted version of reasoning
                tokens in reasoning item outputs. This enables reasoning items to be used in
                multi-turn conversations when using the Responses API statelessly (like when
                the `store` parameter is set to `false`, or when an organization is enrolled
                in the zero data retention program).

          input: Text, image, or file inputs to the model, used to generate a response.

              Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Image inputs](https://platform.openai.com/docs/guides/images)
              - [File inputs](https://platform.openai.com/docs/guides/pdf-files)
              - [Conversation state](https://platform.openai.com/docs/guides/conversation-state)
              - [Function calling](https://platform.openai.com/docs/guides/function-calling)

          instructions: A system (or developer) message inserted into the model's context.

              When using along with `previous_response_id`, the instructions from a previous
              response will not be carried over to the next response. This makes it simple to
              swap out system (or developer) messages in new responses.

          max_output_tokens: An upper bound for the number of tokens that can be generated for a response,
              including visible output tokens and
              [reasoning tokens](https://platform.openai.com/docs/guides/reasoning).

          max_tool_calls: The maximum number of total calls to built-in tools that can be processed in a
              response. This maximum number applies across all built-in tool calls, not per
              individual tool. Any further attempts to call a tool by the model will be
              ignored.

          metadata: Set of 16 key-value pairs that can be attached to an object. This can be useful
              for storing additional information about the object in a structured format, and
              querying for objects via API or the dashboard.

              Keys are strings with a maximum length of 64 characters. Values are strings with
              a maximum length of 512 characters.

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

          prompt: Reference to a prompt template and its variables.
              [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).

          prompt_cache_key: Used by OpenAI to cache responses for similar requests to optimize your cache
              hit rates. Replaces the `user` field.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching).

          prompt_cache_retention: The retention policy for the prompt cache. Set to `24h` to enable extended
              prompt caching, which keeps cached prefixes active for longer, up to a maximum
              of 24 hours.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching#prompt-cache-retention).

          reasoning: **gpt-5 and o-series models only**

              Configuration options for
              [reasoning models](https://platform.openai.com/docs/guides/reasoning).

          safety_identifier: A stable identifier used to help detect users of your application that may be
              violating OpenAI's usage policies. The IDs should be a string that uniquely
              identifies each user. We recommend hashing their username or email address, in
              order to avoid sending us any identifying information.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          service_tier: Specifies the processing type used for serving the request.

              - If set to 'auto', then the request will be processed with the service tier
                configured in the Project settings. Unless otherwise configured, the Project
                will use 'default'.
              - If set to 'default', then the request will be processed with the standard
                pricing and performance for the selected model.
              - If set to '[flex](https://platform.openai.com/docs/guides/flex-processing)' or
                '[priority](https://openai.com/api-priority-processing/)', then the request
                will be processed with the corresponding service tier.
              - When not set, the default behavior is 'auto'.

              When the `service_tier` parameter is set, the response body will include the
              `service_tier` value based on the processing mode actually used to serve the
              request. This response value may be different from the value set in the
              parameter.

          store: Whether to store the generated model response for later retrieval via API.

          stream_options: Options for streaming responses. Only set this when you set `stream: true`.

          temperature: What sampling temperature to use, between 0 and 2. Higher values like 0.8 will
              make the output more random, while lower values like 0.2 will make it more
              focused and deterministic. We generally recommend altering this or `top_p` but
              not both.

          text: Configuration options for a text response from the model. Can be plain text or
              structured JSON data. Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

          tool_choice: How the model should select which tool (or tools) to use when generating a
              response. See the `tools` parameter to see how to specify which tools the model
              can call.

          tools: An array of tools the model may call while generating a response. You can
              specify which tool to use by setting the `tool_choice` parameter.

              We support the following categories of tools:

              - **Built-in tools**: Tools that are provided by OpenAI that extend the model's
                capabilities, like
                [web search](https://platform.openai.com/docs/guides/tools-web-search) or
                [file search](https://platform.openai.com/docs/guides/tools-file-search).
                Learn more about
                [built-in tools](https://platform.openai.com/docs/guides/tools).
              - **MCP Tools**: Integrations with third-party systems via custom MCP servers or
                predefined connectors such as Google Drive and SharePoint. Learn more about
                [MCP Tools](https://platform.openai.com/docs/guides/tools-connectors-mcp).
              - **Function calls (custom tools)**: Functions that are defined by you, enabling
                the model to call your own code with strongly typed arguments and outputs.
                Learn more about
                [function calling](https://platform.openai.com/docs/guides/function-calling).
                You can also use custom tools to call your own code.

          top_logprobs: An integer between 0 and 20 specifying the number of most likely tokens to
              return at each token position, each with an associated log probability.

          top_p: An alternative to sampling with temperature, called nucleus sampling, where the
              model considers the results of the tokens with top_p probability mass. So 0.1
              means only the tokens comprising the top 10% probability mass are considered.

              We generally recommend altering this or `temperature` but not both.

          truncation: The truncation strategy to use for the model response.

              - `auto`: If the input to this Response exceeds the model's context window size,
                the model will truncate the response to fit the context window by dropping
                items from the beginning of the conversation.
              - `disabled` (default): If the input size will exceed the context window size
                for a model, the request will fail with a 400 error.

          user: This field is being replaced by `safety_identifier` and `prompt_cache_key`. Use
              `prompt_cache_key` instead to maintain caching optimizations. A stable
              identifier for your end-users. Used to boost cache hit rates by better bucketing
              similar requests and to help OpenAI detect and prevent abuse.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @overload
    async def create(
        self,
        *,
        stream: bool,
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response | AsyncStream[ResponseStreamEvent]:
        """Creates a model response.

        Provide
        [text](https://platform.openai.com/docs/guides/text) or
        [image](https://platform.openai.com/docs/guides/images) inputs to generate
        [text](https://platform.openai.com/docs/guides/text) or
        [JSON](https://platform.openai.com/docs/guides/structured-outputs) outputs. Have
        the model call your own
        [custom code](https://platform.openai.com/docs/guides/function-calling) or use
        built-in [tools](https://platform.openai.com/docs/guides/tools) like
        [web search](https://platform.openai.com/docs/guides/tools-web-search) or
        [file search](https://platform.openai.com/docs/guides/tools-file-search) to use
        your own data as input for the model's response.

        Args:
          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          background: Whether to run the model response in the background.
              [Learn more](https://platform.openai.com/docs/guides/background).

          conversation: The conversation that this response belongs to. Items from this conversation are
              prepended to `input_items` for this response request. Input items and output
              items from this response are automatically added to this conversation after this
              response completes.

          include: Specify additional output data to include in the model response. Currently
              supported values are:

              - `web_search_call.action.sources`: Include the sources of the web search tool
                call.
              - `code_interpreter_call.outputs`: Includes the outputs of python code execution
                in code interpreter tool call items.
              - `computer_call_output.output.image_url`: Include image urls from the computer
                call output.
              - `file_search_call.results`: Include the search results of the file search tool
                call.
              - `message.input_image.image_url`: Include image urls from the input message.
              - `message.output_text.logprobs`: Include logprobs with assistant messages.
              - `reasoning.encrypted_content`: Includes an encrypted version of reasoning
                tokens in reasoning item outputs. This enables reasoning items to be used in
                multi-turn conversations when using the Responses API statelessly (like when
                the `store` parameter is set to `false`, or when an organization is enrolled
                in the zero data retention program).

          input: Text, image, or file inputs to the model, used to generate a response.

              Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Image inputs](https://platform.openai.com/docs/guides/images)
              - [File inputs](https://platform.openai.com/docs/guides/pdf-files)
              - [Conversation state](https://platform.openai.com/docs/guides/conversation-state)
              - [Function calling](https://platform.openai.com/docs/guides/function-calling)

          instructions: A system (or developer) message inserted into the model's context.

              When using along with `previous_response_id`, the instructions from a previous
              response will not be carried over to the next response. This makes it simple to
              swap out system (or developer) messages in new responses.

          max_output_tokens: An upper bound for the number of tokens that can be generated for a response,
              including visible output tokens and
              [reasoning tokens](https://platform.openai.com/docs/guides/reasoning).

          max_tool_calls: The maximum number of total calls to built-in tools that can be processed in a
              response. This maximum number applies across all built-in tool calls, not per
              individual tool. Any further attempts to call a tool by the model will be
              ignored.

          metadata: Set of 16 key-value pairs that can be attached to an object. This can be useful
              for storing additional information about the object in a structured format, and
              querying for objects via API or the dashboard.

              Keys are strings with a maximum length of 64 characters. Values are strings with
              a maximum length of 512 characters.

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

          prompt: Reference to a prompt template and its variables.
              [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).

          prompt_cache_key: Used by OpenAI to cache responses for similar requests to optimize your cache
              hit rates. Replaces the `user` field.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching).

          prompt_cache_retention: The retention policy for the prompt cache. Set to `24h` to enable extended
              prompt caching, which keeps cached prefixes active for longer, up to a maximum
              of 24 hours.
              [Learn more](https://platform.openai.com/docs/guides/prompt-caching#prompt-cache-retention).

          reasoning: **gpt-5 and o-series models only**

              Configuration options for
              [reasoning models](https://platform.openai.com/docs/guides/reasoning).

          safety_identifier: A stable identifier used to help detect users of your application that may be
              violating OpenAI's usage policies. The IDs should be a string that uniquely
              identifies each user. We recommend hashing their username or email address, in
              order to avoid sending us any identifying information.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          service_tier: Specifies the processing type used for serving the request.

              - If set to 'auto', then the request will be processed with the service tier
                configured in the Project settings. Unless otherwise configured, the Project
                will use 'default'.
              - If set to 'default', then the request will be processed with the standard
                pricing and performance for the selected model.
              - If set to '[flex](https://platform.openai.com/docs/guides/flex-processing)' or
                '[priority](https://openai.com/api-priority-processing/)', then the request
                will be processed with the corresponding service tier.
              - When not set, the default behavior is 'auto'.

              When the `service_tier` parameter is set, the response body will include the
              `service_tier` value based on the processing mode actually used to serve the
              request. This response value may be different from the value set in the
              parameter.

          store: Whether to store the generated model response for later retrieval via API.

          stream_options: Options for streaming responses. Only set this when you set `stream: true`.

          temperature: What sampling temperature to use, between 0 and 2. Higher values like 0.8 will
              make the output more random, while lower values like 0.2 will make it more
              focused and deterministic. We generally recommend altering this or `top_p` but
              not both.

          text: Configuration options for a text response from the model. Can be plain text or
              structured JSON data. Learn more:

              - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
              - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

          tool_choice: How the model should select which tool (or tools) to use when generating a
              response. See the `tools` parameter to see how to specify which tools the model
              can call.

          tools: An array of tools the model may call while generating a response. You can
              specify which tool to use by setting the `tool_choice` parameter.

              We support the following categories of tools:

              - **Built-in tools**: Tools that are provided by OpenAI that extend the model's
                capabilities, like
                [web search](https://platform.openai.com/docs/guides/tools-web-search) or
                [file search](https://platform.openai.com/docs/guides/tools-file-search).
                Learn more about
                [built-in tools](https://platform.openai.com/docs/guides/tools).
              - **MCP Tools**: Integrations with third-party systems via custom MCP servers or
                predefined connectors such as Google Drive and SharePoint. Learn more about
                [MCP Tools](https://platform.openai.com/docs/guides/tools-connectors-mcp).
              - **Function calls (custom tools)**: Functions that are defined by you, enabling
                the model to call your own code with strongly typed arguments and outputs.
                Learn more about
                [function calling](https://platform.openai.com/docs/guides/function-calling).
                You can also use custom tools to call your own code.

          top_logprobs: An integer between 0 and 20 specifying the number of most likely tokens to
              return at each token position, each with an associated log probability.

          top_p: An alternative to sampling with temperature, called nucleus sampling, where the
              model considers the results of the tokens with top_p probability mass. So 0.1
              means only the tokens comprising the top 10% probability mass are considered.

              We generally recommend altering this or `temperature` but not both.

          truncation: The truncation strategy to use for the model response.

              - `auto`: If the input to this Response exceeds the model's context window size,
                the model will truncate the response to fit the context window by dropping
                items from the beginning of the conversation.
              - `disabled` (default): If the input size will exceed the context window size
                for a model, the request will fail with a 400 error.

          user: This field is being replaced by `safety_identifier` and `prompt_cache_key`. Use
              `prompt_cache_key` instead to maintain caching optimizations. A stable
              identifier for your end-users. Used to boost cache hit rates by better bucketing
              similar requests and to help OpenAI detect and prevent abuse.
              [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    async def create(
        self,
        *,
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream: Optional[Literal[False]] | Literal[True] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response | AsyncStream[ResponseStreamEvent]:
        return await self._post(
            "/responses",
            body=await async_maybe_transform(
                {
                    "background": background,
                    "conversation": conversation,
                    "include": include,
                    "input": input,
                    "instructions": instructions,
                    "max_output_tokens": max_output_tokens,
                    "max_tool_calls": max_tool_calls,
                    "metadata": metadata,
                    "model": model,
                    "parallel_tool_calls": parallel_tool_calls,
                    "previous_response_id": previous_response_id,
                    "prompt": prompt,
                    "prompt_cache_key": prompt_cache_key,
                    "prompt_cache_retention": prompt_cache_retention,
                    "reasoning": reasoning,
                    "safety_identifier": safety_identifier,
                    "service_tier": service_tier,
                    "store": store,
                    "stream": stream,
                    "stream_options": stream_options,
                    "temperature": temperature,
                    "text": text,
                    "tool_choice": tool_choice,
                    "tools": tools,
                    "top_logprobs": top_logprobs,
                    "top_p": top_p,
                    "truncation": truncation,
                    "user": user,
                },
                response_create_params.ResponseCreateParamsStreaming
                if stream
                else response_create_params.ResponseCreateParamsNonStreaming,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=Response,
            stream=stream or False,
            stream_cls=AsyncStream[ResponseStreamEvent],
        )

    @overload
    def stream(
        self,
        *,
        response_id: str,
        text_format: type[TextFormatT] | Omit = omit,
        starting_after: int | Omit = omit,
        tools: Iterable[ParseableToolParam] | Omit = omit,
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> AsyncResponseStreamManager[TextFormatT]: ...

    @overload
    def stream(
        self,
        *,
        input: Union[str, ResponseInputParam],
        model: ResponsesModel,
        background: Optional[bool] | Omit = omit,
        text_format: type[TextFormatT] | Omit = omit,
        tools: Iterable[ParseableToolParam] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> AsyncResponseStreamManager[TextFormatT]: ...

    def stream(
        self,
        *,
        response_id: str | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        background: Optional[bool] | Omit = omit,
        text_format: type[TextFormatT] | Omit = omit,
        tools: Iterable[ParseableToolParam] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> AsyncResponseStreamManager[TextFormatT]:
        new_response_args = {
            "input": input,
            "model": model,
            "conversation": conversation,
            "include": include,
            "instructions": instructions,
            "max_output_tokens": max_output_tokens,
            "max_tool_calls": max_tool_calls,
            "metadata": metadata,
            "parallel_tool_calls": parallel_tool_calls,
            "previous_response_id": previous_response_id,
            "prompt": prompt,
            "prompt_cache_key": prompt_cache_key,
            "prompt_cache_retention": prompt_cache_retention,
            "reasoning": reasoning,
            "safety_identifier": safety_identifier,
            "service_tier": service_tier,
            "store": store,
            "stream_options": stream_options,
            "temperature": temperature,
            "text": text,
            "tool_choice": tool_choice,
            "top_logprobs": top_logprobs,
            "top_p": top_p,
            "truncation": truncation,
            "user": user,
            "background": background,
        }
        new_response_args_names = [k for k, v in new_response_args.items() if is_given(v)]

        if (is_given(response_id) or is_given(starting_after)) and len(new_response_args_names) > 0:
            raise ValueError(
                "Cannot provide both response_id/starting_after can't be provided together with "
                + ", ".join(new_response_args_names)
            )

        tools = _make_tools(tools)
        if len(new_response_args_names) > 0:
            if isinstance(input, NotGiven):
                raise ValueError("input must be provided when creating a new response")

            if not is_given(model):
                raise ValueError("model must be provided when creating a new response")

            if is_given(text_format):
                if not text:
                    text = {}

                if "format" in text:
                    raise TypeError("Cannot mix and match text.format with text_format")
                text = copy(text)
                text["format"] = _type_to_text_format_param(text_format)

            api_request = self.create(
                input=input,
                model=model,
                stream=True,
                tools=tools,
                conversation=conversation,
                include=include,
                instructions=instructions,
                max_output_tokens=max_output_tokens,
                max_tool_calls=max_tool_calls,
                metadata=metadata,
                parallel_tool_calls=parallel_tool_calls,
                previous_response_id=previous_response_id,
                prompt=prompt,
                prompt_cache_key=prompt_cache_key,
                prompt_cache_retention=prompt_cache_retention,
                store=store,
                stream_options=stream_options,
                temperature=temperature,
                text=text,
                tool_choice=tool_choice,
                reasoning=reasoning,
                safety_identifier=safety_identifier,
                service_tier=service_tier,
                top_logprobs=top_logprobs,
                top_p=top_p,
                truncation=truncation,
                user=user,
                background=background,
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
            )

            return AsyncResponseStreamManager(
                api_request,
                text_format=text_format,
                input_tools=tools,
                starting_after=None,
            )
        else:
            if isinstance(response_id, Omit):
                raise ValueError("response_id must be provided when streaming an existing response")

            api_request = self.retrieve(
                response_id,
                stream=True,
                include=include or [],
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
            )
            return AsyncResponseStreamManager(
                api_request,
                text_format=text_format,
                input_tools=tools,
                starting_after=starting_after if is_given(starting_after) else None,
            )

    async def parse(
        self,
        *,
        text_format: type[TextFormatT] | Omit = omit,
        background: Optional[bool] | Omit = omit,
        conversation: Optional[response_create_params.Conversation] | Omit = omit,
        include: Optional[List[ResponseIncludable]] | Omit = omit,
        input: Union[str, ResponseInputParam] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        max_output_tokens: Optional[int] | Omit = omit,
        max_tool_calls: Optional[int] | Omit = omit,
        metadata: Optional[Metadata] | Omit = omit,
        model: ResponsesModel | Omit = omit,
        parallel_tool_calls: Optional[bool] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        prompt: Optional[ResponsePromptParam] | Omit = omit,
        prompt_cache_key: str | Omit = omit,
        prompt_cache_retention: Optional[Literal["in-memory", "24h"]] | Omit = omit,
        reasoning: Optional[Reasoning] | Omit = omit,
        safety_identifier: str | Omit = omit,
        service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] | Omit = omit,
        store: Optional[bool] | Omit = omit,
        stream: Optional[Literal[False]] | Literal[True] | Omit = omit,
        stream_options: Optional[response_create_params.StreamOptions] | Omit = omit,
        temperature: Optional[float] | Omit = omit,
        text: ResponseTextConfigParam | Omit = omit,
        tool_choice: response_create_params.ToolChoice | Omit = omit,
        tools: Iterable[ParseableToolParam] | Omit = omit,
        top_logprobs: Optional[int] | Omit = omit,
        top_p: Optional[float] | Omit = omit,
        truncation: Optional[Literal["auto", "disabled"]] | Omit = omit,
        user: str | Omit = omit,
        verbosity: Optional[Literal["low", "medium", "high"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> ParsedResponse[TextFormatT]:
        if is_given(text_format):
            if not text:
                text = {}

            if "format" in text:
                raise TypeError("Cannot mix and match text.format with text_format")
            text = copy(text)
            text["format"] = _type_to_text_format_param(text_format)

        tools = _make_tools(tools)

        def parser(raw_response: Response) -> ParsedResponse[TextFormatT]:
            return parse_response(
                input_tools=tools,
                text_format=text_format,
                response=raw_response,
            )

        return await self._post(
            "/responses",
            body=maybe_transform(
                {
                    "background": background,
                    "conversation": conversation,
                    "include": include,
                    "input": input,
                    "instructions": instructions,
                    "max_output_tokens": max_output_tokens,
                    "max_tool_calls": max_tool_calls,
                    "metadata": metadata,
                    "model": model,
                    "parallel_tool_calls": parallel_tool_calls,
                    "previous_response_id": previous_response_id,
                    "prompt": prompt,
                    "prompt_cache_key": prompt_cache_key,
                    "prompt_cache_retention": prompt_cache_retention,
                    "reasoning": reasoning,
                    "safety_identifier": safety_identifier,
                    "service_tier": service_tier,
                    "store": store,
                    "stream": stream,
                    "stream_options": stream_options,
                    "temperature": temperature,
                    "text": text,
                    "tool_choice": tool_choice,
                    "tools": tools,
                    "top_logprobs": top_logprobs,
                    "top_p": top_p,
                    "truncation": truncation,
                    "user": user,
                    "verbosity": verbosity,
                },
                response_create_params.ResponseCreateParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
                post_parser=parser,
            ),
            # we turn the `Response` instance into a `ParsedResponse`
            # in the `parser` function above
            cast_to=cast(Type[ParsedResponse[TextFormatT]], Response),
        )

    @overload
    async def retrieve(
        self,
        response_id: str,
        *,
        include: List[ResponseIncludable] | Omit = omit,
        include_obfuscation: bool | Omit = omit,
        starting_after: int | Omit = omit,
        stream: Literal[False] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response: ...

    @overload
    async def retrieve(
        self,
        response_id: str,
        *,
        stream: Literal[True],
        include: List[ResponseIncludable] | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> AsyncStream[ResponseStreamEvent]: ...

    @overload
    async def retrieve(
        self,
        response_id: str,
        *,
        stream: bool,
        include: List[ResponseIncludable] | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> Response | AsyncStream[ResponseStreamEvent]: ...

    @overload
    async def retrieve(
        self,
        response_id: str,
        *,
        stream: bool = False,
        include: List[ResponseIncludable] | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    ) -> Response | AsyncStream[ResponseStreamEvent]:
        """
        Retrieves a model response with the given ID.

        Args:
          include: Additional fields to include in the response. See the `include` parameter for
              Response creation above for more information.

          include_obfuscation: When true, stream obfuscation will be enabled. Stream obfuscation adds random
              characters to an `obfuscation` field on streaming delta events to normalize
              payload sizes as a mitigation to certain side-channel attacks. These obfuscation
              fields are included by default, but add a small amount of overhead to the data
              stream. You can set `include_obfuscation` to false to optimize for bandwidth if
              you trust the network links between your application and the OpenAI API.

          starting_after: The sequence number of the event after which to start streaming.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @overload
    async def retrieve(
        self,
        response_id: str,
        *,
        stream: Literal[True],
        include: List[ResponseIncludable] | Omit = omit,
        include_obfuscation: bool | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> AsyncStream[ResponseStreamEvent]:
        """
        Retrieves a model response with the given ID.

        Args:
          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          include: Additional fields to include in the response. See the `include` parameter for
              Response creation above for more information.

          include_obfuscation: When true, stream obfuscation will be enabled. Stream obfuscation adds random
              characters to an `obfuscation` field on streaming delta events to normalize
              payload sizes as a mitigation to certain side-channel attacks. These obfuscation
              fields are included by default, but add a small amount of overhead to the data
              stream. You can set `include_obfuscation` to false to optimize for bandwidth if
              you trust the network links between your application and the OpenAI API.

          starting_after: The sequence number of the event after which to start streaming.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @overload
    async def retrieve(
        self,
        response_id: str,
        *,
        stream: bool,
        include: List[ResponseIncludable] | Omit = omit,
        include_obfuscation: bool | Omit = omit,
        starting_after: int | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response | AsyncStream[ResponseStreamEvent]:
        """
        Retrieves a model response with the given ID.

        Args:
          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section below](https://platform.openai.com/docs/api-reference/responses-streaming)
              for more information.

          include: Additional fields to include in the response. See the `include` parameter for
              Response creation above for more information.

          include_obfuscation: When true, stream obfuscation will be enabled. Stream obfuscation adds random
              characters to an `obfuscation` field on streaming delta events to normalize
              payload sizes as a mitigation to certain side-channel attacks. These obfuscation
              fields are included by default, but add a small amount of overhead to the data
              stream. You can set `include_obfuscation` to false to optimize for bandwidth if
              you trust the network links between your application and the OpenAI API.

          starting_after: The sequence number of the event after which to start streaming.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    async def retrieve(
        self,
        response_id: str,
        *,
        include: List[ResponseIncludable] | Omit = omit,
        include_obfuscation: bool | Omit = omit,
        starting_after: int | Omit = omit,
        stream: Literal[False] | Literal[True] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response | AsyncStream[ResponseStreamEvent]:
        if not response_id:
            raise ValueError(f"Expected a non-empty value for `response_id` but received {response_id!r}")
        return await self._get(
            f"/responses/{response_id}",
            options=make_request_options(
                extra_headers=extra_headers,
                extra_query=extra_query,
                extra_body=extra_body,
                timeout=timeout,
                query=await async_maybe_transform(
                    {
                        "include": include,
                        "include_obfuscation": include_obfuscation,
                        "starting_after": starting_after,
                        "stream": stream,
                    },
                    response_retrieve_params.ResponseRetrieveParams,
                ),
            ),
            cast_to=Response,
            stream=stream or False,
            stream_cls=AsyncStream[ResponseStreamEvent],
        )

    async def delete(
        self,
        response_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> None:
        """
        Deletes a model response with the given ID.

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not response_id:
            raise ValueError(f"Expected a non-empty value for `response_id` but received {response_id!r}")
        extra_headers = {"Accept": "*/*", **(extra_headers or {})}
        return await self._delete(
            f"/responses/{response_id}",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=NoneType,
        )

    async def cancel(
        self,
        response_id: str,
        *,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Response:
        """Cancels a model response with the given ID.

        Only responses created with the
        `background` parameter set to `true` can be cancelled.
        [Learn more](https://platform.openai.com/docs/guides/background).

        Args:
          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        if not response_id:
            raise ValueError(f"Expected a non-empty value for `response_id` but received {response_id!r}")
        return await self._post(
            f"/responses/{response_id}/cancel",
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=Response,
        )

    async def compact(
        self,
        *,
        model: Union[
            Literal[
                "gpt-5.2",
                "gpt-5.2-2025-12-11",
                "gpt-5.2-chat-latest",
                "gpt-5.2-pro",
                "gpt-5.2-pro-2025-12-11",
                "gpt-5.1",
                "gpt-5.1-2025-11-13",
                "gpt-5.1-codex",
                "gpt-5.1-mini",
                "gpt-5.1-chat-latest",
                "gpt-5",
                "gpt-5-mini",
                "gpt-5-nano",
                "gpt-5-2025-08-07",
                "gpt-5-mini-2025-08-07",
                "gpt-5-nano-2025-08-07",
                "gpt-5-chat-latest",
                "gpt-4.1",
                "gpt-4.1-mini",
                "gpt-4.1-nano",
                "gpt-4.1-2025-04-14",
                "gpt-4.1-mini-2025-04-14",
                "gpt-4.1-nano-2025-04-14",
                "o4-mini",
                "o4-mini-2025-04-16",
                "o3",
                "o3-2025-04-16",
                "o3-mini",
                "o3-mini-2025-01-31",
                "o1",
                "o1-2024-12-17",
                "o1-preview",
                "o1-preview-2024-09-12",
                "o1-mini",
                "o1-mini-2024-09-12",
                "gpt-4o",
                "gpt-4o-2024-11-20",
                "gpt-4o-2024-08-06",
                "gpt-4o-2024-05-13",
                "gpt-4o-audio-preview",
                "gpt-4o-audio-preview-2024-10-01",
                "gpt-4o-audio-preview-2024-12-17",
                "gpt-4o-audio-preview-2025-06-03",
                "gpt-4o-mini-audio-preview",
                "gpt-4o-mini-audio-preview-2024-12-17",
                "gpt-4o-search-preview",
                "gpt-4o-mini-search-preview",
                "gpt-4o-search-preview-2025-03-11",
                "gpt-4o-mini-search-preview-2025-03-11",
                "chatgpt-4o-latest",
                "codex-mini-latest",
                "gpt-4o-mini",
                "gpt-4o-mini-2024-07-18",
                "gpt-4-turbo",
                "gpt-4-turbo-2024-04-09",
                "gpt-4-0125-preview",
                "gpt-4-turbo-preview",
                "gpt-4-1106-preview",
                "gpt-4-vision-preview",
                "gpt-4",
                "gpt-4-0314",
                "gpt-4-0613",
                "gpt-4-32k",
                "gpt-4-32k-0314",
                "gpt-4-32k-0613",
                "gpt-3.5-turbo",
                "gpt-3.5-turbo-16k",
                "gpt-3.5-turbo-0301",
                "gpt-3.5-turbo-0613",
                "gpt-3.5-turbo-1106",
                "gpt-3.5-turbo-0125",
                "gpt-3.5-turbo-16k-0613",
                "o1-pro",
                "o1-pro-2025-03-19",
                "o3-pro",
                "o3-pro-2025-06-10",
                "o3-deep-research",
                "o3-deep-research-2025-06-26",
                "o4-mini-deep-research",
                "o4-mini-deep-research-2025-06-26",
                "computer-use-preview",
                "computer-use-preview-2025-03-11",
                "gpt-5-codex",
                "gpt-5-pro",
                "gpt-5-pro-2025-10-06",
                "gpt-5.1-codex-max",
            ],
            str,
            None,
        ],
        input: Union[str, Iterable[ResponseInputItemParam], None] | Omit = omit,
        instructions: Optional[str] | Omit = omit,
        previous_response_id: Optional[str] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> CompactedResponse:
        """
        Compact conversation

        Args:
          model: Model ID used to generate the response, like `gpt-5` or `o3`. OpenAI offers a
              wide range of models with different capabilities, performance characteristics,
              and price points. Refer to the
              [model guide](https://platform.openai.com/docs/models) to browse and compare
              available models.

          input: Text, image, or file inputs to the model, used to generate a response

          instructions: A system (or developer) message inserted into the model's context. When used
              along with `previous_response_id`, the instructions from a previous response
              will not be carried over to the next response. This makes it simple to swap out
              system (or developer) messages in new responses.

          previous_response_id: The unique ID of the previous response to the model. Use this to create
              multi-turn conversations. Learn more about
              [conversation state](https://platform.openai.com/docs/guides/conversation-state).
              Cannot be used in conjunction with `conversation`.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        return await self._post(
            "/responses/compact",
            body=await async_maybe_transform(
                {
                    "model": model,
                    "input": input,
                    "instructions": instructions,
                    "previous_response_id": previous_response_id,
                },
                response_compact_params.ResponseCompactParams,
            ),
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=CompactedResponse,
        )


class ResponsesWithRawResponse:
    def __init__(self, responses: Responses) -> None:
        self._responses = responses

        self.create = _legacy_response.to_raw_response_wrapper(
            responses.create,
        )
        self.retrieve = _legacy_response.to_raw_response_wrapper(
            responses.retrieve,
        )
        self.delete = _legacy_response.to_raw_response_wrapper(
            responses.delete,
        )
        self.cancel = _legacy_response.to_raw_response_wrapper(
            responses.cancel,
        )
        self.compact = _legacy_response.to_raw_response_wrapper(
            responses.compact,
        )
        self.parse = _legacy_response.to_raw_response_wrapper(
            responses.parse,
        )

    @cached_property
    def input_items(self) -> InputItemsWithRawResponse:
        return InputItemsWithRawResponse(self._responses.input_items)

    @cached_property
    def input_tokens(self) -> InputTokensWithRawResponse:
        return InputTokensWithRawResponse(self._responses.input_tokens)


class AsyncResponsesWithRawResponse:
    def __init__(self, responses: AsyncResponses) -> None:
        self._responses = responses

        self.create = _legacy_response.async_to_raw_response_wrapper(
            responses.create,
        )
        self.retrieve = _legacy_response.async_to_raw_response_wrapper(
            responses.retrieve,
        )
        self.delete = _legacy_response.async_to_raw_response_wrapper(
            responses.delete,
        )
        self.cancel = _legacy_response.async_to_raw_response_wrapper(
            responses.cancel,
        )
        self.compact = _legacy_response.async_to_raw_response_wrapper(
            responses.compact,
        )
        self.parse = _legacy_response.async_to_raw_response_wrapper(
            responses.parse,
        )

    @cached_property
    def input_items(self) -> AsyncInputItemsWithRawResponse:
        return AsyncInputItemsWithRawResponse(self._responses.input_items)

    @cached_property
    def input_tokens(self) -> AsyncInputTokensWithRawResponse:
        return AsyncInputTokensWithRawResponse(self._responses.input_tokens)


class ResponsesWithStreamingResponse:
    def __init__(self, responses: Responses) -> None:
        self._responses = responses

        self.create = to_streamed_response_wrapper(
            responses.create,
        )
        self.retrieve = to_streamed_response_wrapper(
            responses.retrieve,
        )
        self.delete = to_streamed_response_wrapper(
            responses.delete,
        )
        self.cancel = to_streamed_response_wrapper(
            responses.cancel,
        )
        self.compact = to_streamed_response_wrapper(
            responses.compact,
        )

    @cached_property
    def input_items(self) -> InputItemsWithStreamingResponse:
        return InputItemsWithStreamingResponse(self._responses.input_items)

    @cached_property
    def input_tokens(self) -> InputTokensWithStreamingResponse:
        return InputTokensWithStreamingResponse(self._responses.input_tokens)


class AsyncResponsesWithStreamingResponse:
    def __init__(self, responses: AsyncResponses) -> None:
        self._responses = responses

        self.create = async_to_streamed_response_wrapper(
            responses.create,
        )
        self.retrieve = async_to_streamed_response_wrapper(
            responses.retrieve,
        )
        self.delete = async_to_streamed_response_wrapper(
            responses.delete,
        )
        self.cancel = async_to_streamed_response_wrapper(
            responses.cancel,
        )
        self.compact = async_to_streamed_response_wrapper(
            responses.compact,
        )

    @cached_property
    def input_items(self) -> AsyncInputItemsWithStreamingResponse:
        return AsyncInputItemsWithStreamingResponse(self._responses.input_items)

    @cached_property
    def input_tokens(self) -> AsyncInputTokensWithStreamingResponse:
        return AsyncInputTokensWithStreamingResponse(self._responses.input_tokens)


def _make_tools(tools: Iterable[ParseableToolParam] | Omit) -> List[ToolParam] | Omit:
    if not is_given(tools):
        return omit

    converted_tools: List[ToolParam] = []
    for tool in tools:
        if tool["type"] != "function":
            converted_tools.append(tool)
            continue

        if "function" not in tool:
            # standard Responses API case
            converted_tools.append(tool)
            continue

        function = cast(Any, tool)["function"]  # pyright: ignore[reportUnnecessaryCast]
        if not isinstance(function, PydanticFunctionTool):
            raise Exception(
                "Expected Chat Completions function tool shape to be created using `openai.pydantic_function_tool()`"
            )

        assert "parameters" in function
        new_tool = ResponsesPydanticFunctionTool(
            {
                "type": "function",
                "name": function["name"],
                "description": function.get("description"),
                "parameters": function["parameters"],
                "strict": function.get("strict") or False,
            },
            function.model,
        )

        converted_tools.append(new_tool.cast())

    return converted_tools
