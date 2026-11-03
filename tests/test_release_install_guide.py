import hashlib
import shlex

import pytest

from nanobot.releases import PLATFORMS, ReleaseArtifact, ReleaseManifest, release_filenames
from scripts import release_candidate
from scripts.release_install_guide import install_command, render_install_guide


@pytest.fixture
def manifest():
    return ReleaseManifest(
        version="0.4.0.dev123", source_commit="a" * 40, candidate_commit="b" * 40,
        requires_python=">=3.11",
        artifacts=[ReleaseArtifact(filename=name, size=123, sha256="c" * 64)
                   for name in sorted(release_filenames("0.4.0.dev123"))],
    )


def test_handoff_commands_bind_every_platform_to_its_exact_release(manifest):
    guide = render_install_guide(manifest)
    assert manifest.source_commit in guide
    assert manifest.candidate_commit in guide
    blocks = [block.split("\n", 1)[1].strip() for block in guide.split("```")[1::2]]
    commands = [shlex.split(block) for block in blocks if block.startswith("python -I -c ")]
    # PowerShell feeds the helper on stdin to avoid legacy native -c quoting.
    commands += [["python", "-I", "-", None, *shlex.split(block.split("'@ | python -I - ", 1)[1])]
                 for block in blocks if block.startswith("@'\n")]
    assert len(commands) == 5 * 3 * 2
    for platform in PLATFORMS.values():
        artifact = next(item for item in manifest.artifacts if item.filename.endswith(f"-{platform}.whl"))
        assert manifest.artifact_url(artifact) in guide
        expected = [artifact.filename, str(artifact.size), artifact.sha256]
        assert sum(command[4:7] == expected for command in commands) == 6
    assert all("--pre" not in command and "--force" not in command for command in commands)


def test_handoff_cannot_generate_install_commands_for_source_or_foreign_artifact(manifest):
    source = next(item for item in manifest.artifacts if item.filename.endswith(".tar.gz"))
    with pytest.raises(ValueError, match="platform wheel"):
        install_command(manifest, source, owner="pip", existing=False)
    wheel = next(item for item in manifest.artifacts if item.filename.endswith(".whl"))
    with pytest.raises(ValueError, match="does not belong"):
        install_command(manifest, wheel.model_copy(update={"sha256": "d" * 64}), owner="uv", existing=True)


@pytest.mark.parametrize("recognized", [True, False], ids=["current-installer", "older-installer"])
def test_verified_handoff_only_offers_bootstrap_supported_by_candidate(tmp_path, monkeypatch, manifest, recognized):
    root, generator, artifacts = (tmp_path / name for name in ("candidate", "generator", "artifacts"))
    artifacts.mkdir()
    for directory in (root, generator):
        (directory / "scripts").mkdir(parents=True)
        for name in ("install.sh", "install.ps1"):
            contents = b"current implementation" if directory == generator or recognized else b"older implementation"
            (directory / "scripts" / name).write_bytes(contents)
    payload = (manifest.model_dump_json(indent=2) + "\n").encode()
    (artifacts / "release-manifest.json").write_bytes(payload)
    monkeypatch.setattr(release_candidate, "ROOT", generator)
    monkeypatch.setattr(release_candidate, "verify_candidate", lambda *args, **kwargs: manifest)
    guide = tmp_path / "install.md"
    release_candidate.write_install_guide(root, artifacts, guide, source_commit=manifest.source_commit)
    text = guide.read_text()
    assert ("## Automatic platform selection" in text) == recognized
    if recognized:
        digest = hashlib.sha256(payload).hexdigest()
        assert f"--manifest-sha256 '{digest}'" in text
        assert f"-ManifestSha256 '{digest}'" in text
        for name in ("install.sh", "install.ps1"):
            assert f"/{manifest.candidate_commit}/scripts/{name}" in text
        assert "<summary>Manual platform and manager commands</summary>" in text
    assert manifest.artifacts[0].sha256 in text
