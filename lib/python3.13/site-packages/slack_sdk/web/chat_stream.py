import json
import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Union

import slack_sdk.errors as e
from slack_sdk.models.blocks.blocks import Block
from slack_sdk.models.messages.chunk import Chunk, MarkdownTextChunk
from slack_sdk.models.metadata import Metadata
from slack_sdk.web.slack_response import SlackResponse

if TYPE_CHECKING:
    from slack_sdk import WebClient


class ChatStream:
    """A helper class for streaming markdown text into a conversation using the chat streaming APIs.

    This class provides a convenient interface for the chat.startStream, chat.appendStream, and chat.stopStream API
    methods, with automatic buffering and state management.
    """

    def __init__(
        self,
        client: "WebClient",
        *,
        channel: str,
        logger: logging.Logger,
        thread_ts: str,
        buffer_size: int,
        recipient_team_id: Optional[str] = None,
        recipient_user_id: Optional[str] = None,
        task_display_mode: Optional[str] = None,
        **kwargs,
    ):
        """Initialize a new ChatStream instance.

        The __init__ method creates a unique ChatStream instance that keeps track of one chat stream.

        Args:
            client: The WebClient instance to use for API calls.
            channel: An encoded ID that represents a channel, private group, or DM.
            logger: A logging channel for outputs.
            thread_ts: Provide another message's ts value to reply to. Streamed messages should always be replies to a user
              request.
            recipient_team_id: The encoded ID of the team the user receiving the streaming text belongs to. Required when
              streaming to channels.
            recipient_user_id: The encoded ID of the user to receive the streaming text. Required when streaming to channels.
            task_display_mode: Specifies how tasks are displayed in the message. A "timeline" displays individual tasks
              with text and "plan" displays all tasks together.
            buffer_size: The length of markdown_text to buffer in-memory before calling a method. Increasing this value
              decreases the number of method calls made for the same amount of text, which is useful to avoid rate limits.
            **kwargs: Additional arguments passed to the underlying API calls.
        """
        self._client = client
        self._logger = logger
        self._token: Optional[str] = kwargs.pop("token", None)
        self._stream_args = {
            "channel": channel,
            "thread_ts": thread_ts,
            "recipient_team_id": recipient_team_id,
            "recipient_user_id": recipient_user_id,
            "task_display_mode": task_display_mode,
            **kwargs,
        }
        self._buffer = ""
        self._state = "starting"
        self._stream_ts: Optional[str] = None
        self._buffer_size = buffer_size

    def append(
        self,
        *,
        markdown_text: Optional[str] = None,
        chunks: Optional[Sequence[Union[Dict, Chunk]]] = None,
        **kwargs,
    ) -> Optional[SlackResponse]:
        """Append to the stream.

        The "append" method appends to the chat stream being used. This method can be called multiple times. After the stream
        is stopped this method cannot be called.

        Args:
            chunks: An array of streaming chunks. Chunks can be markdown text, plan, or task update chunks.
            markdown_text: Accepts message text formatted in markdown. Limit this field to 12,000 characters. This text is
              what will be appended to the message received so far.
            **kwargs: Additional arguments passed to the underlying API calls.

        Returns:
            SlackResponse if the buffer was flushed, None if buffering.

        Raises:
            SlackRequestError: If the stream is already completed.

        Example:
            ```python
            streamer = client.chat_stream(
                channel="C0123456789",
                thread_ts="1700000001.123456",
                recipient_team_id="T0123456789",
                recipient_user_id="U0123456789",
            )
            streamer.append(markdown_text="**hello wo")
            streamer.append(markdown_text="rld!**")
            streamer.stop()
            ```
        """
        if self._state == "completed":
            raise e.SlackRequestError(f"Cannot append to stream: stream state is {self._state}")
        if kwargs.get("token"):
            self._token = kwargs.pop("token")
        if markdown_text is not None:
            self._buffer += markdown_text
        if len(self._buffer) >= self._buffer_size or chunks is not None:
            return self._flush_buffer(chunks=chunks, **kwargs)
        details = {
            "buffer_length": len(self._buffer),
            "buffer_size": self._buffer_size,
            "channel": self._stream_args.get("channel"),
            "recipient_team_id": self._stream_args.get("recipient_team_id"),
            "recipient_user_id": self._stream_args.get("recipient_user_id"),
            "thread_ts": self._stream_args.get("thread_ts"),
        }
        self._logger.debug(f"ChatStream appended to buffer: {json.dumps(details)}")
        return None

    def stop(
        self,
        *,
        markdown_text: Optional[str] = None,
        chunks: Optional[Sequence[Union[Dict, Chunk]]] = None,
        blocks: Optional[Union[str, Sequence[Union[Dict, Block]]]] = None,
        metadata: Optional[Union[Dict, Metadata]] = None,
        **kwargs,
    ) -> SlackResponse:
        """Stop the stream and finalize the message.

        Args:
            blocks: A list of blocks that will be rendered at the bottom of the finalized message.
            chunks: An array of streaming chunks. Chunks can be markdown text, plan, or task update chunks.
            markdown_text: Accepts message text formatted in markdown. Limit this field to 12,000 characters. This text is
              what will be appended to the message received so far.
            metadata: JSON object with event_type and event_payload fields, presented as a URL-encoded string. Metadata you
              post to Slack is accessible to any app or user who is a member of that workspace.
            **kwargs: Additional arguments passed to the underlying API calls.

        Returns:
            SlackResponse from the chat.stopStream API call.

        Raises:
            SlackRequestError: If the stream is already completed.

        Example:
            ```python
            streamer = client.chat_stream(
                channel="C0123456789",
                thread_ts="1700000001.123456",
                recipient_team_id="T0123456789",
                recipient_user_id="U0123456789",
            )
            streamer.append(markdown_text="**hello wo")
            streamer.append(markdown_text="rld!**")
            streamer.stop()
            ```
        """
        if self._state == "completed":
            raise e.SlackRequestError(f"Cannot stop stream: stream state is {self._state}")
        if kwargs.get("token"):
            self._token = kwargs.pop("token")
        if markdown_text:
            self._buffer += markdown_text
        if not self._stream_ts:
            response = self._client.chat_startStream(
                **self._stream_args,
                token=self._token,
            )
            if not response.get("ts"):
                raise e.SlackRequestError("Failed to stop stream: stream not started")
            self._stream_ts = str(response["ts"])
            self._state = "in_progress"
        flushings: List[Union[Dict, Chunk]] = []
        if len(self._buffer) != 0:
            flushings.append(MarkdownTextChunk(text=self._buffer))
        if chunks is not None:
            flushings.extend(chunks)
        response = self._client.chat_stopStream(
            token=self._token,
            channel=self._stream_args["channel"],
            ts=self._stream_ts,
            blocks=blocks,
            chunks=flushings,
            metadata=metadata,
            **kwargs,
        )
        self._state = "completed"
        return response

    def _flush_buffer(self, chunks: Optional[Sequence[Union[Dict, Chunk]]] = None, **kwargs) -> SlackResponse:
        """Flush the internal buffer with chunks by making appropriate API calls."""
        chunks_to_flush: List[Union[Dict, Chunk]] = []
        if len(self._buffer) != 0:
            chunks_to_flush.append(MarkdownTextChunk(text=self._buffer))
        if chunks is not None:
            chunks_to_flush.extend(chunks)
        if not self._stream_ts:
            response = self._client.chat_startStream(
                **self._stream_args,
                token=self._token,
                **kwargs,
                chunks=chunks_to_flush,
            )
            self._stream_ts = response.get("ts")
            self._state = "in_progress"
        else:
            response = self._client.chat_appendStream(
                token=self._token,
                channel=self._stream_args["channel"],
                ts=self._stream_ts,
                **kwargs,
                chunks=chunks_to_flush,
            )
        self._buffer = ""
        return response
