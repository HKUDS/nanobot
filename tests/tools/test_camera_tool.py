"""Tests for CameraTool.

All tests mock cv2 so they run without a physical camera or opencv installed.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nanobot.agent.tools.camera import (
    CameraTool,
    _available_devices,
    _sanitize_filename,
)


def _fake_frame(w: int = 1280, h: int = 720) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


class TestSanitizeFilename:

    def test_simple_name(self):
        assert _sanitize_filename("photo.jpg") == "photo.jpg"

    def test_strips_directory(self):
        assert _sanitize_filename("subdir/photo.jpg") == "photo.jpg"

    def test_strips_parent_traversal(self):
        assert _sanitize_filename("../../etc/passwd") == "passwd"

    def test_rejects_double_dot_only(self):
        assert _sanitize_filename("..") is None

    def test_rejects_empty(self):
        assert _sanitize_filename("") is None

    def test_rejects_special_chars(self):
        assert _sanitize_filename("file;rm.txt") is None

    def test_allows_hyphens_underscores(self):
        assert _sanitize_filename("my-photo_v2.png") == "my-photo_v2.png"


class TestCameraToolNoCv2:

    @pytest.mark.asyncio
    async def test_returns_error_when_cv2_missing(self):
        with patch("nanobot.agent.tools.camera._HAS_CV2", False):
            tool = CameraTool()
            result = await tool.execute()
            assert "Error" in result
            assert "opencv-python is not installed" in result


class TestCameraToolNoDevice:

    @pytest.mark.asyncio
    async def test_returns_error_when_no_camera_found(self):
        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(False, None, "")), \
             patch("nanobot.agent.tools.camera._available_devices", return_value=[]), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=Path("/tmp")):
            tool = CameraTool()
            result = await tool.execute()
            assert "Error" in result
            assert "No camera device found" in result

    @pytest.mark.asyncio
    async def test_returns_error_with_available_indices_on_wrong_index(self):
        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(False, None, "")), \
             patch("nanobot.agent.tools.camera._available_devices", return_value=[0, 2]), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=Path("/tmp")):
            tool = CameraTool()
            result = await tool.execute(device_index=5)
            assert "Error" in result
            assert "Cannot open camera at index 5" in result
            assert "[0, 2]" in result


class TestCameraToolCapture:

    @pytest.mark.asyncio
    async def test_successful_capture_default_params(self, tmp_path):
        frame = _fake_frame()

        def fake_imwrite(path, f):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"\xff\xd8\xff\xe0fake_jpg")
            return True

        mock_cv2 = MagicMock()
        mock_cv2.imwrite.side_effect = fake_imwrite

        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(True, frame, "")), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=tmp_path):
            tool = CameraTool()
            result = await tool.execute()

            assert "Photo captured" in result
            assert ".jpg" in result
            assert "KB" in result
            assert "1280x720" in result

    @pytest.mark.asyncio
    async def test_successful_capture_custom_filename(self, tmp_path):
        frame = _fake_frame()

        def fake_imwrite(path, f):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"\xff\xd8\xff\xe0fake_jpg")
            return True

        mock_cv2 = MagicMock()
        mock_cv2.imwrite.side_effect = fake_imwrite

        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(True, frame, "")), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=tmp_path):
            tool = CameraTool()
            result = await tool.execute(filename="test_photo.png")

            assert "Photo captured" in result
            assert "test_photo.png" in result

    @pytest.mark.asyncio
    async def test_filename_auto_append_extension(self, tmp_path):
        frame = _fake_frame()
        captured_path: list[str] = []

        def fake_imwrite(path, f):
            captured_path.append(str(path))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"\xff\xd8\xff\xe0fake_jpg")
            return True

        mock_cv2 = MagicMock()
        mock_cv2.imwrite.side_effect = fake_imwrite

        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(True, frame, "")), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=tmp_path):
            tool = CameraTool()
            await tool.execute(filename="my_photo")

            assert "my_photo.jpg" in captured_path[0]

    @pytest.mark.asyncio
    async def test_open_and_read_receives_resolution(self, tmp_path):
        frame = _fake_frame()

        def fake_imwrite(path, f):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"\xff\xd8\xff\xe0fake_jpg")
            return True

        mock_cv2 = MagicMock()
        mock_cv2.imwrite.side_effect = fake_imwrite

        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(True, frame, "")) as mock_read, \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=tmp_path):
            tool = CameraTool()
            await tool.execute(width=1920, height=1080)

            mock_read.assert_called_once_with(0, 1920, 1080)


class TestCameraToolFailures:

    @pytest.mark.asyncio
    async def test_read_frame_failure(self):
        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(False, None, "Failed to read frame from camera.")), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=Path("/tmp")):
            tool = CameraTool()
            result = await tool.execute()

            assert "Error" in result
            assert "Failed to read frame" in result

    @pytest.mark.asyncio
    async def test_imwrite_failure(self):
        frame = _fake_frame()
        mock_cv2 = MagicMock()
        mock_cv2.imwrite.return_value = False

        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(True, frame, "")), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=Path("/tmp")):
            tool = CameraTool()
            result = await tool.execute()

            assert "Error" in result
            assert "Failed to save" in result

    @pytest.mark.asyncio
    async def test_timeout(self):
        import asyncio

        async def slow_read(*args):
            await asyncio.sleep(999)
            return (True, _fake_frame(), "")

        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera._open_and_read", side_effect=lambda *a: None), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=Path("/tmp")), \
             patch("asyncio.to_thread", side_effect=slow_read):
            tool = CameraTool(capture_timeout=1)
            result = await tool.execute()

            assert "Error" in result
            assert "timed out" in result

    @pytest.mark.asyncio
    async def test_invalid_filename_rejected(self):
        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=Path("/tmp")):
            tool = CameraTool()
            result = await tool.execute(filename="../../etc/shadow")

            assert "Error" in result
            assert "Invalid filename" in result

    @pytest.mark.asyncio
    async def test_imwrite_exception(self):
        frame = _fake_frame()
        mock_cv2 = MagicMock()
        mock_cv2.imwrite.side_effect = OSError("disk full")

        with patch("nanobot.agent.tools.camera._HAS_CV2", True), \
             patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._open_and_read", return_value=(True, frame, "")), \
             patch("nanobot.agent.tools.camera.get_media_dir", return_value=Path("/tmp")):
            tool = CameraTool()
            result = await tool.execute()

            assert "Error" in result
            assert "disk full" in result


class TestOpenAndRead:

    def test_device_not_opened(self):
        mock_cv2 = MagicMock()
        cap = MagicMock()
        cap.isOpened.return_value = False
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

        with patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._HAS_CV2", True):
            from nanobot.agent.tools.camera import _open_and_read
            success, frame, err = _open_and_read(0, 640, 480)
            assert success is False
            assert err == ""
            cap.release.assert_called_once()

    def test_successful_read(self):
        mock_cv2 = MagicMock()
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.read.return_value = (True, _fake_frame())
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

        with patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._HAS_CV2", True):
            from nanobot.agent.tools.camera import _open_and_read
            success, frame, err = _open_and_read(0, 1280, 720)
            assert success is True
            assert frame is not None
            assert err == ""
            cap.set.assert_any_call(3, 1280)
            cap.set.assert_any_call(4, 720)
            cap.release.assert_called_once()


class TestAvailableDevices:

    def test_returns_empty_when_no_cv2(self):
        with patch("nanobot.agent.tools.camera._HAS_CV2", False):
            assert _available_devices() == []

    def test_probes_and_returns_open_indices(self):
        mock_cv2 = MagicMock()
        opened = MagicMock()
        opened.isOpened.return_value = True
        closed = MagicMock()
        closed.isOpened.return_value = False

        mock_cv2.VideoCapture.side_effect = [opened, closed, opened]

        with patch("nanobot.agent.tools.camera.cv2", mock_cv2), \
             patch("nanobot.agent.tools.camera._HAS_CV2", True):
            result = _available_devices(max_index=3)
            assert result == [0, 2]
            opened.release.assert_called()
            closed.release.assert_not_called()


class TestCameraToolSchema:

    def test_name(self):
        tool = CameraTool()
        assert tool.name == "camera_capture"

    def test_description_mentions_opencv(self):
        tool = CameraTool()
        assert "opencv" in tool.description.lower()

    def test_parameters_has_expected_keys(self):
        tool = CameraTool()
        props = tool.parameters.get("properties", {})
        assert "device_index" in props
        assert "width" in props
        assert "height" in props
        assert "filename" in props

    def test_tool_schema_is_valid(self):
        tool = CameraTool()
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "camera_capture"
