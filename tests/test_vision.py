"""Tests for vision/multi-modal support in LiteLLMProvider."""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


class TestVisionFormatSupport:
    """Test vision format conversion for different providers."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = LiteLLMProvider(
            api_key="test-key",
            default_model="anthropic/claude-opus-4-5"
        )
        self.test_image_base64 = base64.b64encode(b"test_image_data").decode()
        self.test_image_data_url = f"data:image/jpeg;base64,{self.test_image_base64}"

    def test_has_image_content_with_text_only(self):
        """Test detection of text-only content."""
        assert not self.provider._has_image_content("Just text")

    def test_has_image_content_with_images(self):
        """Test detection of content with images."""
        content = [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]
        assert self.provider._has_image_content(content)

    def test_has_image_content_with_empty_list(self):
        """Test detection with empty list."""
        assert not self.provider._has_image_content([])

    def test_format_content_for_provider_text_only(self):
        """Test that text-only content is returned as-is."""
        content = "Just text message"
        result = self.provider._format_content_for_provider(content, "gpt-4")
        assert result == "Just text message"

    def test_format_for_claude_with_image(self):
        """Test Claude vision format conversion."""
        content = [
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_for_claude(content)

        assert len(result) == 2
        # Order is preserved
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "Describe this image"
        assert result[1]["type"] == "image"
        assert result[1]["source"]["type"] == "base64"
        assert result[1]["source"]["media_type"] == "image/jpeg"
        assert result[1]["source"]["data"] == self.test_image_base64

    def test_format_for_claude_with_invalid_data_url(self):
        """Test Claude format with invalid data URL."""
        content = [
            {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
        ]

        result = self.provider._format_for_claude(content)

        # Should return empty list for invalid URLs
        assert result == []

    def test_format_for_gemini_with_image(self):
        """Test Gemini vision format conversion."""
        content = [
            {"type": "text", "text": "What do you see?"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_for_gemini(content)

        assert len(result) == 2
        # Order is preserved
        assert result[0]["text"] == "What do you see?"
        assert result[1]["inline_data"]["mime_type"] == "image/jpeg"
        assert result[1]["inline_data"]["data"] == self.test_image_base64

    def test_format_for_gemini_with_invalid_url(self):
        """Test Gemini format with invalid URL."""
        content = [
            {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
        ]

        result = self.provider._format_for_gemini(content)

        # Should return empty list for invalid URLs
        assert result == []

    def test_format_content_for_provider_openai(self):
        """Test that OpenAI format is preserved."""
        content = [
            {"type": "text", "text": "Analyze this"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_content_for_provider(content, "gpt-4-vision")

        # OpenAI format should be returned as-is
        assert result == content

    def test_format_content_for_provider_claude(self):
        """Test routing to Claude formatter."""
        content = [
            {"type": "text", "text": "See this"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_content_for_provider(content, "claude-opus-4-5")

        # Should be formatted for Claude
        assert len(result) == 2
        # Order preserved - text first
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image"

    def test_format_content_for_provider_gemini(self):
        """Test routing to Gemini formatter."""
        content = [
            {"type": "text", "text": "Look at this"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_content_for_provider(content, "gemini-pro-vision")

        # Should be formatted for Gemini
        assert len(result) == 2
        # Order preserved
        assert result[0]["text"] == "Look at this"
        assert "inline_data" in result[1]

    def test_format_messages_for_provider(self):
        """Test formatting complete message list."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
                ]
            }
        ]

        result = self.provider._format_messages_for_provider(messages, "claude-opus-4-5")

        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a helpful assistant."
        assert result[1]["role"] == "user"
        # User content should be formatted for Claude
        assert len(result[1]["content"]) == 2

    def test_format_messages_preserves_tool_calls(self):
        """Test that tool calls are preserved during formatting."""
        messages = [
            {
                "role": "assistant",
                "content": "Let me check that for you.",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"}
                    }
                ]
            }
        ]

        result = self.provider._format_messages_for_provider(messages, "gpt-4")

        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Let me check that for you."
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["id"] == "call_123"

    def test_format_messages_preserves_tool_role(self):
        """Test that tool role messages are preserved."""
        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "name": "search",
                "content": "Search results: ..."
            }
        ]

        result = self.provider._format_messages_for_provider(messages, "gpt-4")

        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_123"
        assert result[0]["name"] == "search"

    def test_multiple_images_format(self):
        """Test formatting multiple images for Claude."""
        img1 = f"data:image/jpeg;base64,{base64.b64encode(b'img1').decode()}"
        img2 = f"data:image/png;base64,{base64.b64encode(b'img2').decode()}"

        content = [
            {"type": "text", "text": "Compare these"},
            {"type": "image_url", "image_url": {"url": img1}},
            {"type": "image_url", "image_url": {"url": img2}}
        ]

        result = self.provider._format_for_claude(content)

        # Order is preserved
        assert len(result) == 3
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image"
        assert result[2]["type"] == "image"
        assert result[1]["source"]["media_type"] == "image/jpeg"
        assert result[2]["source"]["media_type"] == "image/png"

    def test_malformed_base64_url(self):
        """Test handling of malformed base64 URLs."""
        content = [
            {"type": "image_url", "image_url": {"url": "data:image,no-base64,here"}}
        ]

        result = self.provider._format_for_claude(content)

        # Should skip malformed entries
        assert result == []


