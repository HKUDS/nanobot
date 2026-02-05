# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Union, Mapping, Optional, cast
from typing_extensions import Literal, overload, assert_never

import httpx

from ... import _legacy_response
from ..._types import (
    Body,
    Omit,
    Query,
    Headers,
    NotGiven,
    FileTypes,
    SequenceNotStr,
    omit,
    not_given,
)
from ..._utils import extract_files, required_args, maybe_transform, deepcopy_minimal, async_maybe_transform
from ..._compat import cached_property
from ..._resource import SyncAPIResource, AsyncAPIResource
from ..._response import to_streamed_response_wrapper, async_to_streamed_response_wrapper
from ..._streaming import Stream, AsyncStream
from ...types.audio import transcription_create_params
from ..._base_client import make_request_options
from ...types.audio_model import AudioModel
from ...types.audio.transcription import Transcription
from ...types.audio_response_format import AudioResponseFormat
from ...types.audio.transcription_include import TranscriptionInclude
from ...types.audio.transcription_verbose import TranscriptionVerbose
from ...types.audio.transcription_diarized import TranscriptionDiarized
from ...types.audio.transcription_stream_event import TranscriptionStreamEvent
from ...types.audio.transcription_create_response import TranscriptionCreateResponse

__all__ = ["Transcriptions", "AsyncTranscriptions"]

log: logging.Logger = logging.getLogger("openai.audio.transcriptions")


