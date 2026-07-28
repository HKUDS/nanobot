import pytest

from nanobot.extensions import ExtensionManifest, ExtensionPermission
from nanobot.extensions.registry import ExtensionCandidate, ExtensionRegistry


def _candidate(
    extension_id: str,
    *,
    trusted: bool = True,
    permissions: tuple[ExtensionPermission, ...] = (),
    granted: frozenset[str] = frozenset(),
) -> ExtensionCandidate:
    return ExtensionCandidate(
        ExtensionManifest(
            id=extension_id,
            name=extension_id,
            version="1.0.0",
            permissions=permissions,
        ),
        trusted=trusted,
        granted_permissions=granted,
    )


def test_only_trusted_extensions_activate() -> None:
    registry = ExtensionRegistry()
    registry.register(_candidate("trusted"))
    registry.register(_candidate("untrusted", trusted=False))

    assert [item.manifest.id for item in registry.snapshot().extensions] == ["trusted"]


def test_every_requested_permission_must_be_granted() -> None:
    registry = ExtensionRegistry()
    registry.register(
        _candidate(
            "permission.test",
            permissions=(
                ExtensionPermission(name="network"),
                ExtensionPermission(name="filesystem.read"),
            ),
            granted=frozenset({"network"}),
        )
    )

    snapshot = registry.snapshot()

    assert snapshot.extensions == ()
    assert snapshot.diagnostics[0].code == "permission_required"
    assert "filesystem.read" in snapshot.diagnostics[0].message


def test_duplicate_extension_ids_are_rejected() -> None:
    registry = ExtensionRegistry()
    registry.register(_candidate("duplicate"))

    with pytest.raises(ValueError, match="already installed"):
        registry.register(_candidate("duplicate"))
