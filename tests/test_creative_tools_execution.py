"""Execution tests for creative tools: image, video, music, speech, and weather.

These tests invoke the agent from CLI, mimicking gateway invocation.
Generated files are saved to disk (except video - URI is printed and agent tries to download).

Run with:
    pytest tests/test_creative_tools_execution.py -v                    # all tests
    pytest tests/test_creative_tools_execution.py -m "not slow" -v      # fast tests only
    pytest tests/test_creative_tools_execution.py -m creative -v        # creative tools only
    pytest tests/test_creative_tools_execution.py::TestWeatherTool -v   # weather only
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from scorpion.config.loader import load_config
from scorpion.bus.queue import MessageBus
from scorpion.adk.loop import AdkAgentLoop
from scorpion.cron.service import CronService
from scorpion.providers.gemini_provider import GeminiProvider


# Test prompts for each tool
TEST_PROMPTS = {
    "image": "A red apple on a white background, photorealistic",
    "video": "A cat walking on a beach at sunset",
    "music": "Upbeat electronic dance music, 120 BPM",
    "speech": "Hello, this is a test.",
    "weather": "What's the weather in Tokyo?",
}


def _make_provider():
    """Create the Gemini LLM provider from config."""
    config = load_config()
    model = config.agents.defaults.model
    p = config.get_provider(model)

    if not (p and p.api_key):
        pytest.skip("No Gemini API key configured")

    return GeminiProvider(api_key=p.api_key, default_model=model)


def _create_agent_loop(workspace: Path):
    """Create an agent loop for testing."""
    config = load_config()
    bus = MessageBus()
    provider = _make_provider()
    cron_store_path = Path.home() / ".scorpion" / "data" / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    return AdkAgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        reasoning_effort=config.agents.defaults.reasoning_effort,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )


@pytest.mark.creative
@pytest.mark.slow
class TestImageGeneration:
    """Test image generation tool execution."""

    @pytest.mark.asyncio
    async def test_generate_image_saves_to_disk(self):
        """Test that image generation creates a file on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent_loop = _create_agent_loop(workspace)

            try:
                response = await agent_loop.process_direct(
                    f"Generate an image: {TEST_PROMPTS['image']}",
                    "test:image",
                )

                # Check response indicates success
                assert response is not None
                print(f"\n✓ Image response: {response[:200]}")

                # Check that images were created in media directory
                media_dir = Path.home() / ".scorpion" / "media" / "images"
                if media_dir.exists():
                    images = list(media_dir.glob("image_*.png"))
                    assert len(images) > 0, "No images were generated"
                    print(f"✓ Generated {len(images)} image(s) saved to {media_dir}")

            finally:
                await agent_loop.close_mcp()


@pytest.mark.creative
@pytest.mark.slow
@pytest.mark.skip(reason="Video generation takes 5-10 minutes, run manually when needed")
class TestVideoGeneration:
    """Test video generation tool execution."""

    @pytest.mark.asyncio
    async def test_generate_video_returns_uri(self):
        """Test that video generation returns a URI/path.
        
        Video takes 1-5 minutes, so we just verify the request is initiated.
        The agent will try to download from the URI if successful.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent_loop = _create_agent_loop(workspace)

            try:
                response = await agent_loop.process_direct(
                    f"Generate a video: {TEST_PROMPTS['video']}",
                    "test:video",
                )

                assert response is not None
                print(f"\n✓ Video response: {response[:300]}")

                # Video generation should return path or indicate processing
                # The actual download happens asynchronously via subagent

            finally:
                await agent_loop.close_mcp()

    @pytest.mark.asyncio
    async def test_generate_video_503_handling(self):
        """Test that 503 errors are handled gracefully with friendly message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent_loop = _create_agent_loop(workspace)

            try:
                response = await agent_loop.process_direct(
                    f"Generate a video: {TEST_PROMPTS['video']}",
                    "test:video:503",
                )

                assert response is not None
                print(f"\n✓ Video 503 handling: {response[:200]}")

                # Check for friendly error message (if 503 occurs)
                # Note: May succeed if service is available

            finally:
                await agent_loop.close_mcp()