class Transcriptions(SyncAPIResource):
    @cached_property
    def with_raw_response(self) -> TranscriptionsWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return TranscriptionsWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> TranscriptionsWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return TranscriptionsWithStreamingResponse(self)

    @overload
    def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        response_format: Union[Literal["json"], Omit] = omit,
        stream: Optional[Literal[False]] | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Transcription:
        """
        Transcribes audio into the input language.

        Args:
          file:
              The audio file object (not file name) to transcribe, in one of these formats:
              flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm.

          model: ID of the model to use. The options are `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, `gpt-4o-mini-transcribe-2025-12-15`, `whisper-1`
              (which is powered by our open source Whisper V2 model), and
              `gpt-4o-transcribe-diarize`.

          chunking_strategy: Controls how the audio is cut into chunks. When set to `"auto"`, the server
              first normalizes loudness and then uses voice activity detection (VAD) to choose
              boundaries. `server_vad` object can be provided to tweak VAD detection
              parameters manually. If unset, the audio is transcribed as a single block.

          include: Additional information to include in the transcription response. `logprobs` will
              return the log probabilities of the tokens in the response to understand the
              model's confidence in the transcription. `logprobs` only works with
              response_format set to `json` and only with the models `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, and `gpt-4o-mini-transcribe-2025-12-15`. This field is
              not supported when using `gpt-4o-transcribe-diarize`.

          language: The language of the input audio. Supplying the input language in
              [ISO-639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g. `en`)
              format will improve accuracy and latency.

          prompt: An optional text to guide the model's style or continue a previous audio
              segment. The
              [prompt](https://platform.openai.com/docs/guides/speech-to-text#prompting)
              should match the audio language.

          response_format: The format of the output, in one of these options: `json`, `text`, `srt`,
              `verbose_json`, or `vtt`. For `gpt-4o-transcribe` and `gpt-4o-mini-transcribe`,
              the only supported format is `json`.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section of the Speech-to-Text guide](https://platform.openai.com/docs/guides/speech-to-text?lang=curl#streaming-transcriptions)
              for more information.

              Note: Streaming is not supported for the `whisper-1` model and will be ignored.

          temperature: The sampling temperature, between 0 and 1. Higher values like 0.8 will make the
              output more random, while lower values like 0.2 will make it more focused and
              deterministic. If set to 0, the model will use
              [log probability](https://en.wikipedia.org/wiki/Log_probability) to
              automatically increase the temperature until certain thresholds are hit.

          timestamp_granularities: The timestamp granularities to populate for this transcription.
              `response_format` must be set `verbose_json` to use timestamp granularities.
              Either or both of these options are supported: `word`, or `segment`. Note: There
              is no additional latency for segment timestamps, but generating word timestamps
              incurs additional latency.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request
        """

    @overload
    def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        response_format: Literal["verbose_json"],
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> TranscriptionVerbose: ...

    @overload
    def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        response_format: Literal["text", "srt", "vtt"],
        include: List[TranscriptionInclude] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> str: ...

    @overload
    def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        response_format: Literal["diarized_json"],
        known_speaker_names: SequenceNotStr[str] | Omit = omit,
        known_speaker_references: SequenceNotStr[str] | Omit = omit,
        language: str | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> TranscriptionDiarized: ...

    @overload
    def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        stream: Literal[True],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        known_speaker_names: SequenceNotStr[str] | Omit = omit,
        known_speaker_references: SequenceNotStr[str] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        response_format: Union[AudioResponseFormat, Omit] = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Stream[TranscriptionStreamEvent]:
        """
        Transcribes audio into the input language.

        Args:
          file:
              The audio file object (not file name) to transcribe, in one of these formats:
              flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm.

          model: ID of the model to use. The options are `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, `gpt-4o-mini-transcribe-2025-12-15`, `whisper-1`
              (which is powered by our open source Whisper V2 model), and
              `gpt-4o-transcribe-diarize`.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section of the Speech-to-Text guide](https://platform.openai.com/docs/guides/speech-to-text?lang=curl#streaming-transcriptions)
              for more information.

              Note: Streaming is not supported for the `whisper-1` model and will be ignored.

          chunking_strategy: Controls how the audio is cut into chunks. When set to `"auto"`, the server
              first normalizes loudness and then uses voice activity detection (VAD) to choose
              boundaries. `server_vad` object can be provided to tweak VAD detection
              parameters manually. If unset, the audio is transcribed as a single block.
              Required when using `gpt-4o-transcribe-diarize` for inputs longer than 30
              seconds.

          include: Additional information to include in the transcription response. `logprobs` will
              return the log probabilities of the tokens in the response to understand the
              model's confidence in the transcription. `logprobs` only works with
              response_format set to `json` and only with the models `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, and `gpt-4o-mini-transcribe-2025-12-15`. This field is
              not supported when using `gpt-4o-transcribe-diarize`.

          known_speaker_names: Optional list of speaker names that correspond to the audio samples provided in
              `known_speaker_references[]`. Each entry should be a short identifier (for
              example `customer` or `agent`). Up to 4 speakers are supported.

          known_speaker_references: Optional list of audio samples (as
              [data URLs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs))
              that contain known speaker references matching `known_speaker_names[]`. Each
              sample must be between 2 and 10 seconds, and can use any of the same input audio
              formats supported by `file`.

          language: The language of the input audio. Supplying the input language in
              [ISO-639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g. `en`)
              format will improve accuracy and latency.

          prompt: An optional text to guide the model's style or continue a previous audio
              segment. The
              [prompt](https://platform.openai.com/docs/guides/speech-to-text#prompting)
              should match the audio language. This field is not supported when using
              `gpt-4o-transcribe-diarize`.

          response_format: The format of the output, in one of these options: `json`, `text`, `srt`,
              `verbose_json`, `vtt`, or `diarized_json`. For `gpt-4o-transcribe` and
              `gpt-4o-mini-transcribe`, the only supported format is `json`. For
              `gpt-4o-transcribe-diarize`, the supported formats are `json`, `text`, and
              `diarized_json`, with `diarized_json` required to receive speaker annotations.

          temperature: The sampling temperature, between 0 and 1. Higher values like 0.8 will make the
              output more random, while lower values like 0.2 will make it more focused and
              deterministic. If set to 0, the model will use
              [log probability](https://en.wikipedia.org/wiki/Log_probability) to
              automatically increase the temperature until certain thresholds are hit.

          timestamp_granularities: The timestamp granularities to populate for this transcription.
              `response_format` must be set `verbose_json` to use timestamp granularities.
              Either or both of these options are supported: `word`, or `segment`. Note: There
              is no additional latency for segment timestamps, but generating word timestamps
              incurs additional latency. This option is not available for
              `gpt-4o-transcribe-diarize`.

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
        file: FileTypes,
        model: Union[str, AudioModel],
        stream: bool,
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        known_speaker_names: SequenceNotStr[str] | Omit = omit,
        known_speaker_references: SequenceNotStr[str] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        response_format: Union[AudioResponseFormat, Omit] = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> TranscriptionCreateResponse | Stream[TranscriptionStreamEvent]:
        """
        Transcribes audio into the input language.

        Args:
          file:
              The audio file object (not file name) to transcribe, in one of these formats:
              flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm.

          model: ID of the model to use. The options are `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, `gpt-4o-mini-transcribe-2025-12-15`, `whisper-1`
              (which is powered by our open source Whisper V2 model), and
              `gpt-4o-transcribe-diarize`.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section of the Speech-to-Text guide](https://platform.openai.com/docs/guides/speech-to-text?lang=curl#streaming-transcriptions)
              for more information.

              Note: Streaming is not supported for the `whisper-1` model and will be ignored.

          chunking_strategy: Controls how the audio is cut into chunks. When set to `"auto"`, the server
              first normalizes loudness and then uses voice activity detection (VAD) to choose
              boundaries. `server_vad` object can be provided to tweak VAD detection
              parameters manually. If unset, the audio is transcribed as a single block.
              Required when using `gpt-4o-transcribe-diarize` for inputs longer than 30
              seconds.

          include: Additional information to include in the transcription response. `logprobs` will
              return the log probabilities of the tokens in the response to understand the
              model's confidence in the transcription. `logprobs` only works with
              response_format set to `json` and only with the models `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, and `gpt-4o-mini-transcribe-2025-12-15`. This field is
              not supported when using `gpt-4o-transcribe-diarize`.

          known_speaker_names: Optional list of speaker names that correspond to the audio samples provided in
              `known_speaker_references[]`. Each entry should be a short identifier (for
              example `customer` or `agent`). Up to 4 speakers are supported.

          known_speaker_references: Optional list of audio samples (as
              [data URLs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs))
              that contain known speaker references matching `known_speaker_names[]`. Each
              sample must be between 2 and 10 seconds, and can use any of the same input audio
              formats supported by `file`.

          language: The language of the input audio. Supplying the input language in
              [ISO-639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g. `en`)
              format will improve accuracy and latency.

          prompt: An optional text to guide the model's style or continue a previous audio
              segment. The
              [prompt](https://platform.openai.com/docs/guides/speech-to-text#prompting)
              should match the audio language. This field is not supported when using
              `gpt-4o-transcribe-diarize`.

          response_format: The format of the output, in one of these options: `json`, `text`, `srt`,
              `verbose_json`, `vtt`, or `diarized_json`. For `gpt-4o-transcribe` and
              `gpt-4o-mini-transcribe`, the only supported format is `json`. For
              `gpt-4o-transcribe-diarize`, the supported formats are `json`, `text`, and
              `diarized_json`, with `diarized_json` required to receive speaker annotations.

          temperature: The sampling temperature, between 0 and 1. Higher values like 0.8 will make the
              output more random, while lower values like 0.2 will make it more focused and
              deterministic. If set to 0, the model will use
              [log probability](https://en.wikipedia.org/wiki/Log_probability) to
              automatically increase the temperature until certain thresholds are hit.

          timestamp_granularities: The timestamp granularities to populate for this transcription.
              `response_format` must be set `verbose_json` to use timestamp granularities.
              Either or both of these options are supported: `word`, or `segment`. Note: There
              is no additional latency for segment timestamps, but generating word timestamps
              incurs additional latency. This option is not available for
              `gpt-4o-transcribe-diarize`.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @required_args(["file", "model"], ["file", "model", "stream"])
    def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        known_speaker_names: SequenceNotStr[str] | Omit = omit,
        known_speaker_references: SequenceNotStr[str] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        response_format: Union[AudioResponseFormat, Omit] = omit,
        stream: Optional[Literal[False]] | Literal[True] | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> str | Transcription | TranscriptionDiarized | TranscriptionVerbose | Stream[TranscriptionStreamEvent]:
        body = deepcopy_minimal(
            {
                "file": file,
                "model": model,
                "chunking_strategy": chunking_strategy,
                "include": include,
                "known_speaker_names": known_speaker_names,
                "known_speaker_references": known_speaker_references,
                "language": language,
                "prompt": prompt,
                "response_format": response_format,
                "stream": stream,
                "temperature": temperature,
                "timestamp_granularities": timestamp_granularities,
            }
        )
        files = extract_files(cast(Mapping[str, object], body), paths=[["file"]])
        # It should be noted that the actual Content-Type header that will be
        # sent to the server will contain a `boundary` parameter, e.g.
        # multipart/form-data; boundary=---abc--
        extra_headers = {"Content-Type": "multipart/form-data", **(extra_headers or {})}
        return self._post(  # type: ignore[return-value]
            "/audio/transcriptions",
            body=maybe_transform(
                body,
                transcription_create_params.TranscriptionCreateParamsStreaming
                if stream
                else transcription_create_params.TranscriptionCreateParamsNonStreaming,
            ),
            files=files,
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=_get_response_format_type(response_format),
            stream=stream or False,
            stream_cls=Stream[TranscriptionStreamEvent],
        )


class AsyncTranscriptions(AsyncAPIResource):
    @cached_property
    def with_raw_response(self) -> AsyncTranscriptionsWithRawResponse:
        """
        This property can be used as a prefix for any HTTP method call to return
        the raw response object instead of the parsed content.

        For more information, see https://www.github.com/openai/openai-python#accessing-raw-response-data-eg-headers
        """
        return AsyncTranscriptionsWithRawResponse(self)

    @cached_property
    def with_streaming_response(self) -> AsyncTranscriptionsWithStreamingResponse:
        """
        An alternative to `.with_raw_response` that doesn't eagerly read the response body.

        For more information, see https://www.github.com/openai/openai-python#with_streaming_response
        """
        return AsyncTranscriptionsWithStreamingResponse(self)

    @overload
    async def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        known_speaker_names: SequenceNotStr[str] | Omit = omit,
        known_speaker_references: SequenceNotStr[str] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        response_format: Union[Literal["json"], Omit] = omit,
        stream: Optional[Literal[False]] | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> TranscriptionCreateResponse:
        """
        Transcribes audio into the input language.

        Args:
          file:
              The audio file object (not file name) to transcribe, in one of these formats:
              flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm.

          model: ID of the model to use. The options are `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, `gpt-4o-mini-transcribe-2025-12-15`, `whisper-1`
              (which is powered by our open source Whisper V2 model), and
              `gpt-4o-transcribe-diarize`.

          chunking_strategy: Controls how the audio is cut into chunks. When set to `"auto"`, the server
              first normalizes loudness and then uses voice activity detection (VAD) to choose
              boundaries. `server_vad` object can be provided to tweak VAD detection
              parameters manually. If unset, the audio is transcribed as a single block.
              Required when using `gpt-4o-transcribe-diarize` for inputs longer than 30
              seconds.

          include: Additional information to include in the transcription response. `logprobs` will
              return the log probabilities of the tokens in the response to understand the
              model's confidence in the transcription. `logprobs` only works with
              response_format set to `json` and only with the models `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, and `gpt-4o-mini-transcribe-2025-12-15`. This field is
              not supported when using `gpt-4o-transcribe-diarize`.

          known_speaker_names: Optional list of speaker names that correspond to the audio samples provided in
              `known_speaker_references[]`. Each entry should be a short identifier (for
              example `customer` or `agent`). Up to 4 speakers are supported.

          known_speaker_references: Optional list of audio samples (as
              [data URLs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs))
              that contain known speaker references matching `known_speaker_names[]`. Each
              sample must be between 2 and 10 seconds, and can use any of the same input audio
              formats supported by `file`.

          language: The language of the input audio. Supplying the input language in
              [ISO-639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g. `en`)
              format will improve accuracy and latency.

          prompt: An optional text to guide the model's style or continue a previous audio
              segment. The
              [prompt](https://platform.openai.com/docs/guides/speech-to-text#prompting)
              should match the audio language. This field is not supported when using
              `gpt-4o-transcribe-diarize`.

          response_format: The format of the output, in one of these options: `json`, `text`, `srt`,
              `verbose_json`, `vtt`, or `diarized_json`. For `gpt-4o-transcribe` and
              `gpt-4o-mini-transcribe`, the only supported format is `json`. For
              `gpt-4o-transcribe-diarize`, the supported formats are `json`, `text`, and
              `diarized_json`, with `diarized_json` required to receive speaker annotations.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section of the Speech-to-Text guide](https://platform.openai.com/docs/guides/speech-to-text?lang=curl#streaming-transcriptions)
              for more information.

              Note: Streaming is not supported for the `whisper-1` model and will be ignored.

          temperature: The sampling temperature, between 0 and 1. Higher values like 0.8 will make the
              output more random, while lower values like 0.2 will make it more focused and
              deterministic. If set to 0, the model will use
              [log probability](https://en.wikipedia.org/wiki/Log_probability) to
              automatically increase the temperature until certain thresholds are hit.

          timestamp_granularities: The timestamp granularities to populate for this transcription.
              `response_format` must be set `verbose_json` to use timestamp granularities.
              Either or both of these options are supported: `word`, or `segment`. Note: There
              is no additional latency for segment timestamps, but generating word timestamps
              incurs additional latency. This option is not available for
              `gpt-4o-transcribe-diarize`.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request
        """

    @overload
    async def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        response_format: Literal["verbose_json"],
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> TranscriptionVerbose: ...

    @overload
    async def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        response_format: Literal["text", "srt", "vtt"],
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> str: ...

    @overload
    async def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        stream: Literal[True],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        known_speaker_names: SequenceNotStr[str] | Omit = omit,
        known_speaker_references: SequenceNotStr[str] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        response_format: Union[AudioResponseFormat, Omit] = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> AsyncStream[TranscriptionStreamEvent]:
        """
        Transcribes audio into the input language.

        Args:
          file:
              The audio file object (not file name) to transcribe, in one of these formats:
              flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm.

          model: ID of the model to use. The options are `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, `gpt-4o-mini-transcribe-2025-12-15`, `whisper-1`
              (which is powered by our open source Whisper V2 model), and
              `gpt-4o-transcribe-diarize`.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section of the Speech-to-Text guide](https://platform.openai.com/docs/guides/speech-to-text?lang=curl#streaming-transcriptions)
              for more information.

              Note: Streaming is not supported for the `whisper-1` model and will be ignored.

          chunking_strategy: Controls how the audio is cut into chunks. When set to `"auto"`, the server
              first normalizes loudness and then uses voice activity detection (VAD) to choose
              boundaries. `server_vad` object can be provided to tweak VAD detection
              parameters manually. If unset, the audio is transcribed as a single block.
              Required when using `gpt-4o-transcribe-diarize` for inputs longer than 30
              seconds.

          include: Additional information to include in the transcription response. `logprobs` will
              return the log probabilities of the tokens in the response to understand the
              model's confidence in the transcription. `logprobs` only works with
              response_format set to `json` and only with the models `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, and `gpt-4o-mini-transcribe-2025-12-15`. This field is
              not supported when using `gpt-4o-transcribe-diarize`.

          known_speaker_names: Optional list of speaker names that correspond to the audio samples provided in
              `known_speaker_references[]`. Each entry should be a short identifier (for
              example `customer` or `agent`). Up to 4 speakers are supported.

          known_speaker_references: Optional list of audio samples (as
              [data URLs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs))
              that contain known speaker references matching `known_speaker_names[]`. Each
              sample must be between 2 and 10 seconds, and can use any of the same input audio
              formats supported by `file`.

          language: The language of the input audio. Supplying the input language in
              [ISO-639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g. `en`)
              format will improve accuracy and latency.

          prompt: An optional text to guide the model's style or continue a previous audio
              segment. The
              [prompt](https://platform.openai.com/docs/guides/speech-to-text#prompting)
              should match the audio language. This field is not supported when using
              `gpt-4o-transcribe-diarize`.

          response_format: The format of the output, in one of these options: `json`, `text`, `srt`,
              `verbose_json`, `vtt`, or `diarized_json`. For `gpt-4o-transcribe` and
              `gpt-4o-mini-transcribe`, the only supported format is `json`. For
              `gpt-4o-transcribe-diarize`, the supported formats are `json`, `text`, and
              `diarized_json`, with `diarized_json` required to receive speaker annotations.

          temperature: The sampling temperature, between 0 and 1. Higher values like 0.8 will make the
              output more random, while lower values like 0.2 will make it more focused and
              deterministic. If set to 0, the model will use
              [log probability](https://en.wikipedia.org/wiki/Log_probability) to
              automatically increase the temperature until certain thresholds are hit.

          timestamp_granularities: The timestamp granularities to populate for this transcription.
              `response_format` must be set `verbose_json` to use timestamp granularities.
              Either or both of these options are supported: `word`, or `segment`. Note: There
              is no additional latency for segment timestamps, but generating word timestamps
              incurs additional latency. This option is not available for
              `gpt-4o-transcribe-diarize`.

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
        file: FileTypes,
        model: Union[str, AudioModel],
        stream: bool,
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        known_speaker_names: SequenceNotStr[str] | Omit = omit,
        known_speaker_references: SequenceNotStr[str] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        response_format: Union[AudioResponseFormat, Omit] = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> TranscriptionCreateResponse | AsyncStream[TranscriptionStreamEvent]:
        """
        Transcribes audio into the input language.

        Args:
          file:
              The audio file object (not file name) to transcribe, in one of these formats:
              flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm.

          model: ID of the model to use. The options are `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, `gpt-4o-mini-transcribe-2025-12-15`, `whisper-1`
              (which is powered by our open source Whisper V2 model), and
              `gpt-4o-transcribe-diarize`.

          stream: If set to true, the model response data will be streamed to the client as it is
              generated using
              [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
              See the
              [Streaming section of the Speech-to-Text guide](https://platform.openai.com/docs/guides/speech-to-text?lang=curl#streaming-transcriptions)
              for more information.

              Note: Streaming is not supported for the `whisper-1` model and will be ignored.

          chunking_strategy: Controls how the audio is cut into chunks. When set to `"auto"`, the server
              first normalizes loudness and then uses voice activity detection (VAD) to choose
              boundaries. `server_vad` object can be provided to tweak VAD detection
              parameters manually. If unset, the audio is transcribed as a single block.
              Required when using `gpt-4o-transcribe-diarize` for inputs longer than 30
              seconds.

          include: Additional information to include in the transcription response. `logprobs` will
              return the log probabilities of the tokens in the response to understand the
              model's confidence in the transcription. `logprobs` only works with
              response_format set to `json` and only with the models `gpt-4o-transcribe`,
              `gpt-4o-mini-transcribe`, and `gpt-4o-mini-transcribe-2025-12-15`. This field is
              not supported when using `gpt-4o-transcribe-diarize`.

          known_speaker_names: Optional list of speaker names that correspond to the audio samples provided in
              `known_speaker_references[]`. Each entry should be a short identifier (for
              example `customer` or `agent`). Up to 4 speakers are supported.

          known_speaker_references: Optional list of audio samples (as
              [data URLs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs))
              that contain known speaker references matching `known_speaker_names[]`. Each
              sample must be between 2 and 10 seconds, and can use any of the same input audio
              formats supported by `file`.

          language: The language of the input audio. Supplying the input language in
              [ISO-639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g. `en`)
              format will improve accuracy and latency.

          prompt: An optional text to guide the model's style or continue a previous audio
              segment. The
              [prompt](https://platform.openai.com/docs/guides/speech-to-text#prompting)
              should match the audio language. This field is not supported when using
              `gpt-4o-transcribe-diarize`.

          response_format: The format of the output, in one of these options: `json`, `text`, `srt`,
              `verbose_json`, `vtt`, or `diarized_json`. For `gpt-4o-transcribe` and
              `gpt-4o-mini-transcribe`, the only supported format is `json`. For
              `gpt-4o-transcribe-diarize`, the supported formats are `json`, `text`, and
              `diarized_json`, with `diarized_json` required to receive speaker annotations.

          temperature: The sampling temperature, between 0 and 1. Higher values like 0.8 will make the
              output more random, while lower values like 0.2 will make it more focused and
              deterministic. If set to 0, the model will use
              [log probability](https://en.wikipedia.org/wiki/Log_probability) to
              automatically increase the temperature until certain thresholds are hit.

          timestamp_granularities: The timestamp granularities to populate for this transcription.
              `response_format` must be set `verbose_json` to use timestamp granularities.
              Either or both of these options are supported: `word`, or `segment`. Note: There
              is no additional latency for segment timestamps, but generating word timestamps
              incurs additional latency. This option is not available for
              `gpt-4o-transcribe-diarize`.

          extra_headers: Send extra headers

          extra_query: Add additional query parameters to the request

          extra_body: Add additional JSON properties to the request

          timeout: Override the client-level default timeout for this request, in seconds
        """
        ...

    @required_args(["file", "model"], ["file", "model", "stream"])
    async def create(
        self,
        *,
        file: FileTypes,
        model: Union[str, AudioModel],
        chunking_strategy: Optional[transcription_create_params.ChunkingStrategy] | Omit = omit,
        include: List[TranscriptionInclude] | Omit = omit,
        known_speaker_names: SequenceNotStr[str] | Omit = omit,
        known_speaker_references: SequenceNotStr[str] | Omit = omit,
        language: str | Omit = omit,
        prompt: str | Omit = omit,
        response_format: Union[AudioResponseFormat, Omit] = omit,
        stream: Optional[Literal[False]] | Literal[True] | Omit = omit,
        temperature: float | Omit = omit,
        timestamp_granularities: List[Literal["word", "segment"]] | Omit = omit,
        # Use the following arguments if you need to pass additional parameters to the API that aren't available via kwargs.
        # The extra values given here take precedence over values defined on the client or passed to this method.
        extra_headers: Headers | None = None,
        extra_query: Query | None = None,
        extra_body: Body | None = None,
        timeout: float | httpx.Timeout | None | NotGiven = not_given,
    ) -> Transcription | TranscriptionVerbose | TranscriptionDiarized | str | AsyncStream[TranscriptionStreamEvent]:
        body = deepcopy_minimal(
            {
                "file": file,
                "model": model,
                "chunking_strategy": chunking_strategy,
                "include": include,
                "known_speaker_names": known_speaker_names,
                "known_speaker_references": known_speaker_references,
                "language": language,
                "prompt": prompt,
                "response_format": response_format,
                "stream": stream,
                "temperature": temperature,
                "timestamp_granularities": timestamp_granularities,
            }
        )
        files = extract_files(cast(Mapping[str, object], body), paths=[["file"]])
        # It should be noted that the actual Content-Type header that will be
        # sent to the server will contain a `boundary` parameter, e.g.
        # multipart/form-data; boundary=---abc--
        extra_headers = {"Content-Type": "multipart/form-data", **(extra_headers or {})}
        return await self._post(
            "/audio/transcriptions",
            body=await async_maybe_transform(
                body,
                transcription_create_params.TranscriptionCreateParamsStreaming
                if stream
                else transcription_create_params.TranscriptionCreateParamsNonStreaming,
            ),
            files=files,
            options=make_request_options(
                extra_headers=extra_headers, extra_query=extra_query, extra_body=extra_body, timeout=timeout
            ),
            cast_to=_get_response_format_type(response_format),
            stream=stream or False,
            stream_cls=AsyncStream[TranscriptionStreamEvent],
        )


class TranscriptionsWithRawResponse:
    def __init__(self, transcriptions: Transcriptions) -> None:
        self._transcriptions = transcriptions

        self.create = _legacy_response.to_raw_response_wrapper(
            transcriptions.create,
        )


class AsyncTranscriptionsWithRawResponse:
    def __init__(self, transcriptions: AsyncTranscriptions) -> None:
        self._transcriptions = transcriptions

        self.create = _legacy_response.async_to_raw_response_wrapper(
            transcriptions.create,
        )


class TranscriptionsWithStreamingResponse:
    def __init__(self, transcriptions: Transcriptions) -> None:
        self._transcriptions = transcriptions

        self.create = to_streamed_response_wrapper(
            transcriptions.create,
        )


class AsyncTranscriptionsWithStreamingResponse:
    def __init__(self, transcriptions: AsyncTranscriptions) -> None:
        self._transcriptions = transcriptions

        self.create = async_to_streamed_response_wrapper(
            transcriptions.create,
        )


def _get_response_format_type(
    response_format: AudioResponseFormat | Omit,
) -> type[Transcription | TranscriptionVerbose | TranscriptionDiarized | str]:
    if isinstance(response_format, Omit) or response_format is None:  # pyright: ignore[reportUnnecessaryComparison]
        return Transcription

    if response_format == "json":
        return Transcription
    elif response_format == "verbose_json":
        return TranscriptionVerbose
    elif response_format == "diarized_json":
        return TranscriptionDiarized
    elif response_format == "srt" or response_format == "text" or response_format == "vtt":
        return str
    elif TYPE_CHECKING:  # type: ignore[unreachable]
        assert_never(response_format)
    else:
        log.warn("Unexpected audio response format: %s", response_format)
        return Transcription
