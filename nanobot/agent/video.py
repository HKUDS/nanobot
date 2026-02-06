"""Video processing utilities for frame and audio extraction."""

import asyncio
import atexit
import json
from fractions import Fraction
from pathlib import Path
from typing import Any
from weakref import WeakSet

from loguru import logger

# Maximum file size for video processing (100MB)
MAX_VIDEO_SIZE = 100 * 1024 * 1024


class ProcessRegistry:
    """
    Registry for tracking spawned subprocess processes.

    Ensures proper cleanup on exit and prevents zombie processes.
    Uses WeakSet so processes are automatically removed when they complete.
    """

    def __init__(self) -> None:
        self._processes: WeakSet[asyncio.subprocess.Process] = WeakSet()
        self._shutdown = False
        self._register_cleanup_handlers()

    def _register_cleanup_handlers(self) -> None:
        """
        Register cleanup handlers for graceful shutdown.

        Signal handlers are NOT registered to avoid async-signal-unsafe operations.
        We rely solely on atexit for cleanup, which will be called on:
        - Normal exit
        - SIGTERM/SIGINT (unless custom handlers override default behavior)
        - Exceptions that cause program termination
        """
        atexit.register(self._cleanup_all)

    def register(self, process: asyncio.subprocess.Process) -> None:
        """Register a process for tracking."""
        self._processes.add(process)

    def _cleanup_all(self) -> None:
        """Clean up all tracked processes (called on exit)."""
        if self._shutdown:
            return
        self._shutdown = True

        remaining = len(self._processes)
        if remaining > 0:
            logger.debug(f"ProcessRegistry: Cleaning up {remaining} processes on exit")

        for proc in list(self._processes):
            try:
                if proc.returncode is None:
                    proc.kill()
                    # Try to wait briefly (non-blocking in atexit context)
                    try:
                        proc.wait(timeout=0.1)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Error cleaning up process: {e}")


# Global process registry (initialized at module import time for thread safety)
_global_registry: ProcessRegistry = ProcessRegistry()


def get_process_registry() -> ProcessRegistry:
    """Get the global process registry."""
    return _global_registry