class TestVideoProcessorSecurity:
    """Test security features of VideoProcessor."""

    def setup_method(self):
        """Set up test fixtures."""
        import tempfile
        from nanobot.agent.video import VideoProcessor

        # Create a temp parent directory that will contain both workspace and media
        self.parent_dir = Path(tempfile.mkdtemp())
        self.temp_dir = self.parent_dir / "workspace"
        self.temp_dir.mkdir()

        self.processor = VideoProcessor(self.temp_dir, max_frames=3)

        # VideoProcessor creates media_dir as workspace.parent / "media"
        self.media_dir = self.parent_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        if self.parent_dir.exists():
            shutil.rmtree(self.parent_dir)

    def test_rejects_path_outside_allowed_directories(self):
        """Test that paths outside media/workspace are rejected."""
        # Create a file outside allowed directories
        outside_file = Path("/etc/passwd")

        is_valid, error = self.processor._validate_video_path(outside_file)
        assert not is_valid
        assert "outside allowed directories" in error.lower()

    def test_accepts_path_within_media_directory(self):
        """Test that paths within media directory are accepted."""
        # Create a test video file in media directory
        test_video = self.media_dir / "test_video.mp4"
        test_video.write_bytes(b"fake video content")

        is_valid, error = self.processor._validate_video_path(test_video)
        assert is_valid
        assert error is None

    def test_rejects_oversized_files(self):
        """Test that files exceeding size limit are rejected."""
        from nanobot.agent.video import MAX_VIDEO_SIZE

        # Create a fake oversized video
        test_video = self.media_dir / "huge_video.mp4"
        test_video.write_bytes(b"x" * (MAX_VIDEO_SIZE + 1))

        is_valid, error = self.processor._validate_video_path(test_video)
        assert not is_valid
        assert "too large" in error.lower()

    def test_resolves_symlinks_before_validation(self):
        """Test that symlinks are resolved before checking allowed directories."""
        import tempfile

        # Create a symlink outside allowed directories
        outside_dir = Path(tempfile.mkdtemp())
        outside_file = outside_dir / "outside_video.mp4"
        outside_file.write_bytes(b"fake video")

        symlink = self.media_dir / "symlink.mp4"
        try:
            # Remove symlink if it already exists from previous test run
            if symlink.exists():
                symlink.unlink()

            symlink.symlink_to(outside_file)

            # Should reject since the target is outside allowed directories
            is_valid, error = self.processor._validate_video_path(symlink)
            assert not is_valid
            assert "outside allowed directories" in error.lower()
        finally:
            # Clean up
            if symlink.exists():
                symlink.unlink()
            outside_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.rmtree(outside_dir, ignore_errors=True)


