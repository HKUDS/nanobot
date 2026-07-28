import pytest

from nanobot.extensions import (
    ExtensionDependency,
    ExtensionManifest,
    ExtensionPermission,
)
from nanobot.extensions.manifest import DependencyKind


def test_manifest_defaults_to_native_python_entry() -> None:
    manifest = ExtensionManifest(
        id="acme.research",
        name="Acme Research",
        version="1.2.0",
        permissions=(
            ExtensionPermission(
                name="network",
                reason="Fetch user-selected sources.",
            ),
        ),
    )

    assert manifest.entry == "extension:register"


@pytest.mark.parametrize("extension_id", ["Uppercase", "../escape", "two words", ""])
def test_manifest_rejects_invalid_ids(extension_id: str) -> None:
    with pytest.raises(ValueError):
        ExtensionManifest(id=extension_id, name="Invalid", version="1.0.0")


def test_manifest_rejects_duplicate_contract_rows() -> None:
    dependency = ExtensionDependency(
        kind=DependencyKind.PYTHON,
        name="httpx",
    )
    permission = ExtensionPermission(name="network")

    with pytest.raises(ValueError, match="duplicate dependencies"):
        ExtensionManifest(
            id="duplicate",
            name="Duplicate",
            version="1.0.0",
            dependencies=(dependency, dependency),
        )
    with pytest.raises(ValueError, match="duplicate permissions"):
        ExtensionManifest(
            id="duplicate",
            name="Duplicate",
            version="1.0.0",
            permissions=(permission, permission),
        )