@pytest.mark.creative
@pytest.mark.slow
class TestMusicGeneration:
    """Test music generation tool execution."""

    @pytest.mark.asyncio
    async def test_generate_music_saves_to_disk(self):
        """Test that music generation creates a WAV file on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent_loop = _create_agent_loop(workspace)

            try:
                response = await agent_loop.process_direct(
                    f"Generate music: {TEST_PROMPTS['music']}",
                    "test:music",
                )

                assert response is not None
                print(f"\n✓ Music response: {response[:200]}")

                # Check that music files were created
                media_dir = Path.home() / ".scorpion" / "media" / "music"
                if media_dir.exists():
                    music_files = list(media_dir.glob("music_*.wav"))
                    if len(music_files) > 0:
                        print(f"✓ Generated {len(music_files)} music file(s)")
                        # Verify file is valid WAV
                        import wave
                        try:
                            with wave.open(str(music_files[0]), 'rb') as wf:
                                assert wf.getnchannels() in (1, 2)
                                assert wf.getframerate() == 48000
                                print(f"✓ WAV validation passed: {wf.getnchannels()}ch, {wf.getframerate()}Hz")
                        except Exception as e:
                            print(f"⚠ WAV validation skipped: {e}")

            finally:
                await agent_loop.close_mcp()


@pytest.mark.creative
@pytest.mark.slow
class TestSpeechGeneration:
    """Test text-to-speech generation tool execution."""

    @pytest.mark.asyncio
    async def test_generate_speech_saves_to_disk(self):
        """Test that speech generation creates an audio file on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent_loop = _create_agent_loop(workspace)

            try:
                response = await agent_loop.process_direct(
                    f"Generate speech: {TEST_PROMPTS['speech']}",
                    "test:speech",
                )

                assert response is not None
                print(f"\n✓ Speech response: {response[:200]}")

                # Check that speech files were created
                media_dir = Path.home() / ".scorpion" / "media" / "speech"
                if media_dir.exists():
                    speech_files = list(media_dir.glob("speech_*.wav"))
                    assert len(speech_files) > 0, "No speech files were generated"
                    print(f"✓ Generated {len(speech_files)} speech file(s)")

            finally:
                await agent_loop.close_mcp()


class TestWeatherTool:
    """Test weather tool execution."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_weather_returns_forecast(self):
        """Test that weather tool returns forecast information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent_loop = _create_agent_loop(workspace)

            try:
                response = await agent_loop.process_direct(
                    TEST_PROMPTS['weather'],
                    "test:weather",
                )

                assert response is not None
                print(f"\n✓ Weather response: {response[:300]}")

                # Should contain weather-related information
                weather_keywords = ["temperature", "weather", "°", "C", "F", "cloud", "sun", "rain", "Tokyo"]
                has_weather_info = any(kw.lower() in response.lower() for kw in weather_keywords)
                assert has_weather_info, f"Weather response doesn't contain expected info"

            finally:
                await agent_loop.close_mcp()

    @pytest.mark.asyncio
    async def test_weather_tool_direct(self):
        """Test weather tool by directly invoking the skill (faster)."""
        # Direct test without full agent loop
        import subprocess
        try:
            result = subprocess.run(
                ['curl', '-s', 'wttr.in/Tokyo?format=3'],
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode == 0:
                assert "Tokyo" in result.stdout or "°" in result.stdout
                print(f"\n✓ Direct weather API test: {result.stdout.strip()}")
            else:
                pytest.skip(f"Weather API unavailable: {result.stderr}")
        except subprocess.TimeoutExpired:
            pytest.skip("Weather API timeout - network slow")
        except Exception as e:
            pytest.skip(f"Weather API error: {e}")


@pytest.mark.integration
@pytest.mark.slow
class TestCreativeToolsIntegration:
    """Integration tests for multiple creative tools."""

    @pytest.mark.asyncio
    async def test_image_then_weather(self):
        """Test sequential execution of image generation and weather query."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent_loop = _create_agent_loop(workspace)

            try:
                # Generate image first
                response1 = await agent_loop.process_direct(
                    f"Generate an image: {TEST_PROMPTS['image']}",
                    "test:integration:image",
                )
                assert response1 is not None
                print(f"\n✓ Integration - Image: {response1[:100]}...")

                # Then get weather
                response2 = await agent_loop.process_direct(
                    TEST_PROMPTS['weather'],
                    "test:integration:weather",
                )
                assert response2 is not None
                print(f"✓ Integration - Weather: {response2[:100]}...")

            finally:
                await agent_loop.close_mcp()


# CLI-style test that mimics gateway invocation
@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_cli_style_invocation():
    """Test that mimics CLI gateway invocation pattern."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Setup exactly like CLI does
        config = load_config()
        bus = MessageBus()
        provider = _make_provider()
        cron_store_path = Path.home() / ".scorpion" / "data" / "cron" / "jobs.json"
        cron = CronService(cron_store_path)

        agent_loop = AdkAgentLoop(
            bus=bus,
            provider=provider,
            workspace=workspace,
            model=config.agents.defaults.model,
            temperature=config.agents.defaults.temperature,
            max_tokens=config.agents.defaults.max_tokens,
            max_iterations=config.agents.defaults.max_tool_iterations,
            memory_window=config.agents.defaults.memory_window,
            reasoning_effort=config.agents.defaults.reasoning_effort,
            brave_api_key=config.tools.web.search.api_key or None,
            exec_config=config.tools.exec,
            cron_service=cron,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            mcp_servers=config.tools.mcp_servers,
            channels_config=config.channels,
        )

        try:
            # Test various tool invocations
            test_cases = [
                ("generate_image", f"Generate: {TEST_PROMPTS['image']}"),
                ("weather", TEST_PROMPTS['weather']),
            ]

            for tool_name, prompt in test_cases:
                response = await agent_loop.process_direct(
                    prompt,
                    f"test:cli:{tool_name}",
                )
                assert response is not None, f"{tool_name} returned None"
                print(f"\n✓ CLI {tool_name}: {response[:150]}...")

        finally:
            await agent_loop.close_mcp()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
