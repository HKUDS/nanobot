"""Prepare and verify an exact release candidate without publishing anything.

Preparation creates a separate checkout. Verification writes a manifest only after
all five wheels, the sdist and licensed TUI archives pass their structural checks.
Native execution, CI approval and public-download checks remain separate gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
from email.parser import BytesParser
from fnmatch import fnmatchcase
from pathlib import Path

from packaging.version import Version

from nanobot.releases import (
    PLATFORMS,
    ReleaseArtifact,
    ReleaseManifest,
    release_filenames,
    release_version,
)
from scripts.build_tui_wheels import build_wheel, release_bundle, source_files, wheel_files
from scripts.release_install_guide import render_install_guide

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILES = ("pyproject.toml", "nanobot/__init__.py")


def _git(root: Path, *args: str, env: dict[str, str] | None = None, trim: bool = True) -> str:
    output = subprocess.run(
        ["git", *args], cwd=root, env=env, check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=120,
    ).stdout
    return output.strip() if trim else output


def _commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Use an exact, full source commit SHA, not a branch or tag")
    return value


def preview_version(base: str, sequence: int) -> str:
    release_version(base)
    parsed = Version(base)
    if parsed.is_prerelease or parsed.is_postrelease or sequence < 1:
        raise ValueError("Use a stable base and a positive preview sequence")
    return f"{base}.dev{sequence}"


def _version_changes(pyproject: str, init: str, version: str) -> dict[str, str]:
    current = tomllib.loads(pyproject)["project"]["version"]
    updated_project, project_count = re.subn(
        rf'(?m)^version = "{re.escape(current)}"$', f'version = "{version}"', pyproject,
    )
    updated_init, init_count = re.subn(
        rf'return _read_pyproject_version\(\) or "{re.escape(current)}"',
        f'return _read_pyproject_version() or "{version}"', init,
    )
    if project_count != 1 or init_count != 1:
        raise ValueError("Package and fallback version declarations need maintainer review")
    return dict(zip(VERSION_FILES, (updated_project, updated_init), strict=True))


def prepare_preview(root: Path, output: Path, *, source_commit: str, base: str, sequence: int) -> dict[str, str]:
    source_commit = _commit(source_commit)
    version = preview_version(base, sequence)
    root, output = root.resolve(), output.resolve()
    if output.exists() or output == root or root in output.parents:
        raise ValueError("Candidate output must be a new directory outside the source checkout")
    if _git(root, "rev-parse", f"{source_commit}^{{commit}}") != source_commit:
        raise ValueError("Source commit is not available in this repository")
    original = {name: _git(root, "show", f"{source_commit}:{name}", trim=False) for name in VERSION_FILES}
    current = Version(tomllib.loads(original["pyproject.toml"])["project"]["version"])
    if Version(base).release < current.release or _git(root, "tag", "--list", f"v{base}"):
        raise ValueError("Preview base must not precede the source or reuse an existing stable tag")
    changes = _version_changes(original["pyproject.toml"], original["nanobot/__init__.py"], version)
    _git(root, "clone", "--shared", "--no-checkout", "-c", "core.autocrlf=false", str(root), str(output))
    hooks = output / ".git" / "candidate-hooks"
    hooks.mkdir()
    _git(output, "-c", f"core.hooksPath={hooks}", "checkout", "--detach", source_commit)
    for name, content in changes.items():
        (output / name).write_text(content, encoding="utf-8", newline="\n")
    _git(output, "add", "--", *VERSION_FILES)
    timestamp = _git(root, "show", "-s", "--format=%cI", source_commit)
    env = dict(os.environ)
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"] = "nanobot release"
        env[f"GIT_{role}_EMAIL"] = "nanobot-release@users.noreply.github.com"
        env[f"GIT_{role}_DATE"] = timestamp
    _git(output, "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={hooks}",
         "commit", "-m", f"Prepare {version} from {source_commit}", env=env)
    return {"version": version, "source_commit": source_commit,
            "candidate_commit": _git(output, "rev-parse", "HEAD")}


def prepare_stable(root: Path, output: Path, *, source_commit: str, version: str) -> dict[str, str]:
    """Copy an already versioned final commit without relabelling Preview bytes."""
    source_commit = _commit(source_commit)
    release_version(version)
    parsed = Version(version)
    if parsed.is_prerelease or parsed.is_postrelease:
        raise ValueError("Stable preparation requires a final version")
    root, output = root.resolve(), output.resolve()
    if output.exists() or output == root or root in output.parents:
        raise ValueError("Candidate output must be a new directory outside the source checkout")
    if _git(root, "rev-parse", f"{source_commit}^{{commit}}") != source_commit:
        raise ValueError("Source commit is not available in this repository")
    original = {name: _git(root, "show", f"{source_commit}:{name}", trim=False) for name in VERSION_FILES}
    if tomllib.loads(original["pyproject.toml"])["project"]["version"] != version:
        raise ValueError("Stable source must already declare the requested final version")
    if _version_changes(original["pyproject.toml"], original["nanobot/__init__.py"], version) != original:
        raise ValueError("Stable version declarations need maintainer review")
    if _git(root, "tag", "--list", f"v{version}"):
        raise ValueError("Stable preparation must not reuse an existing stable tag")
    _git(root, "clone", "--shared", "--no-checkout", "-c", "core.autocrlf=false", str(root), str(output))
    hooks = output / ".git" / "candidate-hooks"
    hooks.mkdir()
    _git(output, "-c", f"core.hooksPath={hooks}", "checkout", "--detach", source_commit)
    return {"version": version, "source_commit": source_commit, "candidate_commit": source_commit}


def _candidate_identity(root: Path, source_commit: str) -> tuple[str, str, str]:
    _commit(source_commit)
    candidate_commit = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Candidate has uncommitted tracked changes")
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version, requires_python = release_version(metadata["version"]), metadata["requires-python"]
    if source_commit != candidate_commit:
        if _git(root, "rev-parse", "HEAD^") != source_commit:
            raise ValueError("Candidate must be a direct child of its exact source commit")
        original = {name: _git(root, "show", f"{source_commit}:{name}", trim=False) for name in VERSION_FILES}
        expected = _version_changes(original["pyproject.toml"], original["nanobot/__init__.py"], version)
        changed = set(_git(root, "diff", "--name-only", source_commit, "HEAD").splitlines())
        if changed != set(VERSION_FILES) or any(
            (root / name).read_text(encoding="utf-8") != text for name, text in expected.items()
        ):
            raise ValueError("Candidate contains changes beyond the two version declarations")
    return version, requires_python, candidate_commit


def _source_payload(root: Path, source: dict[str, bytes], prefix: str) -> dict[str, bytes]:
    """Bind shipped application files to the clean candidate, not its commit label."""
    tracked = set(_git(root, "ls-files", "-z", trim=False).split("\0")) - {""}
    build = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["hatch"]["build"]
    exclusions = [*build.get("exclude", []), *build["targets"]["sdist"].get("exclude", [])]
    expected = {name: name for name in tracked if name.startswith("nanobot/")
                and not any(fnmatchcase(name, pattern) for pattern in exclusions)}
    for name in tracked:
        if (name.startswith("docs/") and name.endswith(".md")
                and not any(fnmatchcase(name, pattern) for pattern in exclusions)):
            if source.get(prefix + name) != (root / name).read_bytes():
                raise ValueError(f"Source documentation differs from the candidate: {name}")
            expected["nanobot/skills/nanobot-document/references/" + name.removeprefix("docs/")] = name
    payload = {name.removeprefix(prefix): data for name, data in source.items()
               if name.startswith(prefix + "nanobot/")}
    generated = {name for name in payload if name == "nanobot/_build_commit.txt"
                 or name.startswith("nanobot/web/dist/")}
    if payload.keys() - generated != expected.keys():
        raise ValueError("Source application payload has missing or unexpected files")
    for name, data in payload.items():
        if name in generated:
            continue
        if data != (root / expected[name]).read_bytes():
            raise ValueError(f"Source application payload differs from the candidate: {name}")
    return payload


def verify_candidate(root: Path, artifacts: Path, *, source_commit: str) -> ReleaseManifest:
    version, requires_python, candidate_commit = _candidate_identity(root, source_commit)
    expected = release_filenames(version)
    present = {path.name for path in artifacts.iterdir()}
    if present - {"release-manifest.json"} != expected:
        raise ValueError("Artifact directory must contain exactly the complete release upload set")
    for name in expected:
        if (artifacts / name).is_symlink() or not (artifacts / name).is_file():
            raise ValueError(f"Release artifact must be a regular file: {name}")
    commit_bytes = (candidate_commit + "\n").encode()
    source = source_files((artifacts / f"nanobot_ai-{version}.tar.gz").read_bytes())
    prefix = f"nanobot_ai-{version}/"
    source_metadata = BytesParser().parsebytes(source[f"{prefix}PKG-INFO"])
    if (source_metadata["Name"], source_metadata["Version"], source_metadata["Requires-Python"]) != (
        "nanobot-ai", version, requires_python,
    ):
        raise ValueError("Source distribution metadata differs from the candidate")
    for name in VERSION_FILES:
        if source[f"{prefix}{name}"] != (root / name).read_bytes():
            raise ValueError(f"Source distribution differs from candidate: {name}")
    if (source.get(f"{prefix}nanobot/_build_commit.txt") != commit_bytes
            or not source.get(f"{prefix}nanobot/web/dist/index.html")):
        raise ValueError("Source distribution must contain the candidate commit and built WebUI")
    payload = _source_payload(root, source, prefix)
    for target, platform in PLATFORMS.items():
        wheel = artifacts / f"nanobot_ai-{version}-py3-none-{platform}.whl"
        files, modes, info = wheel_files(wheel, version, platform=platform)
        package_metadata = BytesParser().parsebytes(files[f"{info}/METADATA"])
        if package_metadata["Requires-Python"] != requires_python:
            raise ValueError("Wheel Python requirement differs from the candidate")
        if files.get("nanobot/_build_commit.txt") != commit_bytes:
            raise ValueError("Wheel build commit differs from the candidate")
        if not files.get("nanobot/web/dist/index.html"):
            raise ValueError("Wheel is missing its compiled WebUI")
        application = {name: data for name, data in files.items()
                       if name.startswith("nanobot/") and not name.startswith("nanobot/tui/bin/")}
        if application != payload:
            raise ValueError(f"Wheel application payload differs from the source distribution: {target}")
        bundle = release_bundle(artifacts, target, root=root)
        embedded = {name.removeprefix("nanobot/tui/bin/"): data for name, data in files.items()
                    if name.startswith("nanobot/tui/bin/")}
        if embedded != bundle:
            raise ValueError("Wheel and fallback TUI archive differ")
        asset = f"nanobot-tui-{target}" + (".exe" if target == "win32-x64" else "")
        mode = modes[f"nanobot/tui/bin/{asset}"]
        if not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o755:
            raise ValueError("Installed TUI must retain executable permissions")
    records: list[ReleaseArtifact] = []
    for name in sorted(expected):
        path = artifacts / name
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        records.append(ReleaseArtifact(filename=name, size=path.stat().st_size, sha256=digest))
    return ReleaseManifest(
        version=version, source_commit=source_commit, candidate_commit=candidate_commit,
        requires_python=requires_python,
        artifacts=records,
    )


def _write_candidate_text(payload: str, output: Path) -> None:
    if output.exists():
        if output.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"Existing {output.name} differs; do not overwrite candidate evidence")
    with tempfile.TemporaryDirectory(prefix=".candidate-report-", dir=output.parent) as temporary:
        candidate = Path(temporary) / "report"
        candidate.write_text(payload, encoding="utf-8")
        output.hardlink_to(candidate)


def write_manifest(manifest: ReleaseManifest, output: Path) -> None:
    _write_candidate_text(manifest.model_dump_json(indent=2) + "\n", output)


def write_install_guide(root: Path, artifacts: Path, output: Path, *, source_commit: str) -> None:
    """Reverify the immutable upload set before emitting a manual installation handoff."""
    if output.resolve().is_relative_to(artifacts.resolve()):
        raise ValueError("Install guide must be outside the immutable artifact directory")
    payload = (artifacts / "release-manifest.json").read_bytes()
    recorded = ReleaseManifest.model_validate_json(payload)
    manifest = verify_candidate(root, artifacts, source_commit=source_commit)
    if recorded != manifest:
        raise ValueError("Candidate differs from its recorded release manifest")
    # Older retained candidates may not have the bootstrap options. Only link a
    # candidate's scripts when they are the known implementation shipped here.
    bootstrap = all(
        (root / "scripts" / name).is_file()
        and (root / "scripts" / name).read_bytes() == (ROOT / "scripts" / name).read_bytes()
        for name in ("install.sh", "install.ps1")
    )
    digest = hashlib.sha256(payload).hexdigest() if bootstrap else None
    _write_candidate_text(render_install_guide(manifest, manifest_sha256=digest), output)


def assemble_candidate(root: Path, output: Path, *, wheel: Path, sdist: Path,
                       tui_dir: Path, source_commit: str) -> ReleaseManifest:
    """Assemble in a fresh directory; failed output is never given a manifest."""
    version, _, _ = _candidate_identity(root, source_commit)
    if sdist.name != f"nanobot_ai-{version}.tar.gz":
        raise ValueError("Source distribution filename differs from the candidate")
    output.mkdir(parents=True, exist_ok=False)
    for target in PLATFORMS:
        build_wheel(wheel, tui_dir, output, target, root=root)
    for name in sorted(release_filenames(version)):
        if not name.endswith(".whl"):
            shutil.copyfile(sdist if name == sdist.name else tui_dir / name, output / name)
    manifest = verify_candidate(root, output, source_commit=source_commit)
    write_manifest(manifest, output / "release-manifest.json")
    return manifest


def retain_candidate(root: Path, artifacts: Path, output: Path, *, source_commit: str) -> None:
    """Preserve checked bytes and their source, without publishing or rebuilding.

    A successful handoff has a final handoff.json. Partial copies are not accepted
    release inputs. The self-contained shallow repository preserves the candidate
    and its source parent, not unrelated history, untracked files or credentials.
    """
    root, artifacts, output = root.resolve(), artifacts.resolve(), output.resolve()
    if output.is_relative_to(root) or output.is_relative_to(artifacts):
        raise ValueError("Retained handoff must be outside the checkout and artifact directory")
    recorded = (artifacts / "release-manifest.json").read_bytes()
    manifest = verify_candidate(root, artifacts, source_commit=source_commit)
    if ReleaseManifest.model_validate_json(recorded) != manifest:
        raise ValueError("Candidate differs from its recorded release manifest")
    output.mkdir(parents=True, exist_ok=False)
    retained = output / "artifacts"
    retained.mkdir()
    for name in sorted(release_filenames(manifest.version) | {"release-manifest.json"}):
        shutil.copyfile(artifacts / name, retained / name)
    if ((retained / "release-manifest.json").read_bytes() != recorded
            or verify_candidate(root, retained, source_commit=source_commit) != manifest):
        raise ValueError("Retained artifacts differ from the reviewed candidate")
    source = output / "source.git"
    with tempfile.TemporaryDirectory(prefix=".candidate-template-", dir=output) as template:
        # File transport copies real objects rather than borrowing alternates.
        # Two commits retain the exact version-only candidate relationship.
        _git(root, "-c", f"init.templateDir={template}", "clone", "--bare", "--depth", "2",
             "--single-branch", "--no-tags", root.as_uri(), str(source))
    (source / "config").write_text("[core]\nrepositoryformatversion = 0\nbare = true\n", encoding="utf-8")
    # Artifact transport keeps files, not empty directories. A bare clone can
    # have only packed refs; retain a loose ref so the downloaded Git tree works.
    _git(source, "update-ref", "refs/retained/candidate", manifest.candidate_commit)
    _git(source, "fsck", "--full")
    if _git(source, "rev-parse", "HEAD") != manifest.candidate_commit:
        raise ValueError("Retained source differs from the candidate")
    write_install_guide(root, retained, output / "install.md", source_commit=source_commit)
    _write_candidate_text(json.dumps({
        "version": manifest.version, "source_commit": source_commit,
        "candidate_commit": manifest.candidate_commit,
        "manifest_sha256": hashlib.sha256(recorded).hexdigest(),
        "source_depth": 2,
        "published": False,
    }, indent=2) + "\n", output / "handoff.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source-commit", required=True)
    prepare.add_argument("--base", required=True)
    prepare.add_argument("--sequence", type=int, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    stable = commands.add_parser("prepare-stable")
    stable.add_argument("--source-commit", required=True)
    stable.add_argument("--version", required=True)
    stable.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--source-commit", required=True)
    verify.add_argument("--artifacts", type=Path, required=True)
    instructions = commands.add_parser("instructions")
    instructions.add_argument("--source-commit", required=True)
    instructions.add_argument("--artifacts", type=Path, required=True)
    instructions.add_argument("--output", type=Path, required=True)
    retain = commands.add_parser("retain")
    retain.add_argument("--source-commit", required=True)
    retain.add_argument("--artifacts", type=Path, required=True)
    retain.add_argument("--output", type=Path, required=True)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--source-commit", required=True)
    assemble.add_argument("--wheel", type=Path, required=True)
    assemble.add_argument("--sdist", type=Path, required=True)
    assemble.add_argument("--tui-dir", type=Path, required=True)
    assemble.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare_preview(args.root, args.output, source_commit=args.source_commit,
                                         base=args.base, sequence=args.sequence)))
    elif args.command == "prepare-stable":
        print(json.dumps(prepare_stable(args.root, args.output, source_commit=args.source_commit,
                                       version=args.version)))
    elif args.command == "verify":
        manifest = verify_candidate(args.root, args.artifacts, source_commit=args.source_commit)
        write_manifest(manifest, args.artifacts / "release-manifest.json")
        print(manifest.model_dump_json(indent=2))
    elif args.command == "instructions":
        write_install_guide(args.root, args.artifacts, args.output, source_commit=args.source_commit)
        print(f"Candidate install handoff: {args.output}")
    elif args.command == "retain":
        retain_candidate(args.root, args.artifacts, args.output, source_commit=args.source_commit)
        print(f"Retained exact candidate (not published): {args.output}")
    else:
        manifest = assemble_candidate(args.root, args.output, wheel=args.wheel, sdist=args.sdist,
                                      tui_dir=args.tui_dir, source_commit=args.source_commit)
        print(manifest.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
