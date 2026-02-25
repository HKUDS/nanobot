# coding=utf-8
# Copyright 2023-present, the HuggingFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Contains utilities used by both the sync and async inference clients."""

import base64
import io
import json
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterable, BinaryIO, Iterable, Literal, NoReturn, Optional, Union, overload

import httpx

from huggingface_hub.errors import (
    GenerationError,
    HfHubHTTPError,
    IncompleteGenerationError,
    OverloadedError,
    TextGenerationError,
    UnknownError,
    ValidationError,
)

from ..utils import get_session, is_numpy_available, is_pillow_available
from ._generated.types import ChatCompletionStreamOutput, TextGenerationStreamOutput


if TYPE_CHECKING:
    from PIL.Image import Image

# TYPES
UrlT = str
PathT = Union[str, Path]
ContentT = Union[bytes, BinaryIO, PathT, UrlT, "Image", bytearray, memoryview]

# Use to set an Accept: image/png header
TASKS_EXPECTING_IMAGES = {"text-to-image", "image-to-image"}

logger = logging.getLogger(__name__)


@dataclass
class RequestParameters:
    url: str
    task: str
    model: Optional[str]
    json: Optional[Union[str, dict, list]]
    data: Optional[bytes]
    headers: dict[str, Any]


class MimeBytes(bytes):
    """
    A bytes object with a mime type.
    To be returned by `_prepare_payload_open_as_mime_bytes` in subclasses.

    Example:
    ```python
        >>> b = MimeBytes(b"hello", "text/plain")
        >>> isinstance(b, bytes)
        True
        >>> b.mime_type
        'text/plain'
    ```
    """

    mime_type: Optional[str]

    def __new__(cls, data: bytes, mime_type: Optional[str] = None):
        obj = super().__new__(cls, data)
        obj.mime_type = mime_type
        if isinstance(data, MimeBytes) and mime_type is None:
            obj.mime_type = data.mime_type
        return obj


## IMPORT UTILS


def _import_numpy():
    """Make sure `numpy` is installed on the machine."""
    if not is_numpy_available():
        raise ImportError("Please install numpy to use deal with embeddings (`pip install numpy`).")
    import numpy

    return numpy


def _import_pil_image():
    """Make sure `PIL` is installed on the machine."""
    if not is_pillow_available():
        raise ImportError(
            "Please install Pillow to use deal with images (`pip install Pillow`). If you don't want the image to be"
            " post-processed, use `client.post(...)` and get the raw response from the server."
        )
    from PIL import Image

    return Image


## ENCODING / DECODING UTILS


@overload
def _open_as_mime_bytes(content: ContentT) -> MimeBytes: ...  # means "if input is not None, output is not None"


@overload
def _open_as_mime_bytes(content: Literal[None]) -> Literal[None]: ...  # means "if input is None, output is None"


def _open_as_mime_bytes(content: Optional[ContentT]) -> Optional[MimeBytes]:
    """Open `content` as a binary file, either from a URL, a local path, raw bytes, or a PIL Image.

    Do nothing if `content` is None.
    """
    # If content is None, yield None
    if content is None:
        return None

    # If content is bytes, return it
    if isinstance(content, bytes):
        return MimeBytes(content)

    # If content is raw binary data (bytearray, memoryview)
    if isinstance(content, (bytearray, memoryview)):
        return MimeBytes(bytes(content))

    # If content is a binary file-like object
    if hasattr(content, "read"):  # duck-typing instead of isinstance(content, BinaryIO)
        logger.debug("Reading content from BinaryIO")
        data = content.read()
        mime_type = mimetypes.guess_type(str(content.name))[0] if hasattr(content, "name") else None
        if isinstance(data, str):
            raise TypeError("Expected binary stream (bytes), but got text stream")
        return MimeBytes(data, mime_type=mime_type)

    # If content is a string => must be either a URL or a path
    if isinstance(content, str):
        if content.startswith("https://") or content.startswith("http://"):
            logger.debug(f"Downloading content from {content}")
            response = get_session().get(content)
            mime_type = response.headers.get("Content-Type")
            if mime_type is None:
                mime_type = mimetypes.guess_type(content)[0]
            return MimeBytes(response.content, mime_type=mime_type)

        content = Path(content)
        if not content.exists():
            raise FileNotFoundError(
                f"File not found at {content}. If `data` is a string, it must either be a URL or a path to a local"
                " file. To pass raw content, please encode it as bytes first."
            )

    # If content is a Path => open it
    if isinstance(content, Path):
        logger.debug(f"Opening content from {content}")
        return MimeBytes(content.read_bytes(), mime_type=mimetypes.guess_type(content)[0])

    # If content is a PIL Image => convert to bytes
    if is_pillow_available():
        from PIL import Image

        if isinstance(content, Image.Image):
            logger.debug("Converting PIL Image to bytes")
            buffer = io.BytesIO()
            format = content.format or "PNG"
            content.save(buffer, format=format)
            return MimeBytes(buffer.getvalue(), mime_type=f"image/{format.lower()}")

    # If nothing matched, raise error
    raise TypeError(
        f"Unsupported content type: {type(content)}. "
        "Expected one of: bytes, bytearray, BinaryIO, memoryview, Path, str (URL or file path), or PIL.Image.Image."
    )


