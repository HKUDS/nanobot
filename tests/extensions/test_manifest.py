import pytest

from nanobot.extensions import (
    ContributionKind,
    ExtensionContribution,
    ExtensionManifest,
    ExtensionPermission,
    ExtensionRuntime,
)


def test_manifest_accepts_portable_contributions() -> None:
    manifest = ExtensionManifest(
        id="acme.research",
        name="Acme Research",
        version="1.2.0",
        runtime=ExtensionRuntime.PYTHON,
        contributions=(
            ExtensionContribution(
                kind=ContributionKind.TOOL,
                name="research",
                target="acme_nanobot:ResearchTool",
            ),
        ),
        permissions=(
            ExtensionPermission(
                name="network",
                reason="Fetch sources selected by the user.",
            ),
        ),
    )

    assert manifest.api_version == 1
    assert manifest.contributions[0].name == "research"


@pytest.mark.parametrize("extension_id", ["Uppercase", "../escape", "two words", ""])
def test_manifest_rejects_invalid_ids(extension_id: str) -> None:
    with pytest.raises(ValueError):
        ExtensionManifest(
            id=extension_id,
            name="Invalid",
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
        )


def test_manifest_rejects_duplicate_contributions() -> None:
    contribution = ExtensionContribution(
        kind=ContributionKind.SKILL,
        name="review",
    )

    with pytest.raises(ValueError, match="duplicate contributions"):
        ExtensionManifest(
            id="duplicate",
            name="Duplicate",
            version="1.0.0",
            runtime=ExtensionRuntime.DECLARATIVE,
            contributions=(contribution, contribution),
        )
