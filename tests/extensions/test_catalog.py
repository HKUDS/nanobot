import json

from nanobot.config.schema import Config
from nanobot.extensions.catalog import build_extension_catalog
from nanobot.extensions.store import ExtensionStore


def _write_extension(root, extension_id: str) -> None:
    package = root / extension_id
    package.mkdir(parents=True)
    (package / "nanobot.extension.json").write_text(
        json.dumps(
            {
                "id": extension_id,
                "name": extension_id,
                "version": "1.0.0",
                "entry": "extension:register",
            }
        )
    )


def test_catalog_requires_trust_before_activation(tmp_path) -> None:
    _write_extension(tmp_path, "acme")

    catalog = build_extension_catalog(Config(), user_root=tmp_path)

    assert [item.manifest.id for item in catalog.candidates] == ["acme"]
    assert catalog.snapshot.extensions == ()


def test_store_policy_can_trust_an_extension(tmp_path) -> None:
    source = tmp_path / "source"
    _write_extension(source, "acme")
    store = ExtensionStore(tmp_path / "installed")
    store.install_local(source / "acme")
    store.set_trusted("acme", True)

    catalog = build_extension_catalog(Config(), user_root=store.root)

    assert [item.manifest.id for item in catalog.snapshot.extensions] == ["acme"]


def test_disabled_catalog_discovers_nothing(tmp_path) -> None:
    _write_extension(tmp_path, "acme")

    catalog = build_extension_catalog(
        Config.model_validate({"extensions": {"enabled": False}}),
        user_root=tmp_path,
    )

    assert catalog.candidates == ()
