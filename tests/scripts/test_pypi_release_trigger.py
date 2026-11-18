import json
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
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['release', 'view']:\n"
        "    print(json.dumps({'tagName': 'v1.2.3', 'isDraft': False, 'isPrerelease': False}))\n"
        "elif args[:2] == ['release', 'download']:\n"
        "    pass\n"
        "elif args[0] == 'api':\n"
        "    print(open(os.environ['MOCK_APPROVALS']).read())\n"
        "else:\n"
        "    sys.exit(2)\n"
    )
    gh.chmod(0o755)
    git = bin_dir / "git"
    git.write_text(f"#!/bin/bash\n[[ $1 != rev-parse ]] || echo {COMMIT}\n")
    git.chmod(0o755)
    python = bin_dir / "python"
    python.write_text("#!/bin/bash\nexit 0\n")
    python.chmod(0o755)
    return {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(tmp_path), "GH_TOKEN": "test",
        "GITHUB_RUN_ID": "987", "GITHUB_RUN_ATTEMPT": "1", "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "MOCK_APPROVALS": str(tmp_path / "approvals.json"),
        "GITHUB_EVENT_NAME": "workflow_run", "UPSTREAM_TAG": "v1.2.3", "UPSTREAM_SHA": COMMIT,
        "UPSTREAM_ACTOR": "publisher", "VERSION_INPUT": "", "DESTINATION_INPUT": "",
        "GITHUB_ACTOR": "github-actions[bot]",
    }


def run(step, env):
    return subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True)


def release_step():
    return next(step for step in workflow("publish-pypi.yml")["jobs"]["verify"]["steps"]
                if step.get("id") == "release")


def publish_gate():
    return workflow("publish-pypi.yml")["jobs"]["publish"]["steps"][0]


def test_only_stable_release_completion_can_start_the_main_publisher(shell_env):
    trigger = workflow("trigger-pypi.yml")
    assert trigger["on"]["release"]["types"] == ["released"]
    job = trigger["jobs"]["release"]
    assert "!github.event.release.prerelease" in job["if"]
    assert trigger["permissions"] == {}
    result = run(job["steps"][0], {**shell_env, "RELEASE_TAG": "v1.2.3"})
    assert result.returncode == 0, result.stderr
    publisher = workflow("publish-pypi.yml")
    assert publisher["on"]["workflow_run"]["workflows"] == ["Validate published release for PyPI"]
    assert publisher["on"]["workflow_run"]["types"] == ["completed"]
    assert "github.event.workflow_run.head_branch" in publisher["concurrency"]["group"]
    assert "format('v{0}', inputs.version)" in publisher["concurrency"]["group"]
    guard = publisher["jobs"]["verify"]["if"]
    assert all(value in guard for value in ("refs/heads/main", "conclusion == 'success'", "event == 'release'",
                                            ".github/workflows/trigger-pypi.yml"))


@pytest.mark.parametrize("tag", ["v1.2.3-rc1", "v1.2.3;echo BAD", "1.2.3"])
def test_invalid_release_tag_fails_before_publisher(shell_env, tag):
    step = workflow("trigger-pypi.yml")["jobs"]["release"]["steps"][0]
    assert run(step, {**shell_env, "RELEASE_TAG": tag}).returncode != 0


def test_release_origin_preserves_tag_and_original_actor(shell_env):
    result = run(release_step(), shell_env)
    assert result.returncode == 0, result.stderr
    assert set(Path(shell_env["GITHUB_OUTPUT"]).read_text().splitlines()) == {
        "release_actor=publisher", "release_version=1.2.3", "destination=pypi"
    }


def test_simulated_release_reaches_independently_approved_publisher(shell_env):
    trigger = workflow("trigger-pypi.yml")["jobs"]["release"]["steps"][0]
    assert run(trigger, {**shell_env, "RELEASE_TAG": "v1.2.3"}).returncode == 0
    assert run(release_step(), shell_env).returncode == 0
    outputs = dict(line.split("=", 1) for line in Path(shell_env["GITHUB_OUTPUT"]).read_text().splitlines())
    assert outputs["release_version"] == "1.2.3" and outputs["destination"] == "pypi"
    Path(shell_env["MOCK_APPROVALS"]).write_text(json.dumps([
        {"state": "approved", "user": {"login": "reviewer"}, "environments": [{"name": "pypi"}]}
    ]))
    assert run(publish_gate(), {**shell_env, "DESTINATION": "pypi",
                                "RELEASE_ACTOR": outputs["release_actor"]}).returncode == 0


@pytest.mark.parametrize("change", [{"UPSTREAM_SHA": "b" * 40}, {"UPSTREAM_TAG": "v1.2.3-rc1"},
                                     {"UPSTREAM_ACTOR": "bad\nactor"}, {"UPSTREAM_ACTOR": "publisher[bot]"}])
def test_release_origin_rejects_changed_tag_or_invalid_actor(shell_env, change):
    assert run(release_step(), {**shell_env, **change}).returncode != 0


def test_manual_testpypi_run_uses_its_real_actor_not_upstream_input(shell_env):
    result = run(release_step(), {**shell_env, "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_ACTOR": "maintainer",
                                  "VERSION_INPUT": "1.2.3", "DESTINATION_INPUT": "testpypi"})
    assert result.returncode == 0, result.stderr
    assert set(Path(shell_env["GITHUB_OUTPUT"]).read_text().splitlines()) == {
        "release_actor=maintainer", "release_version=1.2.3", "destination=testpypi"
    }


@pytest.mark.parametrize(("reviewer", "environment", "state", "allowed"), [
    ("reviewer", "pypi", "approved", True),
    ("publisher", "pypi", "approved", False),
    ("PUBLISHER", "pypi", "approved", False),
    ("reviewer", "testpypi", "approved", False),
    ("reviewer", "pypi", "rejected", False),
])
def test_production_approval_must_be_independent(shell_env, reviewer, environment, state, allowed):
    payload = [{"state": state, "user": {"login": reviewer}, "environments": [{"name": environment}]}]
    Path(shell_env["MOCK_APPROVALS"]).write_text(json.dumps(payload))
    result = run(publish_gate(), {**shell_env, "DESTINATION": "pypi", "RELEASE_ACTOR": "publisher"})
    assert (result.returncode == 0) == allowed


@pytest.mark.parametrize("destination", ["pypi", "testpypi"])
def test_rerun_cannot_use_prior_approval_or_staged_files(shell_env, destination):
    if destination == "pypi":
        Path(shell_env["MOCK_APPROVALS"]).write_text(json.dumps([
            {"state": "approved", "user": {"login": "reviewer"}, "environments": [{"name": "pypi"}]}
        ]))
    env = {**shell_env, "DESTINATION": destination, "RELEASE_ACTOR": "publisher"}
    assert run(publish_gate(), env).returncode == 0
    result = run(publish_gate(), {**env, "GITHUB_RUN_ATTEMPT": "2"})
    assert result.returncode != 0 and "start a new workflow run" in result.stderr
