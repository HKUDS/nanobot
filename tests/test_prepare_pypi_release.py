import hashlib

import pytest

from nanobot.releases import ReleaseArtifact, ReleaseManifest, release_filenames
from scripts import prepare_pypi_release


@pytest.fixture
def approved_release(tmp_path, monkeypatch):
    source = tmp_path / "release"
    source.mkdir()
    artifacts = []
    for filename in sorted(release_filenames("1.2.3")):
        data = filename.encode()
        (source / filename).write_bytes(data)
        artifacts.append(ReleaseArtifact(filename=filename, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
    manifest = ReleaseManifest(version="1.2.3", source_commit="a" * 40, candidate_commit="b" * 40,
                               requires_python=">=3.11", artifacts=artifacts)
    (source / "release-manifest.json").write_text(manifest.model_dump_json())
    (source / "release-manifest.json.sigstore.json").write_bytes(b"proof")
    monkeypatch.setattr(prepare_pypi_release, "verify_release_approval", lambda payload, proof: None)
    return source, tmp_path / "output"


def test_stages_only_matching_pypi_distributions(approved_release):
    source, output = approved_release
    prepare_pypi_release.stage_release(source, output, version="1.2.3", tag_commit="b" * 40)
    assert {path.name for path in output.iterdir()} == {
        name for name in release_filenames("1.2.3") if name.endswith((".whl", ".tar.gz"))
    }
    assert all(path.read_bytes() == (source / path.name).read_bytes() for path in output.iterdir())


@pytest.mark.parametrize("failure", ["changed", "missing_archive", "wrong_tag", "invalid_signature", "preview"])
def test_refuses_unapproved_or_incomplete_release(approved_release, monkeypatch, failure):
    source, output = approved_release
    version, commit = "1.2.3", "b" * 40
    archive = next(source.glob("nanobot-tui-*.zip"))
    if failure == "changed":
        data = archive.read_bytes()
        archive.write_bytes(b"x" * len(data))
    elif failure == "missing_archive":
        archive.unlink()
    elif failure == "wrong_tag":
        commit = "c" * 40
    elif failure == "invalid_signature":
        def reject(payload, proof):
            raise ValueError("invalid signature")
        monkeypatch.setattr(prepare_pypi_release, "verify_release_approval", reject)
    else:
        version = "1.2.3.dev1"
    with pytest.raises(ValueError):
        prepare_pypi_release.stage_release(source, output, version=version, tag_commit=commit)
    assert not output.exists()
