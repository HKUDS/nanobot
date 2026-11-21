import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"
COMMIT = "a" * 40


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.fixture
def shell_env(tmp_path):
    if os.name == "nt":
        pytest.skip("Release workflows run their Bash steps on Ubuntu")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if args[:2] == ["release", "view"]:
    print(os.environ["PUBLIC_RELEASE"])
elif args[:2] == ["release", "download"]:
    path = Path(args[args.index("--dir") + 1])
    path.mkdir()
    (path / "release-manifest.json").write_text("public manifest")
elif args[0] == "api" and "repos/HKUDS/nanobot/actions/workflows/release-candidate.yml/runs" in args:
    print(os.environ["CANDIDATE_RUNS"])
elif args[0] == "api" and args[1].startswith("repos/HKUDS/nanobot/actions/runs/"):
    parts = args[1].split("/")
    print("true" if f"{parts[5]}/{parts[7]}" in os.environ["ACCEPTED_ATTEMPTS"].split() else "false")
elif args[:2] == ["run", "download"]:
    run = args[2]
    if run == os.environ.get("EXPIRED_RUN"):
        sys.exit(1)
    manifest = Path(args[args.index("--dir") + 1]) / "release-artifacts/release-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("public manifest" if run == os.environ["MATCHING_RUN"] else "other manifest")
else:
    sys.exit(2)
"""
    )
    gh.chmod(0o755)
    git = bin_dir / "git"
    git.write_text(f"#!/bin/bash\n[[ $1 != rev-parse ]] || echo {COMMIT}\n")
    git.chmod(0o755)
    python = bin_dir / "python"
    python.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$RUNNER_TEMP/staged"\n')
    python.chmod(0o755)
    return {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "GITHUB_RUN_ATTEMPT": "1", "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_EVENT_NAME": "workflow_run", "UPSTREAM_TAG": "v1.2.3", "UPSTREAM_SHA": COMMIT,
        "VERSION_INPUT": "", "DESTINATION_INPUT": "",
        "PUBLIC_RELEASE": '{"tagName":"v1.2.3","isDraft":false,"isPrerelease":false}',
        "CANDIDATE_RUNS": "101\t7\t1\n102\t8\t2", "ACCEPTED_ATTEMPTS": "102/2", "MATCHING_RUN": "102",
    }


def run(step, env):
    return subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True)


def release_step():
    return next(step for step in workflow("publish-pypi.yml")["jobs"]["verify"]["steps"]
                if step.get("id") == "release")


def publish_gate():
    return workflow("publish-pypi.yml")["jobs"]["publish"]["steps"][0]


def test_publishing_a_stable_release_stages_the_accepted_files(shell_env):
    trigger = workflow("trigger-pypi.yml")
    assert trigger["on"]["release"]["types"] == ["published"]
    job = trigger["jobs"]["release"]
    assert "!github.event.release.prerelease" in job["if"]
    assert trigger["permissions"] == {}
    assert run(job["steps"][0], {**shell_env, "RELEASE_TAG": "v1.2.3"}).returncode == 0
    publisher = workflow("publish-pypi.yml")
    assert publisher["on"]["workflow_run"]["workflows"] == ["Validate published release for PyPI"]
    guard = publisher["jobs"]["verify"]["if"]
    assert all(value in guard for value in ("refs/heads/main", "conclusion == 'success'", "event == 'release'",
                                            "head_repository.full_name", ".github/workflows/trigger-pypi.yml"))
    result = run(release_step(), shell_env)
    assert result.returncode == 0, result.stderr
    assert set(Path(shell_env["GITHUB_OUTPUT"]).read_text().splitlines()) == {
        "release_version=1.2.3", "destination=pypi"
    }
    staged = (Path(shell_env["RUNNER_TEMP"]) / "staged").read_text()
    assert "candidate-report-8-2/release-artifacts/release-manifest.json" in staged
    assert run(publish_gate(), shell_env).returncode == 0


@pytest.mark.parametrize("tag", ["v1.2.3-rc1", "1.2.3"])
def test_invalid_release_tag_fails_before_publisher(shell_env, tag):
    step = workflow("trigger-pypi.yml")["jobs"]["release"]["steps"][0]
    assert run(step, {**shell_env, "RELEASE_TAG": tag}).returncode != 0


@pytest.mark.parametrize("change", [
    {"UPSTREAM_SHA": "b" * 40},
    {"PUBLIC_RELEASE": '{"tagName":"v1.2.3","isDraft":true,"isPrerelease":false}'},
    {"ACCEPTED_ATTEMPTS": "101/1 102/1"},
    {"EXPIRED_RUN": "102"},
])
def test_changed_release_or_unaccepted_manifest_never_stages(shell_env, change):
    assert run(release_step(), {**shell_env, **change}).returncode != 0
    assert not (Path(shell_env["RUNNER_TEMP"]) / "staged").exists()


def test_manual_testpypi_checks_the_same_public_release(shell_env):
    env = {**shell_env, "GITHUB_EVENT_NAME": "workflow_dispatch", "VERSION_INPUT": "1.2.3",
           "DESTINATION_INPUT": "testpypi", "ACCEPTED_ATTEMPTS": "101/1 102/2"}
    result = run(release_step(), env)
    assert result.returncode == 0, result.stderr
    assert "destination=testpypi" in Path(shell_env["GITHUB_OUTPUT"]).read_text()
    assert "candidate-report-8-2" in (Path(shell_env["RUNNER_TEMP"]) / "staged").read_text()


def test_rerun_cannot_reuse_staged_files(shell_env):
    result = run(publish_gate(), {**shell_env, "GITHUB_RUN_ATTEMPT": "2"})
    assert result.returncode != 0 and "start a new workflow run" in result.stderr
