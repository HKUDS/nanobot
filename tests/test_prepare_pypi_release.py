import hashlib

import pytest

from nanobot.releases import ReleaseArtifact, ReleaseManifest, release_filenames
from scripts import prepare_pypi_release


@pytest.fixture
def accepted_release(tmp_path):
    source = tmp_path / "release"
    source.mkdir()
    artifacts = []
    for filename in sorted(release_filenames("1.2.3")):
        data = filename.encode()
        (source / filename).write_bytes(data)
        artifacts.append(ReleaseArtifact(filename=filename, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
    manifest = ReleaseManifest(version="1.2.3", source_commit="b" * 40, candidate_commit="b" * 40,
                               requires_python=">=3.11", artifacts=artifacts)
    payload = manifest.model_dump_json()
    (source / "release-manifest.json").write_text(payload)
    accepted = tmp_path / "accepted-manifest.json"
    accepted.write_text(payload)
    return source, tmp_path / "output", accepted


def test_stages_only_matching_pypi_distributions(accepted_release):
    source, output, accepted = accepted_release
    prepare_pypi_release.stage_release(source, output, accepted_manifest=accepted, version="1.2.3", tag_commit="b" * 40)
    assert {path.name for path in output.iterdir()} == {
        name for name in release_filenames("1.2.3") if name.endswith((".whl", ".tar.gz"))
    }
    assert all(path.read_bytes() == (source / path.name).read_bytes() for path in output.iterdir())


@pytest.mark.parametrize("failure", ["changed", "missing_archive", "wrong_tag", "different_manifest", "preview"])
def test_refuses_unaccepted_or_incomplete_release(accepted_release, failure):
    source, output, accepted = accepted_release
    version, commit = "1.2.3", "b" * 40
    archive = next(source.glob("nanobot-tui-*.zip"))
    if failure == "changed":
        data = archive.read_bytes()
        archive.write_bytes(b"x" * len(data))
    elif failure == "missing_archive":
        archive.unlink()
    elif failure == "wrong_tag":
        commit = "c" * 40
    elif failure == "different_manifest":
        (source / "release-manifest.json").write_bytes(accepted.read_bytes() + b"\n")
    else:
        version = "1.2.3.dev1"
    with pytest.raises(ValueError):
        prepare_pypi_release.stage_release(source, output, accepted_manifest=accepted, version=version, tag_commit=commit)
    assert not output.exists()
