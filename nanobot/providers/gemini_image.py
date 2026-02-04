"""Gemini image generation provider using Google's Imagen API."""

import base64
import os
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


class GeminiImageProvider:
    """
    Image generation provider using Google's Gemini/Imagen API.

    Generates images from text descriptions.
    """

    # Gemini API endpoint for image generation
    API_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "imagen-3.0-generate-002",
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model = model

    async def generate_image(
        self,
        prompt: str,
        output_path: str | Path | None = None,
        aspect_ratio: str = "1:1",
        num_images: int = 1,
    ) -> list[Path]:
        """
        Generate image(s) from a text prompt.

        Args:
            prompt: Text description of the image to generate.
            output_path: Directory to save images. If None, uses default.
            aspect_ratio: Image aspect ratio (1:1, 16:9, 9:16, 4:3, 3:4).
            num_images: Number of images to generate (1-4).

        Returns:
            List of paths to generated images.
        """
        if not self.api_key:
            logger.warning("Gemini API key not configured")
            return []

        if not prompt.strip():
            logger.warning("Empty prompt for image generation")
            return []

        # Use Imagen API for image generation
        url = f"{self.API_BASE}/models/{self.model}:predict?key={self.api_key}"

        body = {
            "instances": [
                {"prompt": prompt}
            ],
            "parameters": {
                "sampleCount": min(num_images, 4),
                "aspectRatio": aspect_ratio,
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=body,
                    timeout=120.0
                )

                if response.status_code == 404:
                    # Try alternative endpoint for Gemini 2.0
                    return await self._generate_with_gemini_2(prompt, output_path, num_images)

                response.raise_for_status()
                data = response.json()

                # Process results
                results = []
                predictions = data.get("predictions", [])

                # Determine output directory
                if output_path:
                    out_dir = Path(output_path)
                else:
                    out_dir = Path.home() / ".nanobot" / "media" / "generated"
                out_dir.mkdir(parents=True, exist_ok=True)

                import time
                timestamp = int(time.time())

                for i, pred in enumerate(predictions):
                    if "bytesBase64Encoded" in pred:
                        image_data = base64.b64decode(pred["bytesBase64Encoded"])
                        mime_type = pred.get("mimeType", "image/png")
                        ext = ".png" if "png" in mime_type else ".jpg"

                        path = out_dir / f"img_{timestamp}_{i}{ext}"
                        with open(path, "wb") as f:
                            f.write(image_data)

                        results.append(path)
                        logger.info(f"Generated image: {path}")

                return results

        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini API error ({e.response.status_code}): {e.response.text}")
            # Try fallback method
            return await self._generate_with_gemini_2(prompt, output_path, num_images)
        except Exception as e:
            logger.error(f"Gemini image generation error: {e}")
            return []

    async def _generate_with_gemini_2(
        self,
        prompt: str,
        output_path: str | Path | None = None,
        num_images: int = 1,
    ) -> list[Path]:
        """
        Generate images using Gemini 2.0 Flash with native image generation.

        This is a fallback for when Imagen API is not available.
        """
        url = f"{self.API_BASE}/models/gemini-2.0-flash-exp:generateContent?key={self.api_key}"

        body = {
            "contents": [{
                "parts": [{
                    "text": f"Generate an image: {prompt}"
                }]
            }],
            "generationConfig": {
                "responseModalities": ["image", "text"],
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=body,
                    timeout=120.0
                )

                response.raise_for_status()
                data = response.json()

                results = []

                # Determine output directory
                if output_path:
                    out_dir = Path(output_path)
                else:
                    out_dir = Path.home() / ".nanobot" / "media" / "generated"
                out_dir.mkdir(parents=True, exist_ok=True)

                import time
                timestamp = int(time.time())

                # Extract images from response
                candidates = data.get("candidates", [])
                for candidate in candidates:
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])

                    for i, part in enumerate(parts):
                        if "inlineData" in part:
                            inline_data = part["inlineData"]
                            mime_type = inline_data.get("mimeType", "image/png")
                            image_data = base64.b64decode(inline_data["data"])

                            ext = ".png" if "png" in mime_type else ".jpg"
                            path = out_dir / f"img_{timestamp}_{i}{ext}"

                            with open(path, "wb") as f:
                                f.write(image_data)

                            results.append(path)
                            logger.info(f"Generated image (Gemini 2.0): {path}")

                return results

        except Exception as e:
            logger.error(f"Gemini 2.0 image generation error: {e}")
            return []

    async def edit_image(
        self,
        image_path: str | Path,
        prompt: str,
        output_path: str | Path | None = None,
    ) -> Path | None:
        """
        Edit an existing image based on a text prompt.

        Args:
            image_path: Path to the image to edit.
            prompt: Description of the edit to make.
            output_path: Path to save edited image.

        Returns:
            Path to edited image, or None on error.
        """
        if not self.api_key:
            logger.warning("Gemini API key not configured")
            return None

        image_path = Path(image_path)
        if not image_path.exists():
            logger.error(f"Image not found: {image_path}")
            return None

        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        # Determine mime type
        ext = image_path.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")

        url = f"{self.API_BASE}/models/gemini-2.0-flash-exp:generateContent?key={self.api_key}"

        body = {
            "contents": [{
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": image_data
                        }
                    },
                    {
                        "text": f"Edit this image: {prompt}"
                    }
                ]
            }],
            "generationConfig": {
                "responseModalities": ["image", "text"],
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=body,
                    timeout=120.0
                )

                response.raise_for_status()
                data = response.json()

                # Extract edited image
                candidates = data.get("candidates", [])
                for candidate in candidates:
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])

                    for part in parts:
                        if "inlineData" in part:
                            inline_data = part["inlineData"]
                            result_mime = inline_data.get("mimeType", "image/png")
                            result_data = base64.b64decode(inline_data["data"])

                            # Determine output path
                            if output_path:
                                out_path = Path(output_path)
                            else:
                                import time
                                out_dir = Path.home() / ".nanobot" / "media" / "generated"
                                out_dir.mkdir(parents=True, exist_ok=True)
                                ext = ".png" if "png" in result_mime else ".jpg"
                                out_path = out_dir / f"edited_{int(time.time())}{ext}"

                            with open(out_path, "wb") as f:
                                f.write(result_data)

                            logger.info(f"Edited image saved: {out_path}")
                            return out_path

                return None

        except Exception as e:
            logger.error(f"Gemini image edit error: {e}")
            return None
