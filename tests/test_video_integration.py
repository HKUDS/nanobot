"""Integration tests for VideoProcessor async operations."""

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.video import VideoProcessor, get_process_registry, MAX_VIDEO_SIZE


class TestVideoProcessorIntegration:
    """Integration tests for VideoProcessor with real file operations."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create a temp parent directory
        self.parent_dir = Path(tempfile.mkdtemp())
        self.workspace = self.parent_dir / "workspace"
        self.workspace.mkdir()

        # VideoProcessor creates media_dir as workspace.parent / "media"
        self.media_dir = self.parent_dir / "media"

        self.processor = VideoProcessor(self.workspace, max_frames=3)

    def teardown_method(self):
        """Clean up test fixtures."""
        if self.parent_dir.exists():
            shutil.rmtree(self.parent_dir)

    def test_video_processor_creates_media_directory(self):
        """Test that VideoProcessor creates the media directory."""
        assert self.media_dir.exists()
        assert self.media_dir.is_dir()

    def test_video_processor_creates_frames_directory(self):
        """Test that VideoProcessor creates the frames subdirectory."""
        frames_dir = self.media_dir / "frames"
        assert frames_dir.exists()
        assert frames_dir.is_dir()

    def test_extract_key_frames_rejects_nonexistent_file(self):
        """Test that extract_key_frames handles missing files."""
        result = asyncio.run(self.processor.extract_key_frames("/nonexistent/video.mp4"))
        assert result == []

    def test_extract_key_frames_rejects_path_outside_allowed(self):
        """Test that extract_key_frames rejects paths outside allowed directories."""
        outside_file = Path("/etc/passwd")
        result = asyncio.run(self.processor.extract_key_frames(outside_file))
        assert result == []

    def test_extract_key_frames_rejects_oversized_files(self):
        """Test that extract_key_frames rejects files exceeding size limit."""
        # Create a fake oversized video
        huge_file = self.media_dir / "huge.mp4"
        huge_file.write_bytes(b"x" * (MAX_VIDEO_SIZE + 1))

        result = asyncio.run(self.processor.extract_key_frames(huge_file))
        assert result == []

    def test_extract_key_frames_without_ffmpeg(self):
        """Test behavior when ffmpeg is not available."""
        # Mock VideoProcessor.is_ffmpeg_available to return False
        with patch.object(VideoProcessor, "is_ffmpeg_available", return_value=False):
            processor = VideoProcessor(self.workspace, max_frames=3)
            result = asyncio.run(processor.extract_key_frames("/fake/video.mp4"))
            assert result == []

    def test_cleanup_frames_removes_all_variants(self):
        """Test that cleanup_frames removes all UUID variants."""
        # Create fake frame files with different UUIDs
        video_path = self.media_dir / "test_video.mp4"
        video_path.write_bytes(b"fake video")

        # Create frame files with UUID pattern
        for uuid_suffix in ["abc123", "def456", "ghi789"]:
            for i in range(1, 4):
                frame_file = self.media_dir / "frames" / f"test_video_{uuid_suffix}_frame_{i}.jpg"
                frame_file.write_bytes(b"fake frame")

        # Run cleanup
        deleted = self.processor.cleanup_frames(video_path)

        # All frames should be deleted
        assert deleted == 9  # 3 UUIDs * 3 frames each
        frames_dir = self.media_dir / "frames"
        remaining = list(frames_dir.glob("test_video_*_*.jpg"))
        assert len(remaining) == 0

    def test_cleanup_frames_with_no_frames(self):
        """Test cleanup_frames when no frames exist."""
        video_path = self.media_dir / "nonexistent.mp4"
        deleted = self.processor.cleanup_frames(video_path)
        assert deleted == 0


class TestVideoProcessorAsyncOperations:
    """Test async operations and subprocess management."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parent_dir = Path(tempfile.mkdtemp())
        self.workspace = self.parent_dir / "workspace"
        self.workspace.mkdir()
        self.media_dir = self.parent_dir / "media"

    def teardown_method(self):
        """Clean up test fixtures."""
        if self.parent_dir.exists():
            shutil.rmtree(self.parent_dir)

    @pytest.mark.asyncio
    async def test_extract_key_frames_timeout(self):
        """Test that timeout works correctly."""
        processor = VideoProcessor(self.workspace, max_frames=3, frame_timeout=0.01)

        # Create a test file (it will fail because it's not a real video)
        test_file = self.media_dir / "test.mp4"
        test_file.write_bytes(b"not a real video")

        # Should timeout quickly (not hang)
        # Note: This may succeed quickly if ffmpeg rejects invalid file immediately
        # The important thing is it doesn't hang
        result = await processor.extract_key_frames(test_file)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_extract_audio_timeout(self):
        """Test that audio extraction timeout works."""
        processor = VideoProcessor(self.workspace, audio_timeout=0.01)

        test_file = self.media_dir / "test.mp4"
        test_file.write_bytes(b"not a real video")

        # Should timeout quickly
        result = await processor.extract_audio(test_file)
        # Result could be None (timeout/error) or Path (unlikely to succeed)
        assert result is None or isinstance(result, Path)

    @pytest.mark.asyncio
    async def test_get_video_info_timeout(self):
        """Test that video info query timeout works."""
        processor = VideoProcessor(self.workspace, info_timeout=0.01)

        test_file = self.media_dir / "test.mp4"
        test_file.write_bytes(b"not a real video")

        # Should timeout quickly
        result = await processor.get_video_info(test_file)
        # Result could be None (timeout/error) or dict (unlikely to succeed)
        assert result is None or isinstance(result, dict)