def _b64_encode(content: ContentT) -> str:
    """Encode a raw file (image, audio) into base64. Can be bytes, an opened file, a path or a URL."""
    raw_bytes = _open_as_mime_bytes(content)
    return base64.b64encode(raw_bytes).decode()


def _as_url(content: ContentT, default_mime_type: str) -> str:
    if isinstance(content, str) and content.startswith(("http://", "https://", "data:")):
        return content

    # Convert content to bytes
    raw_bytes = _open_as_mime_bytes(content)

    # Get MIME type
    mime_type = raw_bytes.mime_type or default_mime_type

    # Encode content to base64
    encoded_data = base64.b64encode(raw_bytes).decode()

    # Build data URL
    return f"data:{mime_type};base64,{encoded_data}"


def _b64_to_image(encoded_image: str) -> "Image":
    """Parse a base64-encoded string into a PIL Image."""
    Image = _import_pil_image()
    return Image.open(io.BytesIO(base64.b64decode(encoded_image)))


def _bytes_to_list(content: bytes) -> list:
    """Parse bytes from a Response object into a Python list.

    Expects the response body to be JSON-encoded data.

    NOTE: This is exactly the same implementation as `_bytes_to_dict` and will not complain if the returned data is a
    dictionary. The only advantage of having both is to help the user (and mypy) understand what kind of data to expect.
    """
    return json.loads(content.decode())


def _bytes_to_dict(content: bytes) -> dict:
    """Parse bytes from a Response object into a Python dictionary.

    Expects the response body to be JSON-encoded data.

    NOTE: This is exactly the same implementation as `_bytes_to_list` and will not complain if the returned data is a
    list. The only advantage of having both is to help the user (and mypy) understand what kind of data to expect.
    """
    return json.loads(content.decode())


def _bytes_to_image(content: bytes) -> "Image":
    """Parse bytes from a Response object into a PIL Image.

    Expects the response body to be raw bytes. To deal with b64 encoded images, use `_b64_to_image` instead.
    """
    Image = _import_pil_image()
    return Image.open(io.BytesIO(content))


def _as_dict(response: Union[bytes, dict]) -> dict:
    return json.loads(response) if isinstance(response, bytes) else response


## STREAMING UTILS


def _stream_text_generation_response(
    output_lines: Iterable[str], details: bool
) -> Union[Iterable[str], Iterable[TextGenerationStreamOutput]]:
    """Used in `InferenceClient.text_generation`."""
    # Parse ServerSentEvents
    for line in output_lines:
        try:
            output = _format_text_generation_stream_output(line, details)
        except StopIteration:
            break
        if output is not None:
            yield output


async def _async_stream_text_generation_response(
    output_lines: AsyncIterable[str], details: bool
) -> Union[AsyncIterable[str], AsyncIterable[TextGenerationStreamOutput]]:
    """Used in `AsyncInferenceClient.text_generation`."""
    # Parse ServerSentEvents
    async for line in output_lines:
        try:
            output = _format_text_generation_stream_output(line, details)
        except StopIteration:
            break
        if output is not None:
            yield output


def _format_text_generation_stream_output(
    line: str, details: bool
) -> Optional[Union[str, TextGenerationStreamOutput]]:
    if not line.startswith("data:"):
        return None  # empty line

    if line.strip() == "data: [DONE]":
        raise StopIteration("[DONE] signal received.")

    # Decode payload
    payload = line.lstrip("data:").rstrip("/n")
    json_payload = json.loads(payload)

    # Either an error as being returned
    if json_payload.get("error") is not None:
        raise _parse_text_generation_error(json_payload["error"], json_payload.get("error_type"))

    # Or parse token payload
    output = TextGenerationStreamOutput.parse_obj_as_instance(json_payload)
    return output.token.text if not details else output


