import json
from unittest.mock import patch

from nanobot.config.schema import Config
from nanobot.extensions import build_extension_catalog


def _write_extension(root, extension_id: str) -> None:
    package = root / extension_id
    package.mkdir(parents=True)
    (package / "nanobot.extension.json").write_text(
        json.dumps(
            {
                "id": extension_id,
                "name": extension_id,
                "version": "1.0.0",
                "runtime": "python",
                "contributions": [{"kind": "tool", "name": f"{extension_id}_tool"}],
            }
        )
    )


def _catalog(config: Config, user_root):
    with (
        patch("nanobot.channels.registry.discover_plugins", return_value={}),
        patch("nanobot.providers.registry.PROVIDERS", ()),
        patch("nanobot.audio.transcription_registry.TRANSCRIPTION_PROVIDERS", ()),
        patch(
            "nanobot.providers.image_generation.image_gen_provider_names",
            return_value=(),
        ),
    ):
        return build_extension_catalog(config, user_root=user_root)


def test_installed_extension_requires_explicit_trust(tmp_path) -> None:
    _write_extension(tmp_path, "acme")

    catalog = _catalog(Config(), tmp_path)

    assert [item.manifest.id for item in catalog.candidates] == ["acme"]
    assert catalog.snapshot.extensions == ()


def test_entry_config_trust_activates_installed_extension(tmp_path) -> None:
    _write_extension(tmp_path, "acme")
    config = Config.model_validate(
        {
            "extensions": {
                "entries": {
                    "acme": {
                        "enabled": True,
                        "trusted": True,
                    }
                }
            }
        }
    )

    catalog = _catalog(config, tmp_path)

    assert [item.manifest.id for item in catalog.snapshot.extensions] == ["acme"]
    assert catalog.snapshot.contributions[0].contribution.name == "acme_tool"


def test_extensions_disabled_keeps_native_catalog_only(tmp_path) -> None:
    _write_extension(tmp_path, "acme")
    config = Config.model_validate({"extensions": {"enabled": False}})

    catalog = _catalog(config, tmp_path)

    assert all(item.manifest.id != "acme" for item in catalog.candidates)
