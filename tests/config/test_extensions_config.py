import pytest
from pydantic import ValidationError

from nanobot.config.schema import Config, ExtensionsConfig


def test_extensions_config_accepts_camel_case_workspace_trust() -> None:
    config = Config.model_validate(
        {
            "extensions": {
                "workspaceTrust": "allow",
                "entries": {
                    "acme": {
                        "enabled": True,
                        "trusted": True,
                        "config": {"endpoint": "https://example.com"},
                    }
                },
            }
        }
    )

    assert config.extensions.workspace_trust == "allow"
    assert config.extensions.entries["acme"].trusted is True


def test_extensions_config_rejects_overlapping_policy() -> None:
    with pytest.raises(ValidationError, match="both allow and deny"):
        ExtensionsConfig(allow=["acme"], deny=["acme"])
