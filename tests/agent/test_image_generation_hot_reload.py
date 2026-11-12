"""Image generation runtime reload tests."""

from __future__ import annotations

import pytest

from nanobot.agent.tools.image_generation import (
    ImageGenerationTool,
    register_image_generation_tool,
    reload_image_generation_tool,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config, save_config
from nanobot.webui.settings_models import create_provider_settings


async def test_dynamic_image_overrides_reload_without_changing_inflight_client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "other-instance.json")
    config = load_config(config_path)
    name = create_provider_settings(config, {"name": ["Image gateway"], "apiBase": ["https://images.test/v1"]})
    connection = getattr(config.providers, name)
    connection.api_key = "named-image-key"
    connection.extra_headers = {"X-Connection": "image"}
    connection.extra_body = {"quality": "low"}
    config.tools.image_generation.enabled = True
    config.tools.image_generation.provider = name
    config.tools.image_generation.extra_headers = {"X-Route": "before"}
    config.tools.image_generation.extra_body = {"watermark": True}
    save_config(config, config_path)
    registry = ToolRegistry()
    register_image_generation_tool(config, registry, workspace=tmp_path)
    first_tool = registry.get("generate_image")
    assert isinstance(first_tool, ImageGenerationTool)
    first = first_tool._provider_client()
    assert first is not None
    definitions = registry.get_definitions()
    config.tools.image_generation.extra_headers = {"X-Route": "after"}
    config.tools.image_generation.extra_body = {"watermark": False}
    save_config(config, config_path)
    result = await reload_image_generation_tool(config_path=config_path, workspace=tmp_path, registry=registry)
    assert result["requires_restart"] is False
    second_tool = registry.get("generate_image")
    assert isinstance(second_tool, ImageGenerationTool)
    second = second_tool._provider_client()
    assert second is not None
    assert first.api_key == second.api_key == "named-image-key"
    assert first.api_base == second.api_base == "https://images.test/v1"
    assert first.extra_headers == {"X-Connection": "image", "X-Route": "before"}
    assert second.extra_headers == {"X-Connection": "image", "X-Route": "after"}
    assert first.extra_body == {"quality": "low", "watermark": True}
    assert second.extra_body == {"quality": "low", "watermark": False}
    assert registry.get_definitions() == definitions


@pytest.mark.asyncio
async def test_image_generation_reload_replaces_and_removes_live_tool(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "other-instance.json")
    config = load_config(config_path)
    config.providers.openrouter.api_key = "first-key"
    config.tools.image_generation.enabled = True
    config.tools.image_generation.provider = "openrouter"
    config.tools.image_generation.model = "openai/first-image-model"
    save_config(config, config_path)

    registry = ToolRegistry()
    assert registry.get_definitions() == []
    result = await reload_image_generation_tool(config_path=config_path, workspace=tmp_path, registry=registry)

    first_tool = registry.get("generate_image")
    assert result["requires_restart"] is False
    assert isinstance(first_tool, ImageGenerationTool)
    assert first_tool.config.model == "openai/first-image-model"
    assert first_tool.provider_configs["openrouter"].api_key == "first-key"
    assert [definition["function"]["name"] for definition in registry.get_definitions()] == [
        "generate_image"
    ]

    config = load_config(config_path)
    config.providers.openrouter.api_key = "second-key"
    config.tools.image_generation.model = "openai/second-image-model"
    save_config(config, config_path)

    result = await reload_image_generation_tool(config_path=config_path, workspace=tmp_path, registry=registry)
    second_tool = registry.get("generate_image")
    assert result["requires_restart"] is False
    assert isinstance(second_tool, ImageGenerationTool)
    assert second_tool is not first_tool
    assert second_tool.config.model == "openai/second-image-model"
    assert second_tool.provider_configs["openrouter"].api_key == "second-key"

    config = load_config(config_path)
    config.tools.image_generation.enabled = False
    save_config(config, config_path)

    result = await reload_image_generation_tool(config_path=config_path, workspace=tmp_path, registry=registry)
    assert result["requires_restart"] is False
    assert not registry.has("generate_image")
    assert registry.get_definitions() == []


@pytest.mark.asyncio
async def test_image_generation_reload_failure_preserves_live_tool(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = load_config(config_path)
    config.tools.image_generation.enabled = True
    config.providers.openrouter.api_key = "working-key"
    save_config(config, config_path)
    registry = ToolRegistry()
    await reload_image_generation_tool(config_path=config_path, workspace=tmp_path, registry=registry)
    working_tool = registry.get("generate_image")
    definitions = registry.get_definitions()

    missing_env = "NANOBOT_TEST_IMAGE_RELOAD_KEY"
    monkeypatch.delenv(missing_env, raising=False)
    config.providers.openrouter.api_key = f"${{{missing_env}}}"
    save_config(config, config_path)
    result = await reload_image_generation_tool(config_path=config_path, workspace=tmp_path, registry=registry)

    assert result["ok"] is False
    assert result["requires_restart"] is True
    assert registry.get("generate_image") is working_tool
    assert registry.get_definitions() == definitions
