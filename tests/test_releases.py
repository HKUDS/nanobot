import hashlib
import json

import pytest
from packaging.tags import Tag, mac_platforms
from pydantic import ValidationError

from nanobot.releases import (
    ReleaseArtifact,
    ReleaseCatalogue,
    ReleaseManifest,
    ReleasePointer,
    release_filenames,
)


def manifest(version="0.3.6.dev42"):
    return ReleaseManifest(
        version=version, source_commit="a" * 40, candidate_commit="b" * 40,
        requires_python=">=3.11",
        artifacts=[ReleaseArtifact(filename=name, size=123, sha256="c" * 64)
                   for name in sorted(release_filenames(version))],
    )


def pointer(version):
    release = manifest(version)
    return ReleasePointer(version=version, candidate_commit=release.candidate_commit,
                          manifest_sha256=hashlib.sha256(release.model_dump_json().encode()).hexdigest())


def test_preview_is_opt_in_and_subscribers_receive_the_final_release():
    catalogue = ReleaseCatalogue(generation=10, stable=pointer("0.3.5"), preview=pointer("0.3.6.dev42"))
    assert catalogue.latest("stable").version == "0.3.5"
    assert catalogue.latest("preview").version == "0.3.6.dev42"
    released = ReleaseCatalogue(generation=11, stable=pointer("0.3.6"), preview=catalogue.preview)
    assert released.latest("preview").version == "0.3.6"


def test_withdrawal_and_stale_catalogue_are_not_update_offers():
    catalogue = ReleaseCatalogue(generation=10, stable=pointer("0.3.5"), preview=pointer("0.3.6.dev42"),
                                 withdrawn={"0.3.6.dev42": "Broken startup"})
    assert catalogue.latest("preview").version == "0.3.5"
    with pytest.raises(ValueError, match="older"):
        catalogue.latest("preview", minimum_generation=11)
    assert ReleaseCatalogue(generation=10).latest("stable") is None


@pytest.mark.parametrize("version", ["0.3.6.dev42", "0.3.6rc1", "0.3.6+local", "../main", "00.3.6"])
def test_stable_catalogue_never_accepts_unreleased_or_noncanonical_targets(version):
    with pytest.raises(ValueError):
        ReleaseCatalogue.model_validate({
            "generation": 1,
            "stable": {"version": version, "candidate_commit": "a" * 40, "manifest_sha256": "b" * 64},
        })


@pytest.mark.parametrize("platform", [
    "macosx_13_0_arm64", "macosx_13_0_x86_64", "manylinux_2_17_aarch64",
    "manylinux_2_17_x86_64", "win_amd64",
])
def test_target_wheel_and_url_are_owned_by_the_manifest(platform):
    release = manifest()
    artifact = release.wheel_for(python_version="3.11.4", supported_tags=[Tag("py3", "none", platform)])
    assert artifact.filename == f"nanobot_ai-0.3.6.dev42-py3-none-{platform}.whl"
    assert release.artifact_url(artifact) == (
        "https://github.com/HKUDS/nanobot/releases/download/v0.3.6.dev42/"
        f"{artifact.filename}#sha256={'c' * 64}"
    )


def test_newer_macos_uses_compatible_minimum_platform_tag():
    tags = [Tag("py3", "none", platform) for platform in mac_platforms((15, 0), "arm64")]
    assert manifest().wheel_for(python_version="3.14.0", supported_tags=tags).filename.endswith(
        "macosx_13_0_arm64.whl"
    )


@pytest.mark.parametrize("platform", ["musllinux_1_2_x86_64", "win_arm64"])
def test_unsupported_platform_does_not_fall_back_to_source_build(platform):
    with pytest.raises(ValueError, match="No compatible"):
        manifest().wheel_for(python_version="3.11.4", supported_tags=[Tag("py3", "none", platform)])


def test_python_requirement_checked_before_platform_selection():
    with pytest.raises(ValueError, match="requires Python"):
        manifest().wheel_for(python_version="3.10.0", supported_tags=[Tag("py3", "none", "win_amd64")])


def test_downloaded_manifest_must_match_selected_bytes_and_identity():
    release = manifest()
    payload = release.model_dump_json().encode()
    selected = pointer(release.version)
    assert selected.verify_manifest(payload) == release
    with pytest.raises(ValueError, match="checksum"):
        selected.verify_manifest(payload + b"\n")
    other_commit = selected.model_copy(update={"candidate_commit": "d" * 40})
    with pytest.raises(ValueError, match="identity"):
        other_commit.verify_manifest(payload)


@pytest.mark.parametrize("change", ["missing", "duplicate", "mixed_version", "universal", "url"])
def test_manifest_rejects_partial_mixed_or_redirected_uploads(change):
    payload = manifest().model_dump(mode="json")
    if change == "missing":
        payload["artifacts"].pop()
    elif change == "duplicate":
        payload["artifacts"][-1] = payload["artifacts"][0]
    elif change == "mixed_version":
        payload["artifacts"][-1]["filename"] = "nanobot_ai-0.3.5.tar.gz"
    elif change == "universal":
        payload["artifacts"][-1]["filename"] = "nanobot_ai-0.3.6.dev42-py3-none-any.whl"
    else:
        payload["artifacts"][0]["url"] = "https://untrusted.example/installer.sh"
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate_json(json.dumps(payload))


def test_catalogue_unknown_schema_and_blank_withdrawal_reason_fail_closed():
    with pytest.raises(ValidationError):
        ReleaseCatalogue.model_validate_json('{"schema_version":2,"generation":1}')
    with pytest.raises(ValidationError, match="withdrawal reason"):
        ReleaseCatalogue(generation=1, withdrawn={"0.3.6.dev42": " "})
