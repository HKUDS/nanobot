"""Voice transcription provider using SiliconFlow's FunAudioLLM/SenseVoiceSmall."""

import os
from pathlib import Path

import httpx
from loguru import logger


class SiliconFlowTranscriptionProvider:
    """
    Voice transcription provider using SiliconFlow's FunAudioLLM/SenseVoiceSmall.
    
    Fast and accurate, supports multiple languages including Chinese.
    """
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("SILICONFLOW_API_KEY")
        self.api_url = "https://api.siliconflow.cn/v1/audio/transcriptions"
        self.model = "FunAudioLLM/SenseVoiceSmall"
    
    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using SiliconFlow.
        
        Args:
            file_path: Path to the audio file.
            
        Returns:
            Transcribed text.
        """
        if not self.api_key:
            logger.warning("SiliconFlow API key not configured for transcription")
            return ""
        
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""
        
        # Determine MIME type from extension
        ext = path.suffix.lstrip(".").lower()
        mime_map = {
            "ogg": "audio/ogg",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
            "flac": "audio/flac",
        }
        mime_type = mime_map.get(ext, "audio/ogg")
        
        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f, mime_type),
                        "model": (None, self.model),
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }
                    
                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        timeout=60.0
                    )
                    
                    response.raise_for_status()
                    data = response.json()
                    text = data.get("text", "").strip()
                    if text:
                        logger.info("Transcribed audio: {}...", text[:50])
                    return text
                    
        except httpx.HTTPStatusError as e:
            logger.error("SiliconFlow transcription HTTP error: {} - {}", e.response.status_code, e.response.text)
            return ""
        except Exception as e:
            logger.error("SiliconFlow transcription error: {}", e)
            return ""