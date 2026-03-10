"""Image tools for analyzing and displaying images."""

import base64
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage
from nanobot.providers.providers_manager import ProvidersManager


class ImageTool(Tool):
    """
    Tool for analyzing and displaying images.

    Supports three modes:
    - vision: Analyze images using multimodal LLM models (OCR, description, visual QA)
    - display: Display images to users through WebSocket channel
    - generate: Generate images from text prompts
    """

    def __init__(
        self,
        provider: ProvidersManager,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        """Initialize the image tool with all required parameters."""
        self.provider = provider
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id

    @property
    def name(self) -> str:
        return "image"

    @property
    def description(self) -> str:
        return (
            "Analyze or display images. Supports three modes:\n"
            "- vision: Analyze and describe images using multimodal LLM models. "
            "Supports image description, text extraction (OCR), visual analysis, "
            "and answering questions about image content.\n"
            "- display: Display images to users by reading from disk and sending to frontend. "
            "Use this when you want to show an image to the user directly.\n"
            "- generate: Generate images from text prompts using Alibaba Cloud Qwen-Image API. "
            "Supports various artistic styles and text rendering in images.\n"
            "Images are encoded as base64 for processing or display."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["vision", "display", "generate"],
                    "description": (
                        "The operation mode: 'vision' for image analysis, 'display' for showing images to users, "
                        "'generate' for creating images from text prompts."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "[In vision mode] The user's request or question about the image. "
                        "Examples: 'Describe this image', 'Extract text from this image', "
                        "'What objects are in this picture?', 'Is there a cat in this photo?'\n"
                        "[In display mode] Caption to display with the image. "
                        "This text will appear above the image in the message box.\n"
                        "[In generate mode] Text prompt describing the desired image content, style, and composition. "
                        "Supports Chinese and English, max 800 characters. Example: 'A sitting orange cat with happy expression'."
                    ),
                },
                "image_path": {
                    "type": "string",
                    "description": (
                        "[In vision/display mode] Path to the image file to analyze or display. Should be an absolute path "
                        "to a local image file (e.g., '/Users/archer/Desktop/photo.png'). "
                        "Supported formats: PNG, JPG, JPEG, GIF, WEBP.\n"
                        "[In generate mode] Absolute path where the generated image will be saved."
                    ),
                },
                "size": {
                    "type": "string",
                    "description": (
                        "[Optional for generate mode] Output image resolution in format 'width*height'. "
                        "For qwen-image-2.0 series: total pixels must be between 512*512 and 2048*2048, default is 1024*1024. "
                        "Examples: '1024*1024', '1664*928', '1328*1328'."
                    ),
                },
                "negative_prompt": {
                    "type": "string",
                    "description": (
                        "[Optional for generate mode] Negative prompt describing what should NOT appear in the image. "
                        "Max 500 characters. Example: 'low resolution, low quality, deformed limbs, blurry text'."
                    ),
                },
                "n": {
                    "type": "integer",
                    "description": (
                        "[Optional for generate mode] Number of images to generate. "
                        "For qwen-image-2.0 series: 1-6 images, default is 1. "
                        "For qwen-image-max/plus series: fixed at 1."
                    ),
                },
                "prompt_extend": {
                    "type": "boolean",
                    "description": (
                        "[Optional for generate mode] Enable AI-powered prompt enhancement. "
                        "When enabled, the model will optimize and refine the prompt for better results. "
                        "Default is true. Set to false for more controlled output."
                    ),
                },
                "watermark": {
                    "type": "boolean",
                    "description": (
                        "[Optional for generate mode] Add 'Qwen-Image' watermark to bottom-right corner. "
                        "Default is false."
                    ),
                },
            },
            "required": ["mode", "image_path"],
        }

    def _encode_image(self, image_path: str) -> str:
        """
        Encode an image file to base64 string.

        Args:
            image_path: Absolute path to the image file.

        Returns:
            Base64 encoded image string.

        Raises:
            FileNotFoundError: If image file doesn't exist.
            ValueError: If file is not a valid image.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Check file extension
        valid_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        if path.suffix.lower() not in valid_extensions:
            raise ValueError(
                f"Unsupported image format: {path.suffix}. "
                f"Supported formats: {', '.join(valid_extensions)}"
            )

        # Read and encode image
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")

        return encoded

    def _get_mime_type(self, image_path: str) -> str:
        """Get MIME type based on file extension."""
        ext = Path(image_path).suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        return mime_types.get(ext, "image/png")

    def set_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Set the current message context."""
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    async def execute(
        self,
        mode: str,
        text: str = "",
        image_path: str = "",
        size: str = "1024*1024",
        negative_prompt: str = "",
        n: int = 1,
        prompt_extend: bool = True,
        watermark: bool = False,
        **kwargs: Any,
    ) -> str:
        """
        Execute image tool based on mode.

        Args:
            mode: Operation mode - 'vision' for analysis, 'display' for showing images, 'generate' for creating images.
            text: [Vision mode] User's request/question about the image. [Display mode] Caption to display. [Generate mode] Image generation prompt.
            image_path: Path to the image file (for vision/display) or save path (for generate).
            size: [Generate mode] Output image resolution.
            negative_prompt: [Generate mode] Negative prompt for undesired content.
            n: [Generate mode] Number of images to generate.
            prompt_extend: [Generate mode] Enable AI prompt enhancement.
            watermark: [Generate mode] Add watermark.

        Returns:
            Analysis result (vision mode), status message (display mode), or generation result (generate mode).
        """
        if mode == "vision":
            return await self._execute_vision(text=text, image_path=image_path, **kwargs)
        elif mode == "display":
            return await self._execute_display(text=text, image_path=image_path, **kwargs)
        elif mode == "generate":
            return await self._execute_generate(
                text=text,
                image_path=image_path,
                size=size,
                negative_prompt=negative_prompt,
                n=n,
                prompt_extend=prompt_extend,
                watermark=watermark,
                **kwargs,
            )
        else:
            return f"Error: Invalid mode '{mode}'. Must be 'vision', 'display', or 'generate'."

    async def _execute_vision(self, text: str, image_path: str, **kwargs: Any) -> str:
        """
        Execute image vision analysis.

        Args:
            text: User's request/question about the image.
            images: List of image file paths.

        Returns:
            Analysis result from the vision model.
        """
        if not image_path:
            return "Error: No image provided. Please provide at least one image path."

        content: list[dict[str, Any]] = [{"type": "text", "text": text}]

        # Process image
        try:
            encoded_image = self._encode_image(image_path)
            mime_type = self._get_mime_type(image_path)

            # Add image to content in OpenAI format
            # Reference: https://platform.moonshot.cn/docs/guide/use-kimi-vision-model
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
                }
            )
        except FileNotFoundError as e:
            return f"Error: {str(e)}"
        except ValueError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"Error encoding image '{image_path}': {str(e)}"

        # Build messages for chat completion
        messages = [
            {"role": "system", "content": "Your are a multimodal model"},
            {"role": "user", "content": content},
        ]
        try:
            response = await self.provider.chat_with_retry(messages=messages, mode="multimodal")
            if response.content:
                return response.content
            return "Error: No response content from vision model."
        except Exception as e:
            return f"Error calling vision model: {str(e)}"

    async def _execute_display(self, text: str, image_path: str, **kwargs: Any) -> str:
        """
        Execute image display by sending image data to frontend.

        Args:
            image_path: Path to the image file to display.
            caption: Optional caption text to display above the image.

        Returns:
            Status message indicating success or error.
        """

        if not self._send_callback:
            return "Error: Message sending not configured"

        try:
            # Encode image to base64
            encoded_image = self._encode_image(image_path)
            mime_type = self._get_mime_type(image_path)

            # Prepare media data for the message
            media_data = {
                "data": f"data:{mime_type};base64,{encoded_image}",
                "file_name": Path(image_path).name,
            }

            # Create outbound message with image as media
            msg = OutboundMessage(
                channel=self._default_channel,
                chat_id=self._default_chat_id,
                content=text or "Image display",
                media=[media_data],
                metadata={
                    "msg_type": "image",  # Indicate this is an image message
                    "file_type": mime_type,
                },
            )

            # Send the message through the callback
            await self._send_callback(msg)

            return f"Image displayed successfully: {Path(image_path).name}"

        except FileNotFoundError as e:
            return f"Error: {str(e)}"
        except ValueError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"Error: {str(e)}"

    async def _execute_generate(
        self,
        text: str,
        image_path: str,
        size: str = "1024*1024",
        negative_prompt: str = "",
        n: int = 1,
        prompt_extend: bool = True,
        watermark: bool = False,
        **kwargs: Any,
    ) -> str:
        """
        Execute image generation using Alibaba Cloud Qwen-Image API.

        Args:
            text: Text prompt describing the desired image content, style, and composition.
            image_path: File name where the generated image will be saved.
            size: Output image resolution in format 'width*height'.
            negative_prompt: Negative prompt for undesired content.
            n: Number of images to generate (1-6 for qwen-image-2.0 series, fixed 1 for max/plus).
            prompt_extend: Enable AI-powered prompt enhancement.
            watermark: Add 'Qwen-Image' watermark.

        Returns:
            Status message with generation result or error details.
        """
        import json
        import os

        import httpx

        if not text:
            return "Error: Text prompt is required for image generation."

        if not image_path:
            return "Error: Image save path is required."

        # Get API key from environment
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            return (
                "Error: DASHSCOPE_API_KEY not found. Please set it in environment variables at ~/.nanobot/workspace/.env. "
                "Get your API key from https://dashscope.console.aliyun.com/"
            )

        # Determine endpoint based on region
        # You can set DASHSCOPE_REGION to 'beijing' or 'singapore', default is beijing
        region = os.getenv("DASHSCOPE_REGION", "beijing").lower()
        if region == "beijing":
            endpoint = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        elif region == "singapore":
            endpoint = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        else:
            return f"Error: Invalid region '{region}'. Must be 'beijing' or 'singapore'."

        # Build request payload
        payload = {
            "model": os.getenv("DASHSCOPE_IMAGE_GEN_MODEL", "qwen-imag-max"),
            "input": {"messages": [{"role": "user", "content": [{"text": text}]}]},
            "parameters": {
                "size": size,
                "prompt_extend": prompt_extend,
                "watermark": watermark,
            },
        }

        # Add optional parameters
        if negative_prompt:
            payload["parameters"]["negative_prompt"] = negative_prompt

        # Only add n parameter for qwen-image-2.0 series (supports 1-6 images)
        if n > 1:
            payload["parameters"]["n"] = min(n, 6)  # Cap at 6 for 2.0 series

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            # Parse response
            output = result.get("output", {})
            choices = output.get("choices", [])

            if not choices:
                return (
                    f"Error: No image generated. Response: {json.dumps(result, ensure_ascii=False)}"
                )

            # Get image URLs
            image_urls = []
            for choice in choices:
                message = choice.get("message", {})
                content = message.get("content", [])
                for item in content:
                    if "image" in item:
                        image_urls.append(item["image"])

            if not image_urls:
                return f"Error: No image URL in response. Response: {json.dumps(result, ensure_ascii=False)}"

            # Download and save the first image (or all images if n > 1)
            saved_paths = []
            for idx, img_url in enumerate(image_urls):
                async with httpx.AsyncClient(timeout=30.0) as download_client:
                    img_response = await download_client.get(img_url)
                    img_response.raise_for_status()

                    # Determine save path
                    if len(image_urls) > 1:
                        # Multiple images: add index to filename
                        path_obj = Path("~/.nanobot/media") / image_path
                        save_path = path_obj.parent / f"{path_obj.stem}_{idx + 1}{path_obj.suffix}"
                    else:
                        save_path = Path("~/.nanobot/media") / image_path

                    # Save image
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(img_response.content)

                    saved_paths.append(str(save_path))

            # Get usage info
            usage = result.get("usage", {})
            width = usage.get("width", "unknown")
            height = usage.get("height", "unknown")

            if len(saved_paths) == 1:
                logger.info(f"Image generated successfully: {saved_paths[0]} ({width}x{height})")
                return await self._execute_display(
                    f"Generated image:\n{os.path.basename(saved_paths[0])}", saved_paths[0]
                )
            return (
                f"Generated {len(saved_paths)} images successfully:\n"
                + "\n".join(f"- {path}" for path in saved_paths)
                + f"\nResolution: {width}x{height}"
            )

        except httpx.HTTPStatusError as e:
            error_detail = e.response.text if e.response else str(e)
            try:
                error_json = e.response.json()
                error_msg = error_json.get("message", error_json.get("error", error_detail))
            except Exception:
                error_msg = error_detail
            return f"Error: HTTP {e.response.status_code} - {error_msg}"
        except httpx.TimeoutException:
            return (
                "Error: Request timed out. The generation may take 10-30 seconds, please try again."
            )
        except httpx.RequestError as e:
            return f"Error: Network request failed - {str(e)}"
        except Exception as e:
            return f"Error: Generation failed - {str(e)}"
