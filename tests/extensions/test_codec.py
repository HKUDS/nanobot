import json

import pytest

from nanobot.extensions import ExtensionManifest
from nanobot.extensions.codec import (
    ManifestFormatError,
    dump_manifest,
    load_manifest,
    manifest_from_mapping,
)


def test_manifest_json_round_trip(tmp_path) -> None:
    path = tmp_path / "nanobot.extension.json"
    original = ExtensionManifest(
        id="acme.tools",
        name="Acme Tools",
        version="2.0.0",
        entry="acme_extension:register",
    )

    dump_manifest(original, path)

    assert load_manifest(path) == original
    assert json.loads(path.read_text())["apiVersion"] == 1


def test_manifest_codec_rejects_unknown_fields() -> None:
    with pytest.raises(ManifestFormatError, match="unknown fields: typo"):
        manifest_from_mapping(
            {"id": "bad", "name": "Bad", "version": "1.0.0", "typo": True}
        )
    with pytest.raises(ManifestFormatError, match="unknown fields: contributions"):
        manifest_from_mapping(
            {
                "id": "bad",
                "name": "Bad",
                "version": "1.0.0",
                "contributions": [{"kind": "mystery", "name": "unknown"}],
            }
        )