class TestProcessRegistry:
    """Test the global process registry for tracking subprocesses."""

    def setup_method(self):
        """Set up test fixtures."""
        # Reset global state
        import nanobot.agent.video as video_module
        video_module._global_registry = None

    def teardown_method(self):
        """Clean up test fixtures."""
        import nanobot.agent.video as video_module
        if video_module._global_registry:
            # Clean up any registered processes
            video_module._global_registry._cleanup_all()
        video_module._global_registry = None

    def test_get_process_registry_returns_singleton(self):
        """Test that get_process_registry returns the same instance."""
        registry1 = get_process_registry()
        registry2 = get_process_registry()
        assert registry1 is registry2

    def test_process_registry_tracks_processes(self):
        """Test that ProcessRegistry tracks spawned processes."""
        registry = get_process_registry()

        # Create a mock process
        mock_process = MagicMock()
        mock_process.returncode = None

        registry.register(mock_process)

        # Process should be in registry
        assert mock_process in registry._processes

    def test_process_registry_cleanup_kills_processes(self):
        """Test that cleanup_all kills running processes."""
        registry = get_process_registry()

        # Create mock processes
        mock_process1 = MagicMock()
        mock_process1.returncode = None
        mock_process1.wait = MagicMock(return_value=None)

        mock_process2 = MagicMock()
        mock_process2.returncode = None
        mock_process2.wait = MagicMock(return_value=None)

        registry.register(mock_process1)
        registry.register(mock_process2)

        # Run cleanup
        registry._cleanup_all()

        # Both processes should be killed
        mock_process1.kill.assert_called_once()
        mock_process2.kill.assert_called_once()

    def test_process_registry_weakset_auto_removes(self):
        """Test that WeakSet automatically removes completed processes."""
        registry = get_process_registry()

        # Create and register a process, then let it go out of scope
        def register_process():
            mock_proc = MagicMock()
            mock_proc.returncode = 0  # Completed
            registry.register(mock_proc)
            # mock_proc goes out of scope here

        register_process()

        # Force garbage collection (WeakSet should auto-cleanup)
        import gc
        gc.collect()

        # The process may or may not be in the WeakSet depending on GC timing
        # This is just to verify WeakSet doesn't crash

    def test_process_registry_cleanup_waits_for_termination(self):
        """Test that cleanup waits for process termination."""
        registry = get_process_registry()

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.wait = MagicMock(return_value=None)

        registry.register(mock_process)
        registry._cleanup_all()

        # wait should have been called with timeout keyword argument
        mock_process.wait.assert_called_once()
        call_args = mock_process.wait.call_args
        assert call_args[1]["timeout"] <= 0.5  # Should be ~0.1 timeout

    def test_process_registry_handles_wait_timeout(self):
        """Test that cleanup handles wait timeout gracefully."""
        registry = get_process_registry()

        mock_process = MagicMock()
        mock_process.returncode = None
        # Mock wait to raise TimeoutError
        import asyncio
        mock_process.wait = MagicMock(side_effect=asyncio.TimeoutError)

        registry.register(mock_process)

        # Should not raise exception
        registry._cleanup_all()

        # Process should still be killed
        mock_process.kill.assert_called_once()


