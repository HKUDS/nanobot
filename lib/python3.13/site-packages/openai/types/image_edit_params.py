# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Optional
from typing_extensions import Literal, Required, TypedDict

from .._types import FileTypes, SequenceNotStr
from .image_model import ImageModel

__all__ = ["ImageEditParamsBase", "ImageEditParamsNonStreaming", "ImageEditParamsStreaming"]


class ImageEditParamsBase(TypedDict, total=False):
    image: Required[Union[FileTypes, SequenceNotStr[FileTypes]]]
    """The image(s) to edit. Must be a supported image file or an array of images.

    For the GPT image models (`gpt-image-1`, `gpt-image-1-mini`, and
    `gpt-image-1.5`), each image should be a `png`, `webp`, or `jpg` file less than
    50MB. You can provide up to 16 images. `chatgpt-image-latest` follows the same
    input constraints as GPT image models.

    For `dall-e-2`, you can only provide one image, and it should be a square `png`
    file less than 4MB.
    """

    prompt: Required[str]
    """A text description of the desired image(s).

    The maximum length is 1000 characters for `dall-e-2`, and 32000 characters for
    the GPT image models.
    """

    background: Optional[Literal["transparent", "opaque", "auto"]]
    """
    Allows to set transparency for the background of the generated image(s). This
    parameter is only supported for the GPT image models. Must be one of
    `transparent`, `opaque` or `auto` (default value). When `auto` is used, the
    model will automatically determine the best background for the image.

    If `transparent`, the output format needs to support transparency, so it should
    be set to either `png` (default value) or `webp`.
    """

    input_fidelity: Optional[Literal["high", "low"]]
    """
    Control how much effort the model will exert to match the style and features,
    especially facial features, of input images. This parameter is only supported
    for `gpt-image-1` and `gpt-image-1.5` and later models, unsupported for
    `gpt-image-1-mini`. Supports `high` and `low`. Defaults to `low`.
    """

    mask: FileTypes
    """An additional image whose fully transparent areas (e.g.

    where alpha is zero) indicate where `image` should be edited. If there are
    multiple images provided, the mask will be applied on the first image. Must be a
    valid PNG file, less than 4MB, and have the same dimensions as `image`.
    """

    model: Union[str, ImageModel, None]
    """The model to use for image generation. Defaults to `gpt-image-1.5`."""

    n: Optional[int]
    """The number of images to generate. Must be between 1 and 10."""

    output_compression: Optional[int]
    """The compression level (0-100%) for the generated images.

    This parameter is only supported for the GPT image models with the `webp` or
    `jpeg` output formats, and defaults to 100.
    """

    output_format: Optional[Literal["png", "jpeg", "webp"]]
    """The format in which the generated images are returned.

    This parameter is only supported for the GPT image models. Must be one of `png`,
    `jpeg`, or `webp`. The default value is `png`.
    """

    partial_images: Optional[int]
    """The number of partial images to generate.

    This parameter is used for streaming responses that return partial images. Value
    must be between 0 and 3. When set to 0, the response will be a single image sent
    in one streaming event.

    Note that the final image may be sent before the full number of partial images
    are generated if the full image is generated more quickly.
    """

    quality: Optional[Literal["standard", "low", "medium", "high", "auto"]]
    """The quality of the image that will be generated for GPT image models.

    Defaults to `auto`.
    """

    response_format: Optional[Literal["url", "b64_json"]]
    """The format in which the generated images are returned.

    Must be one of `url` or `b64_json`. URLs are only valid for 60 minutes after the
    image has been generated. This parameter is only supported for `dall-e-2`
    (default is `url` for `dall-e-2`), as GPT image models always return
    base64-encoded images.
    """

    size: Optional[Literal["256x256", "512x512", "1024x1024", "1536x1024", "1024x1536", "auto"]]
    """The size of the generated images.

    Must be one of `1024x1024`, `1536x1024` (landscape), `1024x1536` (portrait), or
    `auto` (default value) for the GPT image models, and one of `256x256`,
    `512x512`, or `1024x1024` for `dall-e-2`.
    """

    user: str
    """
    A unique identifier representing your end-user, which can help OpenAI to monitor
    and detect abuse.
    [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#end-user-ids).
    """


class ImageEditParamsNonStreaming(ImageEditParamsBase, total=False):
    stream: Optional[Literal[False]]
    """Edit the image in streaming mode.

    Defaults to `false`. See the
    [Image generation guide](https://platform.openai.com/docs/guides/image-generation)
    for more information.
    """


class ImageEditParamsStreaming(ImageEditParamsBase):
    stream: Required[Literal[True]]
    """Edit the image in streaming mode.

    Defaults to `false`. See the
    [Image generation guide](https://platform.openai.com/docs/guides/image-generation)
    for more information.
    """


ImageEditParams = Union[ImageEditParamsNonStreaming, ImageEditParamsStreaming]
