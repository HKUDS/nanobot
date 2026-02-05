# Inference code generated from the JSON schema spec in @huggingface/tasks.
#
# See:
#   - script: https://github.com/huggingface/huggingface.js/blob/main/packages/tasks/scripts/inference-codegen.ts
#   - specs:  https://github.com/huggingface/huggingface.js/tree/main/packages/tasks/src/tasks.
from typing import Any, Optional

from .base import BaseInferenceType, dataclass_with_extra


@dataclass_with_extra
class ImageTextToImageTargetSize(BaseInferenceType):
    """The size in pixels of the output image. This parameter is only supported by some
    providers and for specific models. It will be ignored when unsupported.
    """

    height: int
    width: int


@dataclass_with_extra
class ImageTextToImageParameters(BaseInferenceType):
    """Additional inference parameters for Image Text To Image"""

    guidance_scale: Optional[float] = None
    """For diffusion models. A higher guidance scale value encourages the model to generate
    images closely linked to the text prompt at the expense of lower image quality.
    """
    negative_prompt: Optional[str] = None
    """One prompt to guide what NOT to include in image generation."""
    num_inference_steps: Optional[int] = None
    """For diffusion models. The number of denoising steps. More denoising steps usually lead to
    a higher quality image at the expense of slower inference.
    """
    prompt: Optional[str] = None
    """The text prompt to guide the image generation. Either this or inputs (image) must be
    provided.
    """
    seed: Optional[int] = None
    """Seed for the random number generator."""
    target_size: Optional[ImageTextToImageTargetSize] = None
    """The size in pixels of the output image. This parameter is only supported by some
    providers and for specific models. It will be ignored when unsupported.
    """


@dataclass_with_extra
class ImageTextToImageInput(BaseInferenceType):
    """Inputs for Image Text To Image inference. Either inputs (image) or prompt (in parameters)
    must be provided, or both.
    """

    inputs: Optional[str] = None
    """The input image data as a base64-encoded string. If no `parameters` are provided, you can
    also provide the image data as a raw bytes payload. Either this or prompt must be
    provided.
    """
    parameters: Optional[ImageTextToImageParameters] = None
    """Additional inference parameters for Image Text To Image"""


@dataclass_with_extra
class ImageTextToImageOutput(BaseInferenceType):
    """Outputs of inference for the Image Text To Image task"""

    image: Any
    """The generated image returned as raw bytes in the payload."""
