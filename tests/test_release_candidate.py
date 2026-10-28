"""Candidate preparation uses real isolated Git repositories, never a live install."""

import subprocess
import tomllib
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from nanobot.releases import ReleaseArtifact, ReleaseManifest, release_filenames
from scripts import release_candidate
from scripts.release_candidate import (
    _candidate_identity,
    _source_payload,
    prepare_preview,
    prepare_stable,
    preview_version,
)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "nanobot").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "nanobot-ai"\nversion = "0.3.5"\nrequires-python = ">=3.11"\n\n'
    )
    (root / "nanobot/__init__.py").write_text(
        'def _resolve_version():\n    return _read_pyproject_version() or "0.3.5"\n\n'
    )
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.test",
        "-c", "commit.gpgsign=false", "commit", "-qm", "source")
    return root, git(root, "rev-parse", "HEAD")


def test_same_source_and_sequence_produce_same_candidate_without_mutating_source(tmp_path, source):
    root, source_commit = source
    before = (root / "pyproject.toml").read_bytes()
    first = prepare_preview(root, tmp_path / "candidate-one", source_commit=source_commit,
                            base="0.3.6", sequence=42)
    second = prepare_preview(root, tmp_path / "candidate-two", source_commit=source_commit,
                             base="0.3.6", sequence=42)
    assert first == second
    assert (root / "pyproject.toml").read_bytes() == before
    assert git(root, "status", "--porcelain") == ""
    assert git(tmp_path / "candidate-one", "rev-parse", "HEAD^") == source_commit
    assert tomllib.loads((tmp_path / "candidate-one/pyproject.toml").read_text())["project"]["version"] == "0.3.6.dev42"
    assert _candidate_identity(tmp_path / "candidate-one", source_commit) == (
        "0.3.6.dev42", ">=3.11", first["candidate_commit"],
    )


def test_dirty_source_is_not_accidentally_included_in_candidate(tmp_path, source):
    root, source_commit = source
    (root / "secret.txt").write_text("local data")
    (root / "nanobot/__init__.py").write_text("uncommitted work")
    prepare_preview(root, tmp_path / "candidate", source_commit=source_commit, base="0.3.6", sequence=1)
    assert not (tmp_path / "candidate/secret.txt").exists()
    assert "0.3.6.dev1" in (tmp_path / "candidate/nanobot/__init__.py").read_text()
    assert (root / "nanobot/__init__.py").read_text() == "uncommitted work"


def test_stable_preparation_preserves_exact_source_and_ignores_local_changes(tmp_path, source):
    root, commit = source
    (root / "nanobot/__init__.py").write_text("uncommitted work")
    target = tmp_path / "stable"
    result = prepare_stable(root, target, source_commit=commit, version="0.3.5")
    assert result == {"version": "0.3.5", "source_commit": commit, "candidate_commit": commit}
    assert git(target, "rev-parse", "HEAD") == commit
    assert git(target, "status", "--porcelain") == ""
    assert _candidate_identity(target, commit) == ("0.3.5", ">=3.11", commit)
    assert (root / "nanobot/__init__.py").read_text() == "uncommitted work"


def test_stable_preparation_refuses_version_mismatch_and_published_identity(tmp_path, source):
    root, commit = source
    target = tmp_path / "stable"
    with pytest.raises(ValueError, match="already declare"):
        prepare_stable(root, target, source_commit=commit, version="0.4.0")
    with pytest.raises(ValueError, match="final version"):
        prepare_stable(root, target, source_commit=commit, version="0.4.0.dev1")
    git(root, "tag", "v0.3.5")
    with pytest.raises(ValueError, match="existing stable tag"):
        prepare_stable(root, target, source_commit=commit, version="0.3.5")
    assert not target.exists()


def test_refuses_existing_output_and_published_stable_base(tmp_path, source):
    root, commit = source
    with pytest.raises(ValueError, match="new directory"):
        prepare_preview(root, root, source_commit=commit, base="0.3.6", sequence=1)
    git(root, "tag", "v0.3.6")
    with pytest.raises(ValueError, match="existing stable tag"):
        prepare_preview(root, tmp_path / "candidate", source_commit=commit, base="0.3.6", sequence=1)
    assert not (tmp_path / "candidate").exists()