def _stream_chat_completion_response(
    lines: Iterable[str],
) -> Iterable[ChatCompletionStreamOutput]:
    """Used in `InferenceClient.chat_completion` if model is served with TGI."""
    for line in lines:
        try:
            output = _format_chat_completion_stream_output(line)
        except StopIteration:
            break
        if output is not None:
            yield output


async def _async_stream_chat_completion_response(
    lines: AsyncIterable[str],
) -> AsyncIterable[ChatCompletionStreamOutput]:
    """Used in `AsyncInferenceClient.chat_completion`."""
    async for line in lines:
        try:
            output = _format_chat_completion_stream_output(line)
        except StopIteration:
            break
        if output is not None:
            yield output


def _format_chat_completion_stream_output(
    line: str,
) -> Optional[ChatCompletionStreamOutput]:
    if not line.startswith("data:"):
        return None  # empty line

    if line.strip() == "data: [DONE]":
        raise StopIteration("[DONE] signal received.")

    # Decode payload
    json_payload = json.loads(line.lstrip("data:").strip())

    # Either an error as being returned
    if json_payload.get("error") is not None:
        raise _parse_text_generation_error(json_payload["error"], json_payload.get("error_type"))

    # Or parse token payload
    return ChatCompletionStreamOutput.parse_obj_as_instance(json_payload)


async def _async_yield_from(client: httpx.AsyncClient, response: httpx.Response) -> AsyncIterable[str]:
    async for line in response.aiter_lines():
        yield line.strip()


# "TGI servers" are servers running with the `text-generation-inference` backend.
# This backend is the go-to solution to run large language models at scale. However,
# for some smaller models (e.g. "gpt2") the default `transformers` + `api-inference`
# solution is still in use.
#
# Both approaches have very similar APIs, but not exactly the same. What we do first in
# the `text_generation` method is to assume the model is served via TGI. If we realize
# it's not the case (i.e. we receive an HTTP 400 Bad Request), we fall back to the
# default API with a warning message. When that's the case, We remember the unsupported
# attributes for this model in the `_UNSUPPORTED_TEXT_GENERATION_KWARGS` global variable.
#
# In addition, TGI servers have a built-in API route for chat-completion, which is not
# available on the default API. We use this route to provide a more consistent behavior
# when available.
#
# For more details, see https://github.com/huggingface/text-generation-inference and
# https://huggingface.co/docs/api-inference/detailed_parameters#text-generation-task.

_UNSUPPORTED_TEXT_GENERATION_KWARGS: dict[Optional[str], list[str]] = {}


def _set_unsupported_text_generation_kwargs(model: Optional[str], unsupported_kwargs: list[str]) -> None:
    _UNSUPPORTED_TEXT_GENERATION_KWARGS.setdefault(model, []).extend(unsupported_kwargs)


def _get_unsupported_text_generation_kwargs(model: Optional[str]) -> list[str]:
    return _UNSUPPORTED_TEXT_GENERATION_KWARGS.get(model, [])


# TEXT GENERATION ERRORS
# ----------------------
# Text-generation errors are parsed separately to handle as much as possible the errors returned by the text generation
# inference project (https://github.com/huggingface/text-generation-inference).
# ----------------------


def raise_text_generation_error(http_error: HfHubHTTPError) -> NoReturn:
    """
    Try to parse text-generation-inference error message and raise HTTPError in any case.

    Args:
        error (`HTTPError`):
            The HTTPError that have been raised.
    """
    # Try to parse a Text Generation Inference error
    if http_error.response is None:
        raise http_error

    try:
        # Hacky way to retrieve payload in case of aiohttp error
        payload = getattr(http_error, "response_error_payload", None) or http_error.response.json()
        error = payload.get("error")
        error_type = payload.get("error_type")
    except Exception:  # no payload
        raise http_error

    # If error_type => more information than `hf_raise_for_status`
    if error_type is not None:
        exception = _parse_text_generation_error(error, error_type)
        raise exception from http_error

    # Otherwise, fallback to default error
    raise http_error


def _parse_text_generation_error(error: Optional[str], error_type: Optional[str]) -> TextGenerationError:
    if error_type == "generation":
        return GenerationError(error)  # type: ignore
    if error_type == "incomplete_generation":
        return IncompleteGenerationError(error)  # type: ignore
    if error_type == "overloaded":
        return OverloadedError(error)  # type: ignore
    if error_type == "validation":
        return ValidationError(error)  # type: ignore
    return UnknownError(error)  # type: ignore