class TestRateLimiter:
    """Test rate limiting functionality."""

    def test_rate_limiter_allows_within_limit(self):
        """Test that requests within limit are allowed."""
        from nanobot.utils.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=5, window_seconds=60)
        is_allowed, error = limiter.is_allowed("user123")
        assert is_allowed
        assert error is None

    def test_rate_limiter_blocks_when_exceeded(self):
        """Test that requests exceeding limit are blocked."""
        from nanobot.utils.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=2, window_seconds=60)

        # First two requests should be allowed
        assert limiter.is_allowed("user123")[0]
        assert limiter.is_allowed("user123")[0]

        # Third request should be blocked
        is_allowed, error = limiter.is_allowed("user123")
        assert not is_allowed
        assert "rate limit exceeded" in error.lower()

    def test_rate_limiter_resets_after_window(self):
        """Test that counter resets after time window expires (without triggering block)."""
        from nanobot.utils.rate_limit import RateLimiter
        import time

        # Use short block duration for testing
        limiter = RateLimiter(max_requests=2, window_seconds=1, block_duration=1)

        # Exhaust limit
        assert limiter.is_allowed("user123")[0]
        assert limiter.is_allowed("user123")[0]

        # Wait for window to expire (but don't exceed to trigger block)
        time.sleep(1.1)

        # Window should have expired, counter reset
        is_allowed, error = limiter.is_allowed("user123")
        assert is_allowed
        assert error is None

    def test_rate_limiter_blocks_for_duration(self):
        """Test that users who exceed limits are blocked for block_duration."""
        from nanobot.utils.rate_limit import RateLimiter
        import time

        # Use very short block and window duration for testing
        limiter = RateLimiter(max_requests=1, window_seconds=1, block_duration=1)

        # Exhaust limit and trigger block
        assert limiter.is_allowed("user123")[0]
        is_allowed, error = limiter.is_allowed("user123")
        assert not is_allowed
        assert "rate limit exceeded" in error.lower()

        # Wait for both block AND window to expire
        time.sleep(1.2)

        # Should now be allowed (both block and window expired)
        is_allowed, error = limiter.is_allowed("user123")
        assert is_allowed
        assert error is None

    def test_rate_limiter_per_user_independent(self):
        """Test that rate limits are tracked per user."""
        from nanobot.utils.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=1, window_seconds=60)

        # Each user should have independent limits
        assert limiter.is_allowed("user1")[0]
        assert not limiter.is_allowed("user1")[0]

        # user2 should still be allowed
        assert limiter.is_allowed("user2")[0]

    def test_rate_limiter_reset(self):
        """Test that reset clears rate limit state."""
        from nanobot.utils.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=1, window_seconds=60)

        assert limiter.is_allowed("user1")[0]
        assert not limiter.is_allowed("user1")[0]

        # Reset specific user
        limiter.reset("user1")
        assert limiter.is_allowed("user1")[0]

        # Test reset all
        assert not limiter.is_allowed("user1")[0]
        limiter.reset()  # Reset all
        assert limiter.is_allowed("user1")[0]

    def test_rate_limiter_cleanup_expired_entries(self):
        """Test that old entries are cleaned up automatically."""
        from nanobot.utils.rate_limit import RateLimiter
        import time

        # Use short max_age for testing
        limiter = RateLimiter(
            max_requests=10,
            window_seconds=60,
            max_age_seconds=1,  # Expire after 1 second
            max_entries=1000,
        )

        # Create entries for multiple users
        for i in range(50):
            limiter.is_allowed(f"user{i}")

        assert len(limiter._state) == 50

        # Wait for entries to expire (need to wait > max_age_seconds)
        time.sleep(1.1)

        # Trigger cleanup by making more requests (CLEANUP_INTERVAL = 100)
        # We need to make enough requests to trigger cleanup
        for i in range(100):
            limiter.is_allowed(f"new_user{i}")

        # After cleanup, old entries should be removed
        # Note: The exact count depends on timing, but old users should be cleaned up
        assert len(limiter._state) < 150, "Cleanup should have removed old entries"

    def test_rate_limiter_max_entries_eviction(self):
        """Test that excess entries are evicted using LRU policy."""
        from nanobot.utils.rate_limit import RateLimiter

        # Set low max_entries to test eviction
        limiter = RateLimiter(
            max_requests=10,
            window_seconds=60,
            max_age_seconds=3600,  # Don't expire by age
            max_entries=10,  # Only keep 10 entries
        )

        # Create many users to exceed max_entries
        # Cleanup runs every 100 requests, so we need to create enough users
        # to trigger cleanup and then verify the state
        for i in range(150):
            limiter.is_allowed(f"user{i}")

        # Cleanup should have run once (at call 100), reducing to ~10 entries
        # Then 50 more users added, so we expect ~60 entries now
        # The key is that cleanup DID run and removed entries
        assert len(limiter._state) < 150, "Cleanup should have removed some entries"

        # Trigger another cleanup by making more requests
        for i in range(100):
            limiter.is_allowed(f"user{i+150}")

        # Now cleanup should have run again, reducing back to ~10 + recent additions
        # The exact count depends on timing, but should be much less than 250
        assert len(limiter._state) < 150, f"Second cleanup should have removed more entries, got {len(limiter._state)}"

    def test_rate_limiter_no_cleanup_when_disabled(self):
        """Test that cleanup can be disabled by setting max_age and max_entries to 0."""
        from nanobot.utils.rate_limit import RateLimiter

        limiter = RateLimiter(
            max_requests=10,
            window_seconds=60,
            max_age_seconds=0,  # Disable age-based cleanup
            max_entries=0,  # Disable max entries limit
        )

        # Create many entries
        for i in range(50):
            limiter.is_allowed(f"user{i}")

        # Entries should not be cleaned up
        assert len(limiter._state) == 50


class TestRateLimiterConcurrency:
    """Test RateLimiter thread safety under concurrent access."""

    def test_concurrent_access_no_errors(self):
        """Test that concurrent access doesn't cause RuntimeError."""
        import threading
        from nanobot.utils.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=1000, window_seconds=60)
        errors = []
        completed = []

        def worker(worker_id: int):
            try:
                for i in range(100):
                    limiter.is_allowed(f"worker{worker_id}_user{i}")
                completed.append(worker_id)
            except RuntimeError as e:
                errors.append(e)

        # Create 20 threads accessing the limiter concurrently
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All workers should complete without RuntimeError
        assert len(completed) == 20, f"Some workers failed: {errors}"
        assert len(errors) == 0, f"Concurrent access caused errors: {errors}"

    def test_concurrent_cleanup_during_access(self):
        """Test that cleanup during concurrent access is safe."""
        import threading
        from nanobot.utils.rate_limit import RateLimiter

        # Use short max_age to trigger frequent cleanup
        limiter = RateLimiter(
            max_requests=10,
            window_seconds=60,
            max_age_seconds=0,  # Immediate cleanup
            max_entries=50,     # Low limit to trigger LRU eviction
        )
        errors = []

        def worker():
            try:
                for i in range(100):
                    limiter.is_allowed(f"user{i}")
            except RuntimeError as e:
                errors.append(e)

        # Create many threads to trigger cleanup concurrently
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent cleanup caused errors: {errors}"
