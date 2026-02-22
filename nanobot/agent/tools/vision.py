"""Vision tool for image analysis using VLM models."""

import base64
import os
from pathlib import Path

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool


class VisionTool(Tool):
    """
    Analyze images using VLM (Vision Language Model) via any OpenAI-compatible API.
    
    This tool allows the agent to understand images while keeping the main
    LLM as a text-only model. Supports OpenAI GPT-4V, SiliconFlow Qwen-VL,
    Google Gemini Vision, and any OpenAI-compatible VLM endpoint.
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
    ):
        """
        Initialize VisionTool.
        
        Args:
            api_key: API key for the VLM provider (optional, falls back to env vars)
            api_base: API base URL (optional, defaults to OpenAI)
            model: Vision model name (optional, defaults to gpt-4o)
        """
        # Priority: passed parameter > environment variable
        self.api_key = api_key or os.environ.get("VISION_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.api_base = api_base or os.environ.get("VISION_API_BASE") or "https://api.openai.com/v1"
        self.vision_model = model or os.environ.get("VISION_MODEL") or "gpt-4o"
    
    @property
    def name(self) -> str:
        return "vision_analyze"
    
    @property
    def description(self) -> str:
        return (
            "Analyze an image and return a detailed text description. "
            "Use this tool when you need to understand what's in a picture, "
            "including text, objects, people, scenes, charts, etc. "
            "Returns: A detailed description of the image content."
        )
    
    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Path to the image file to analyze (absolute path)"
                },
                "question": {
                    "type": "string",
                    "description": "Specific question about the image (optional, for focused analysis)"
                }
            },
            "required": ["image_path"]
        }
    
    async def execute(self, image_path: str, question: str | None = None) -> str:
        """
        Analyze an image using the configured VLM API.
        
        Args:
            image_path: Path to the image file.
            question: Optional specific question about the image.
            
        Returns:
            Text description of the image.
        """
        if not self.api_key:
            return "Error: API key not configured for vision analysis"
        
        path = Path(image_path)
        if not path.exists():
            return f"Error: Image file not found: {image_path}"
        
        # Read and encode image
        try:
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            return f"Error reading image: {e}"
        
        # Determine MIME type
        ext = path.suffix.lstrip(".").lower()
        mime_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
            "bmp": "image/bmp",
        }
        mime_type = mime_map.get(ext, "image/jpeg")
        
        # Build the prompt
        if question:
            prompt = question
        else:
            prompt = "请详细描述这张图片的内容，包括所有可识别的物体、人物、文字、场景、颜色等信息。"
        
        # Build messages for VLM
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_data}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.vision_model,
                        "messages": messages,
                        "max_tokens": 1024,
                        "temperature": 0.7
                    },
                    timeout=60.0
                )
                
                response.raise_for_status()
                data = response.json()
                
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"]["content"]
                    logger.info("Vision analysis completed for: {}", path.name)
                    return content
                else:
                    return "Error: No response from vision model"
                    
        except httpx.HTTPStatusError as e:
            logger.error("Vision API HTTP error: {} - {}", e.response.status_code, e.response.text)
            return f"Error: Vision API failed with status {e.response.status_code}"
        except Exception as e:
            logger.error("Vision analysis error: {}", e)
            return f"Error analyzing image: {e}"