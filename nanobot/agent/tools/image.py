"""Image generation tool using Gemini/Imagen API."""

from typing import Any, Callable, Awaitable

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class ImageGeneratorTool(Tool):
    """
    Tool to generate images from text descriptions using Gemini/Imagen.

    Generated images can be sent to users or saved for later use.
    """

    def __init__(
        self,
        api_key: str = "",
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
    ):
        self._api_key = api_key
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._provider = None

    def _get_provider(self):
        """Lazy initialization of Gemini image provider."""
        if self._provider is None:
            from nanobot.providers.gemini_image import GeminiImageProvider
            self._provider = GeminiImageProvider(api_key=self._api_key)
        return self._provider

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current message context."""
        self._default_channel = channel
        self._default_chat_id = chat_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return (
            "Generate an image from a text description using Google Gemini/Imagen. "
            "Use this to create images, illustrations, artwork, or visualizations. "
            "The generated image will be sent to the user."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate"
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["1:1", "16:9", "9:16", "4:3", "3:4"],
                    "description": "Image aspect ratio (default: 1:1)"
                },
                "send_to_user": {
                    "type": "boolean",
                    "description": "Whether to send the image to the user (default: true)"
                },
            },
            "required": ["prompt"]
        }

    async def execute(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        send_to_user: bool = True,
        **kwargs: Any
    ) -> str:
        if not prompt.strip():
            return "Error: No prompt provided for image generation"

        provider = self._get_provider()
        if not provider.api_key:
            return "Error: Gemini API key not configured"

        try:
            # Generate image
            images = await provider.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                num_images=1,
            )

            if not images:
                return "Error: Failed to generate image"

            image_path = images[0]

            # Send to user if requested
            if send_to_user and self._send_callback:
                channel = self._default_channel
                chat_id = self._default_chat_id

                if channel and chat_id:
                    msg = OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content="",  # Image message
                        media=[str(image_path)]
                    )
                    await self._send_callback(msg)
                    return f"Image generated and sent: {image_path}"

            return f"Image generated: {image_path}"

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return f"Error generating image: {str(e)}"


class ImageEditorTool(Tool):
    """
    Tool to edit existing images based on text instructions.

    Uses Gemini's multimodal capabilities to understand and modify images.
    """

    def __init__(
        self,
        api_key: str = "",
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
    ):
        self._api_key = api_key
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._provider = None

    def _get_provider(self):
        """Lazy initialization of Gemini image provider."""
        if self._provider is None:
            from nanobot.providers.gemini_image import GeminiImageProvider
            self._provider = GeminiImageProvider(api_key=self._api_key)
        return self._provider

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current message context."""
        self._default_channel = channel
        self._default_chat_id = chat_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    @property
    def name(self) -> str:
        return "edit_image"

    @property
    def description(self) -> str:
        return (
            "Edit an existing image based on text instructions. "
            "Use this to modify, enhance, or transform images. "
            "Requires the path to an existing image file."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Path to the image file to edit"
                },
                "prompt": {
                    "type": "string",
                    "description": "Instructions for how to edit the image"
                },
                "send_to_user": {
                    "type": "boolean",
                    "description": "Whether to send the edited image to the user (default: true)"
                },
            },
            "required": ["image_path", "prompt"]
        }

    async def execute(
        self,
        image_path: str,
        prompt: str,
        send_to_user: bool = True,
        **kwargs: Any
    ) -> str:
        if not image_path.strip():
            return "Error: No image path provided"

        if not prompt.strip():
            return "Error: No edit instructions provided"

        provider = self._get_provider()
        if not provider.api_key:
            return "Error: Gemini API key not configured"

        try:
            # Edit image
            edited_path = await provider.edit_image(
                image_path=image_path,
                prompt=prompt,
            )

            if not edited_path:
                return "Error: Failed to edit image"

            # Send to user if requested
            if send_to_user and self._send_callback:
                channel = self._default_channel
                chat_id = self._default_chat_id

                if channel and chat_id:
                    msg = OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content="",
                        media=[str(edited_path)]
                    )
                    await self._send_callback(msg)
                    return f"Image edited and sent: {edited_path}"

            return f"Image edited: {edited_path}"

        except Exception as e:
            logger.error(f"Image editing failed: {e}")
            return f"Error editing image: {str(e)}"
