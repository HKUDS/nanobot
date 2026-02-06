"""Video processing utilities for frame and audio extraction."""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger


class VideoProcessor:
    """
    Extract frames and audio from videos for analysis.

    Uses ffmpeg for processing (must be installed on the system).
    """

    def __init__(self, workspace: Path, max_frames: int = 5):
        """
        Initialize the video processor.

        Args:
            workspace: Workspace directory for storing extracted content.
            max_frames: Maximum number of frames to extract.
        """
        self.workspace = workspace
        self.media_dir = workspace.parent / "media"
        self.frames_dir = self.media_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.max_frames = max_frames

    async def extract_key_frames(
        self,
        video_path: str | Path,
        max_frames: int | None = None,
    ) -> list[str]:
        """
        Extract key frames from a video file.

        Args:
            video_path: Path to video file.
            max_frames: Maximum number of frames to extract (uses self.max_frames if None).

        Returns:
            List of paths to extracted frame images.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            logger.error(f"Video not found: {video_path}")
            return []

        max_frames = max_frames or self.max_frames
        output_prefix = self.frames_dir / f"{video_path.stem}_frame"

        # Extract frames at intervals (1 frame every 5 seconds for typical videos)
        # Using fps filter: 1/5 = 1 frame every 5 seconds
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", f"fps=1/5,scale=640:-1",  # 1 frame every 5 sec, max width 640px
            "-vframes", str(max_frames),
            "-y",  # Overwrite output files
            f"{output_prefix}_%d.jpg"
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"ffmpeg error: {error_msg}")
                return []

            # Find extracted frames
            frames = []
            for i in range(1, max_frames + 1):
                frame_path = Path(f"{output_prefix}_{i}.jpg")
                if frame_path.exists():
                    frames.append(str(frame_path))
                else:
                    break

            logger.info(f"Extracted {len(frames)} frames from {video_path.name}")
            return frames

        except FileNotFoundError:
            logger.error("ffmpeg not found. Install with: apt install ffmpeg or brew install ffmpeg")
            return []
        except Exception as e:
            logger.error(f"Frame extraction error: {e}")
            return []

    async def extract_audio(self, video_path: str | Path) -> Path | None:
        """
        Extract audio track from video for transcription.

        Args:
            video_path: Path to video file.

        Returns:
            Path to extracted audio file, or None if no audio or extraction failed.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            logger.error(f"Video not found: {video_path}")
            return None

        output_path = self.media_dir / f"{video_path.stem}_audio.mp3"

        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",  # No video
            "-acodec", "libmp3lame",  # MP3 codec
            "-y",  # Overwrite
            str(output_path)
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0 and output_path.exists():
                logger.info(f"Extracted audio to {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
                return output_path
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.warning(f"Audio extraction failed: {error_msg}")
                return None

        except FileNotFoundError:
            logger.error("ffmpeg not found. Install with: apt install ffmpeg or brew install ffmpeg")
            return None
        except Exception as e:
            logger.error(f"Audio extraction error: {e}")
            return None

    async def get_video_info(self, video_path: str | Path) -> dict[str, Any] | None:
        """
        Get metadata about a video file.

        Args:
            video_path: Path to video file.

        Returns:
            Dictionary with video metadata (duration, width, height, etc.)
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return None

        # Use ffprobe to get video info
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video_path)
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                info = json.loads(stdout.decode())
                return self._parse_video_info(info)
            return None

        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to get video info: {e}")
            return None

    def _parse_video_info(self, info: dict) -> dict[str, Any]:
        """Parse ffprobe output to extract relevant video metadata."""
        result = {}

        # Get video stream info
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                result.update({
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "fps": eval(stream.get("r_frame_rate", "0/1")),
                    "codec": stream.get("codec_name"),
                })
                break  # Use first video stream

        # Get duration from format
        format_info = info.get("format", {})
        duration = float(format_info.get("duration", 0))
        if duration > 0:
            result["duration_seconds"] = duration

        # File size
        size = int(format_info.get("size", 0))
        if size > 0:
            result["size_bytes"] = size

        return result

    def cleanup_frames(self, video_path: str | Path) -> int:
        """
        Clean up extracted frames for a specific video.

        Args:
            video_path: Original video path (to identify frames).

        Returns:
            Number of frames deleted.
        """
        video_path = Path(video_path)
        pattern = f"{video_path.stem}_frame_"
        deleted = 0

        for frame_path in self.frames_dir.glob(f"{pattern}*.jpg"):
            try:
                frame_path.unlink()
                deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {frame_path}: {e}")

        if deleted > 0:
            logger.debug(f"Cleaned up {deleted} frames for {video_path.name}")

        return deleted

    @staticmethod
    def is_ffmpeg_available() -> bool:
        """Check if ffmpeg is available on the system."""
        try:
            import shutil
            return shutil.which("ffmpeg") is not None
        except Exception:
            return False