class VideoProcessor:
    """
    Extract frames and audio from videos for analysis.

    Uses ffmpeg for processing (must be installed on the system).

    Process Management:
    - All spawned processes are tracked in a global registry
    - Processes are automatically cleaned up on exit via atexit/signals
    - Timeouts are configurable to prevent hanging
    """

    # Default timeouts (seconds)
    DEFAULT_FRAME_TIMEOUT = 30.0
    DEFAULT_AUDIO_TIMEOUT = 30.0
    DEFAULT_INFO_TIMEOUT = 10.0
    # Default frame extraction parameters
    DEFAULT_FRAME_INTERVAL_SECONDS = 5.0  # Extract 1 frame every 5 seconds
    DEFAULT_MAX_FRAME_WIDTH = 640  # Scale frames to max width (height auto)
    # Time to wait for process to terminate after SIGKILL
    # - Most processes terminate within 100ms after kill()
    # - 5 seconds handles edge cases (stuck in uninterruptible syscall, NFS, etc.)
    # - This is a generous timeout to avoid hanging shutdown
    DEFAULT_PROCESS_WAIT_TIMEOUT = 5.0

    def __init__(
        self,
        workspace: Path,
        max_frames: int = 5,
        frame_interval_seconds: float = 5.0,
        max_frame_width: int = 640,
        frame_timeout: float | None = None,
        audio_timeout: float | None = None,
        info_timeout: float | None = None,
    ):
        """
        Initialize the video processor.

        Args:
            workspace: Workspace directory for storing extracted content.
            max_frames: Maximum number of frames to extract.
            frame_interval_seconds: Seconds between frame extractions (default: 5.0).
            max_frame_width: Maximum width for extracted frames in pixels (default: 640).
            frame_timeout: Timeout for frame extraction (seconds).
            audio_timeout: Timeout for audio extraction (seconds).
            info_timeout: Timeout for video info query (seconds).
        """
        self.workspace = workspace.resolve()
        self.media_dir = self.workspace.parent / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir = self.media_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.max_frames = max_frames
        self.frame_interval_seconds = frame_interval_seconds
        self.max_frame_width = max_frame_width

        # Configurable timeouts
        self.frame_timeout = frame_timeout or self.DEFAULT_FRAME_TIMEOUT
        self.audio_timeout = audio_timeout or self.DEFAULT_AUDIO_TIMEOUT
        self.info_timeout = info_timeout or self.DEFAULT_INFO_TIMEOUT

        # Get process registry
        self._registry = get_process_registry()

    def _validate_video_path(self, video_path: Path) -> tuple[bool, str | None]:
        """
        Validate that the video path is within allowed directories.

        Args:
            video_path: Path to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # Resolve to absolute path
        try:
            resolved = video_path.resolve()
        except Exception as e:
            return False, f"Invalid path: {e}"

        # Must be within media directory or workspace
        allowed_dirs = [self.media_dir.resolve(), self.workspace.resolve()]
        is_allowed = any(
            resolved.is_relative_to(allowed_dir)
            for allowed_dir in allowed_dirs
        )

        if not is_allowed:
            return False, f"Path outside allowed directories: {resolved}"

        # Check file size
        try:
            file_size = resolved.stat().st_size
            if file_size > MAX_VIDEO_SIZE:
                return False, f"Video too large ({file_size / 1024 / 1024:.1f}MB > {MAX_VIDEO_SIZE / 1024 / 1024:.0f}MB)"
        except Exception as e:
            return False, f"Cannot access file: {e}"

        return True, None

    def _validate_path_before_use(self, video_path: Path) -> Path:
        """
        Validate a video path immediately before use (TOCTOU protection).

        This should be called right before passing the path to ffmpeg/fprobe
        to prevent time-of-check-time-of-use race conditions.

        Args:
            video_path: Path to validate.

        Returns:
            The resolved path (safe to use with subprocess).

        Raises:
            ValueError: If path is invalid or outside allowed directories.
        """
        try:
            resolved = video_path.resolve()
        except Exception as e:
            raise ValueError(f"Invalid path: {e}")

        allowed_dirs = [self.media_dir.resolve(), self.workspace.resolve()]
        is_allowed = any(
            resolved.is_relative_to(allowed_dir)
            for allowed_dir in allowed_dirs
        )

        if not is_allowed:
            raise ValueError(f"Path outside allowed directories: {resolved}")

        # Return resolved path to prevent symlink swap attacks
        return resolved

    async def _run_subprocess(
        self,
        cmd: list[str],
        timeout: float,
    ) -> tuple[bytes, bytes, int]:
        """
        Run a subprocess with proper cleanup and error handling.

        Args:
            cmd: Command and arguments to execute.
            timeout: Timeout in seconds.

        Returns:
            Tuple of (stdout, stderr, returncode).

        Raises:
            asyncio.TimeoutError: If process exceeds timeout.
            FileNotFoundError: If command not found.
        """
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Register process for cleanup on exit
        self._registry.register(process)

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            return stdout, stderr, process.returncode
        except asyncio.TimeoutError:
            # Timeout: kill process and wait for cleanup
            logger.error(f"Process timeout, killing: {' '.join(cmd[:2])}")
            process.kill()
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=self.DEFAULT_PROCESS_WAIT_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning("Process did not terminate after kill")
            raise
        except Exception:
            # Other exceptions: try to clean up process
            if process.returncode is None:
                process.kill()
                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=self.DEFAULT_PROCESS_WAIT_TIMEOUT
                    )
                except Exception:
                    pass
            raise

    async def extract_key_frames(
        self,
        video_path: str | Path,
        max_frames: int | None = None,
    ) -> list[str]:
        """
        Extract key frames from a video file.

        Args:
            video_path: Path to video file (must be within media directory).
            max_frames: Maximum number of frames to extract (uses self.max_frames if None).

        Returns:
            List of paths to extracted frame images.
        """
        video_path = Path(video_path)

        # Validate path is within allowed directories
        is_valid, error = self._validate_video_path(video_path)
        if not is_valid:
            logger.error(f"Video path validation failed: {error}")
            return []

        if not video_path.exists():
            logger.error(f"Video not found: {video_path}")
            return []

        max_frames = max_frames or self.max_frames
        # Add UUID to prevent filename collisions
        import uuid
        output_prefix = self.frames_dir / f"{video_path.stem}_{uuid.uuid4().hex[:8]}_frame"

        # Build fps filter from frame_interval_seconds
        # fps=1/X means 1 frame every X seconds
        fps_filter = f"fps=1/{self.frame_interval_seconds}"
        # Scale to max width, maintain aspect ratio (-1 for height)
        scale_filter = f"scale={self.max_frame_width}:-1"

        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", f"{fps_filter},{scale_filter}",
            "-vframes", str(max_frames),
            "-y",  # Overwrite output files
            f"{output_prefix}_%d.jpg"
        ]

        try:
            # Re-validate path right before subprocess call (TOCTOU protection)
            # Use resolved path to prevent symlink swap attacks
            validated_path = self._validate_path_before_use(video_path)
            cmd[1] = str(validated_path)  # Replace -i argument with resolved path
            stdout, stderr, returncode = await self._run_subprocess(cmd, self.frame_timeout)

            if returncode != 0:
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

        except asyncio.TimeoutError:
            logger.error(f"ffmpeg timeout ({self.frame_timeout}s) processing {video_path.name}")
            # Cleanup frames that match this UUID
            self._cleanup_frame_batch(output_prefix)
            return []
        except FileNotFoundError:
            logger.error("ffmpeg not found. Install with: apt install ffmpeg or brew install ffmpeg")
            return []
        except Exception as e:
            logger.error(f"Frame extraction error: {e}")
            # Cleanup frames that match this UUID
            self._cleanup_frame_batch(output_prefix)
            return []

    def _cleanup_frame_batch(self, output_prefix: Path) -> None:
        """Clean up a batch of frames matching the given prefix."""
        for frame_path in self.frames_dir.glob(f"{output_prefix.name}_*.jpg"):
            try:
                frame_path.unlink()
            except Exception:
                pass

    async def extract_audio(self, video_path: str | Path) -> Path | None:
        """
        Extract audio track from video for transcription.

        Args:
            video_path: Path to video file (must be within media directory).

        Returns:
            Path to extracted audio file, or None if no audio or extraction failed.
        """
        video_path = Path(video_path)

        # Validate path is within allowed directories
        is_valid, error = self._validate_video_path(video_path)
        if not is_valid:
            logger.error(f"Video path validation failed: {error}")
            return None

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
            # Re-validate path right before subprocess call (TOCTOU protection)
            # Use resolved path to prevent symlink swap attacks
            validated_path = self._validate_path_before_use(video_path)
            cmd[1] = str(validated_path)  # Replace -i argument with resolved path
            stdout, stderr, returncode = await self._run_subprocess(cmd, self.audio_timeout)

            if returncode == 0 and output_path.exists():
                logger.info(f"Extracted audio to {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
                return output_path
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.warning(f"Audio extraction failed: {error_msg}")
                return None

        except asyncio.TimeoutError:
            logger.error(f"ffmpeg timeout ({self.audio_timeout}s) extracting audio from {video_path.name}")
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
            video_path: Path to video file (must be within media directory).

        Returns:
            Dictionary with video metadata (duration, width, height, etc.)
        """
        video_path = Path(video_path)

        # Validate path is within allowed directories
        is_valid, error = self._validate_video_path(video_path)
        if not is_valid:
            logger.error(f"Video path validation failed: {error}")
            return None

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
            # Re-validate path right before subprocess call (TOCTOU protection)
            # Use resolved path to prevent symlink swap attacks
            validated_path = self._validate_path_before_use(video_path)
            cmd[-1] = str(validated_path)  # Replace last argument with resolved path
            stdout, stderr, returncode = await self._run_subprocess(cmd, self.info_timeout)

            if returncode == 0:
                info = json.loads(stdout.decode())
                return self._parse_video_info(info)
            return None

        except asyncio.TimeoutError:
            logger.error(f"ffprobe timeout ({self.info_timeout}s) getting info for {video_path.name}")
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
                # Parse frame rate safely (format: "numerator/denominator")
                frame_rate_str = stream.get("r_frame_rate", "0/1")
                try:
                    fps = float(Fraction(frame_rate_str))
                except (ValueError, ZeroDivisionError):
                    fps = 0.0

                result.update({
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "fps": fps,
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
        Clean up all frames for a specific video (including all UUID variants).

        Note: Since UUIDs are now used, this cleans up ALL frames matching
        the video stem, regardless of UUID. This is safe since UUIDs prevent
        collisions between different video processing runs.

        Args:
            video_path: Original video path (to identify frames).

        Returns:
            Number of frames deleted.
        """
        video_path = Path(video_path)
        # Match: video_stem_UUID_frame_*.jpg
        pattern = f"{video_path.stem}_*_frame_*.jpg"
        deleted = 0

        for frame_path in self.frames_dir.glob(pattern):
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
        """
        Check if ffmpeg is available on the system.

        Returns:
            True if ffmpeg is found in PATH, False otherwise.
        """
        try:
            import shutil
            return shutil.which("ffmpeg") is not None
        except Exception:
            return False
