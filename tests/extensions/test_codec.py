import json

import pytest

from nanobot.extensions import (
    ContributionKind,
    ExtensionContribution,
    ExtensionManifest,
    ExtensionRuntime,
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
        runtime=ExtensionRuntime.PI,
        contributions=(
            ExtensionContribution(
                kind=ContributionKind.TOOL,
                name="acme_search",
                target="./index.ts#search",
            ),
        ),
    )

    dump_manifest(original, path)

    assert load_manifest(path) == original
    assert json.loads(path.read_text())["apiVersion"] == 1


def test_manifest_rejects_unknown_fields() -> None:
    with pytest.raises(ManifestFormatError, match="unknown fields: typo"):
        manifest_from_mapping(
            {
                "id": "bad",
                "name": "Bad",
                "version": "1.0.0",
                "runtime": "python",
                "typo": True,
            }
        )


def test_manifest_rejects_unknown_contribution_kind() -> None:
    with pytest.raises(ManifestFormatError, match="invalid extension contribution"):
        manifest_from_mapping(
            {
                "id": "bad",
                "name": "Bad",
                "version": "1.0.0",
                "runtime": "python",
                "contributions": [{"kind": "mystery", "name": "unknown"}],
            }
        )
