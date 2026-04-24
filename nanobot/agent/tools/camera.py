"""Camera tool: capture photos from webcam via OpenCV."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import PurePosixPath
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.config.paths import get_media_dir

try:
    import cv2

    _HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore[assignment]
    _HAS_CV2 = False

_SAFE_FILENAME_RE = re.compile(r'^[\w.\-]+$')
_MAX_FILENAME_LEN = 128
_MAX_PROBE_INDEX = 11

_camera_lock = asyncio.Lock()


def _sanitize_filename(filename: str) -> str | None:
    """Return a safe basename or None if the filename is suspicious."""
    name = PurePosixPath(filename).name
    if not name or ".." in name or len(name) > _MAX_FILENAME_LEN:
        return None
    if not _SAFE_FILENAME_RE.match(name):
        return None
    return name


def _available_devices(max_index: int = _MAX_PROBE_INDEX) -> list[int]:
    """Probe device indices and return those that can be opened."""
    if not _HAS_CV2:
        return []
    found: list[int] = []
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx)
        try:
            if cap.isOpened():
                found.append(idx)
        finally:
            cap.release()
    return found


def _open_and_read(device_index: int, width: int, height: int) -> tuple[bool, Any, str]:
    """Synchronous helper: open camera, set resolution, read one frame.

    Returns ``(success, frame_or_None, error_message)``.
    """
    cap = cv2.VideoCapture(device_index)
    try:
        if not cap.isOpened():
            return False, None, ""

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        ret, frame = cap.read()
        if not ret or frame is None:
            return False, None, "Failed to read frame from camera."
        return True, frame, ""
    except Exception as exc:
        return False, None, str(exc)
    finally:
        cap.release()


@tool_parameters(
    tool_parameters_schema(
        device_index=IntegerSchema(
            0,
            description="Camera device index (default 0 for primary camera)",
            minimum=0,
            maximum=10,
        ),
        width=IntegerSchema(
            1280,
            description="Image width in pixels (default 1280)",
            minimum=160,
            maximum=3840,
        ),
        height=IntegerSchema(
            720,
            description="Image height in pixels (default 720)",
            minimum=120,
            maximum=2160,
        ),
        filename=StringSchema(
            "Optional custom filename for the captured photo (saved in media directory)",
        ),
    )
)
class CameraTool(Tool):
    """Capture a photo from the system webcam."""

    def __init__(self, capture_timeout: int = 15) -> None:
        self._capture_timeout = capture_timeout

    @property
    def name(self) -> str:
        return "camera_capture"

    @property
    def description(self) -> str:
        return (
            "Capture a photo from the system webcam. "
            "Returns the file path of the saved image. "
            "Requires opencv-python (or opencv-python-headless) installed."
        )

    async def execute(
        self,
        device_index: int = 0,
        width: int = 1280,
        height: int = 720,
        filename: str | None = None,
        **_kwargs: Any,
    ) -> str:
        if not _HAS_CV2:
            return (
                "Error: opencv-python is not installed. "
                "Install it with: pip install opencv-python-headless"
            )

        if width <= 0 or height <= 0:
            return "Error: width and height must be positive integers."

        if filename:
            safe = _sanitize_filename(filename)
            if safe is None:
                return "Error: Invalid filename. Use only alphanumeric characters, dots, hyphens and underscores."
            filename = safe

        if not filename:
            ts = time.strftime("%Y%m%d_%H%M%S")
            ms = int(time.monotonic() * 1000) % 10000
            filename = f"photo_{ts}_{ms:04d}.jpg"
        if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
            filename += ".jpg"

        media_dir = get_media_dir("camera")
        output_path = media_dir / filename

        async with _camera_lock:
            try:
                success, frame, err = await asyncio.wait_for(
                    asyncio.to_thread(_open_and_read, device_index, width, height),
                    timeout=self._capture_timeout,
                )
            except asyncio.TimeoutError:
                return f"Error: Camera capture timed out after {self._capture_timeout}s."

        if not success and not err:
            available = await asyncio.to_thread(_available_devices)
            if not available:
                return (
                    "Error: No camera device found. "
                    "Make sure a webcam is connected and drivers are installed."
                )
            return (
                f"Error: Cannot open camera at index {device_index}. "
                f"Available device indices: {available}"
            )

        if not success:
            return f"Error: {err}"

        try:
            write_ok = await asyncio.to_thread(cv2.imwrite, str(output_path), frame)
        except Exception as exc:
            return f"Error: Failed to save captured image: {exc}"

        if not write_ok:
            return "Error: Failed to save captured image."

        actual_h, actual_w = frame.shape[:2]
        size_kb = output_path.stat().st_size / 1024
        logger.info(
            "camera_capture: saved photo to {} ({:.1f} KB, {}x{})",
            output_path, size_kb, actual_w, actual_h,
        )
        return f"Photo captured: {output_path} ({size_kb:.1f} KB, {actual_w}x{actual_h})"
