"""Tests for custom provider thinking_style config passthrough."""

from __future__ import annotations

from blackcat.config.schema import ProviderConfig, ProvidersConfig
from blackcat.providers.registry import create_dynamic_spec


class TestCustomProviderThinkingStyle:
    """Verify that thinking_style flows from config to ProviderSpec."""

    def test_default_thinking_style_is_empty(self) -> None:
        cfg = ProviderConfig()
        assert cfg.thinking_style is None

    def test_create_dynamic_spec_default(self) -> None:
        spec = create_dynamic_spec("custom")
        assert spec.thinking_style == ""

    def test_create_dynamic_spec_with_thinking_type(self) -> None:
        spec = create_dynamic_spec("custom", thinking_style="thinking_type")
        assert spec.thinking_style == "thinking_type"

    def test_create_dynamic_spec_with_enable_thinking(self) -> None:
        spec = create_dynamic_spec("custom", thinking_style="enable_thinking")
        assert spec.thinking_style == "enable_thinking"

    def test_create_dynamic_spec_with_reasoning_split(self) -> None:
        spec = create_dynamic_spec("custom", thinking_style="reasoning_split")
        assert spec.thinking_style == "reasoning_split"

    def test_provider_config_accepts_camel_case(self) -> None:
        """Config JSON uses camelCase: thinkingStyle."""
        cfg = ProviderConfig.model_validate({"thinkingStyle": "thinking_type"})
        assert cfg.thinking_style == "thinking_type"

    def test_providers_config_custom_has_thinking_style(self) -> None:
        """Full providers config round-trip."""
        data = {
            "custom": {
                "apiKey": "sk-test",
                "apiBase": "https://example.com/v1",
                "thinkingStyle": "enable_thinking",
            }
        }
        pc = ProvidersConfig.model_validate(data)
        assert pc.custom.thinking_style == "enable_thinking"

    def test_invalid_thinking_style_raises_with_clear_message(self) -> None:
        """An invalid thinking_style must raise a ValidationError whose message
        lists the valid options (not just Pydantic's generic Literal error)."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            ProviderConfig.model_validate({"thinkingStyle": "thinking_typ"})

        message = str(exc_info.value)
        assert "Invalid thinking_style" in message
        assert "thinking_type" in message
        assert "enable_thinking" in message
        assert "reasoning_split" in message