def test_arbitrary_ref_or_invalid_version_never_creates_candidate(tmp_path, source):
    root, commit = source
    with pytest.raises(ValueError, match="exact"):
        prepare_preview(root, tmp_path / "candidate", source_commit="main", base="0.3.6", sequence=1)
    with pytest.raises(ValueError):
        prepare_preview(root, tmp_path / "candidate", source_commit=commit, base="0.3.6.dev1", sequence=2)
    assert not (tmp_path / "candidate").exists()
    with pytest.raises(ValueError):
        preview_version("0.3.6", 0)


def test_verification_rejects_changes_after_candidate_commit(tmp_path, source):
    root, commit = source
    target = tmp_path / "candidate"
    prepare_preview(root, target, source_commit=commit, base="0.3.6", sequence=1)
    with (target / "nanobot/__init__.py").open("a") as stream:
        stream.write("# unchecked change\n")
    with pytest.raises(ValueError, match="uncommitted"):
        _candidate_identity(target, commit)
    git(target, "add", ".")
    git(target, "-c", "user.name=Test", "-c", "user.email=test@example.test",
        "-c", "commit.gpgsign=false", "commit", "--amend", "--no-edit", "-q")
    with pytest.raises(ValueError, match="beyond"):
        _candidate_identity(target, commit)


def test_candidate_verifies_bundled_documentation_against_its_tracked_source(source):
    from hatch_build import WebUIBuildHook

    root, _ = source
    with (root / "pyproject.toml").open("a") as stream:
        stream.write('[tool.hatch.build.targets.sdist]\nexclude = ["docs/plans/**"]\n')
    (root / "docs/plans").mkdir(parents=True)
    (root / "docs/README.md").write_text("Checked documentation", encoding="utf-8")
    (root / "docs/plans/private.md").write_text("Not packaged", encoding="utf-8")
    git(root, "add", ".")
    hook = WebUIBuildHook(str(root), {}, None, {}, "", "wheel",
                          SimpleNamespace(display_info=lambda message: None))
    hook.initialize("editable", {})
    reference = "nanobot/skills/nanobot-document/references/README.md"
    names = ["nanobot/__init__.py", "docs/README.md", reference]
    prefix = "nanobot_ai-0.3.5/"
    packaged = {prefix + name: (root / name).read_bytes() for name in names}
    payload = _source_payload(root, packaged, prefix)
    assert payload[reference] == (root / "docs/README.md").read_bytes()

    # Both the shipped reference and the source used to rebuild the sdist must
    # match the reviewed documentation, not merely match each other.
    for name in (reference, "docs/README.md"):
        with pytest.raises(ValueError, match="differs from the candidate"):
            _source_payload(root, {**packaged, prefix + name: b"Unchecked instructions"}, prefix)


def test_retained_source_survives_file_only_artifact_transport(tmp_path, source, monkeypatch):
    root, commit = source
    manifest = ReleaseManifest(
        version="0.3.5", source_commit=commit, candidate_commit=commit,
        requires_python=">=3.11",
        artifacts=[ReleaseArtifact(filename=name, size=123, sha256="c" * 64)
                   for name in sorted(release_filenames("0.3.5"))],
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for artifact in manifest.artifacts:
        (artifacts / artifact.filename).write_bytes(b"structurally verified elsewhere")
    (artifacts / "release-manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    # Exercise actual Git retention and ZIP transport; packaging has independent
    # real-archive coverage and is not the contract under test here.
    monkeypatch.setattr(release_candidate, "verify_candidate", lambda *args, **kwargs: manifest)
    monkeypatch.setattr(release_candidate, "write_install_guide", lambda *args, **kwargs: None)
    retained = tmp_path / "retained"
    release_candidate.retain_candidate(root, artifacts, retained, source_commit=commit)
    with ZipFile(tmp_path / "handoff.zip", "w") as archive:
        for path in retained.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(retained))
    downloaded = tmp_path / "downloaded"
    with ZipFile(tmp_path / "handoff.zip") as archive:
        archive.extractall(downloaded)
    restored = downloaded / "source.git"
    git(restored, "fsck", "--full")
    assert git(restored, "rev-parse", "HEAD") == commit
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", str(restored), str(checkout))
    assert (checkout / "pyproject.toml").read_bytes() == (root / "pyproject.toml").read_bytes()