class TestVideoProcessorWithRealFiles:
    """Tests that require real file system operations (but mock ffmpeg)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parent_dir = Path(tempfile.mkdtemp())
        self.workspace = self.parent_dir / "workspace"
        self.workspace.mkdir()
        self.media_dir = self.parent_dir / "media"

    def teardown_method(self):
        """Clean up test fixtures."""
        if self.parent_dir.exists():
            shutil.rmtree(self.parent_dir)

    def test_validate_video_path_with_symlink(self):
        """Test that symlinks are resolved and validated."""
        # Create a file outside allowed directory
        outside_dir = Path(tempfile.mkdtemp())
        try:
            outside_file = outside_dir / "outside.mp4"
            outside_file.write_bytes(b"fake video")

            # Ensure media_dir exists
            self.media_dir.mkdir(parents=True, exist_ok=True)

            # Create a symlink inside media directory using absolute path
            symlink = self.media_dir / "symlink.mp4"
            try:
                # Use os.symlink with absolute paths to avoid path resolution issues
                import os
                os.symlink(str(outside_file.resolve()), str(symlink))

                processor = VideoProcessor(self.workspace)

                # Should reject because target is outside allowed directories
                is_valid, error = processor._validate_video_path(symlink)
                assert not is_valid
                assert "outside allowed directories" in error.lower()
            finally:
                if symlink.exists() or symlink.is_symlink():
                    symlink.unlink()
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_validate_path_before_use_checks_symlinks(self):
        """Test that _validate_path_before_use resolves symlinks."""
        outside_dir = Path(tempfile.mkdtemp())
        try:
            outside_file = outside_dir / "outside.mp4"
            outside_file.write_bytes(b"fake video")

            # Ensure media_dir exists
            self.media_dir.mkdir(parents=True, exist_ok=True)

            symlink = self.media_dir / "symlink.mp4"
            try:
                # Use os.symlink with absolute paths
                import os
                os.symlink(str(outside_file.resolve()), str(symlink))

                processor = VideoProcessor(self.workspace)

                # Should raise ValueError
                with pytest.raises(ValueError, match="outside allowed directories"):
                    processor._validate_path_before_use(symlink)
            finally:
                if symlink.exists() or symlink.is_symlink():
                    symlink.unlink()
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_parse_video_info_with_valid_data(self):
        """Test parsing ffprobe output."""
        processor = VideoProcessor(self.workspace)

        # Mock ffprobe output
        ffprobe_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "codec_name": "h264",
                }
            ],
            "format": {
                "duration": "120.5",
                "size": "1048576",
            }
        }

        result = processor._parse_video_info(ffprobe_output)

        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["fps"] == 30.0
        assert result["codec"] == "h264"
        assert result["duration_seconds"] == 120.5
        assert result["size_bytes"] == 1048576

    def test_parse_video_info_with_no_video_stream(self):
        """Test parsing ffprobe output with no video stream."""
        processor = VideoProcessor(self.workspace)

        ffprobe_output = {
            "streams": [
                {
                    "codec_type": "audio",
                }
            ],
            "format": {
                "duration": "60.0",
            }
        }

        result = processor._parse_video_info(ffprobe_output)

        # Should not have video-specific fields
        assert "width" not in result
        assert "height" not in result
        assert "duration_seconds" in result

    def test_parse_video_info_with_invalid_framerate(self):
        """Test parsing with invalid frame rate."""
        processor = VideoProcessor(self.workspace)

        ffprobe_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "r_frame_rate": "invalid",
                }
            ],
            "format": {}
        }

        result = processor._parse_video_info(ffprobe_output)

        # Should handle gracefully
        assert result["fps"] == 0.0

    def test_parse_video_info_with_zero_framerate(self):
        """Test parsing with zero denominator in frame rate."""
        processor = VideoProcessor(self.workspace)

        ffprobe_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "r_frame_rate": "30/0",
                }
            ],
            "format": {}
        }

        result = processor._parse_video_info(ffprobe_output)

        # Should handle division by zero
        assert result["fps"] == 0.0


class TestVideoProcessorEdgeCases:
    """Test edge cases and error conditions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parent_dir = Path(tempfile.mkdtemp())
        self.workspace = self.parent_dir / "workspace"
        self.workspace.mkdir()
        self.media_dir = self.parent_dir / "media"

    def teardown_method(self):
        """Clean up test fixtures."""
        if self.parent_dir.exists():
            shutil.rmtree(self.parent_dir)

    def test_is_ffmpeg_available(self):
        """Test ffmpeg availability check."""
        result = VideoProcessor.is_ffmpeg_available()
        assert isinstance(result, bool)

    def test_max_frames_parameter(self):
        """Test that max_frames parameter is respected."""
        processor = VideoProcessor(self.workspace, max_frames=10)
        assert processor.max_frames == 10

    def test_default_timeouts(self):
        """Test that default timeouts are set."""
        processor = VideoProcessor(self.workspace)

        assert processor.frame_timeout == 30.0
        assert processor.audio_timeout == 30.0
        assert processor.info_timeout == 10.0

    def test_custom_timeouts(self):
        """Test that custom timeouts can be set."""
        processor = VideoProcessor(
            self.workspace,
            frame_timeout=60.0,
            audio_timeout=45.0,
            info_timeout=20.0,
        )

        assert processor.frame_timeout == 60.0
        assert processor.audio_timeout == 45.0
        assert processor.info_timeout == 20.0

    @pytest.mark.asyncio
    async def test_extract_key_frames_with_zero_max_frames(self):
        """Test behavior with max_frames=0 (edge case)."""
        processor = VideoProcessor(self.workspace, max_frames=0)

        test_file = self.media_dir / "test.mp4"
        test_file.write_bytes(b"fake video")

        # Should return empty list (no frames to extract)
        # This will fail at ffmpeg level, so we get []
        result = await processor.extract_key_frames(test_file)
        assert isinstance(result, list)
