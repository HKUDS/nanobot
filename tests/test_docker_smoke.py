"""Exercise the Docker smoke script's failure and resource-ownership contract."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the Docker smoke script runs under Unix Bash",
)
SCRIPT = Path(__file__).with_name("test_docker.sh")


@pytest.fixture
def docker_boundary(tmp_path):
    executable = tmp_path / "bin" / "docker"
    executable.parent.mkdir()
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['DOCKER_CALLS'], 'a') as log:\n"
        "    log.write(json.dumps(args) + '\\n')\n"
        "stage = args[0]\n"
        "if stage == 'run': stage = args[-1]\n"
        "if stage == 'status':\n"
        "    print('nanobot Status\\nConfig: configured\\nWorkspace: ready\\nModel: test\\n'\n"
        "          'OpenRouter API: unset\\nAnthropic API: unset\\nOpenAI API: unset')\n"
        "if stage == os.environ.get('DOCKER_FAIL_STAGE'): sys.exit(23)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    def run(name, *, fail_stage=""):
        log = tmp_path / f"{name}.jsonl"
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **os.environ,
                "PATH": f"{executable.parent}{os.pathsep}{os.environ.get('PATH', '')}",
                "DOCKER_CALLS": str(log),
                "DOCKER_FAIL_STAGE": fail_stage,
            },
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return result, calls

    return run


def _assert_owned_cleanup(calls):
    image = calls[0][2]
    suffix = image.removeprefix("nanobot-test-")
    assert suffix and suffix != image
    container = f"nanobot-test-run-{suffix}"
    onboarded = f"nanobot-test-onboarded-{suffix}"
    assert calls[-2:] == [["rm", "-f", container], ["rmi", "-f", onboarded, image]]
    for call in calls:
        if call[0] == "run" and call[-1] == "onboard":
            assert call == ["run", "--name", container, image, "onboard"]
        elif call[0] == "commit":
            assert call == ["commit", container, onboarded]
        elif call[0] == "run" and call[-1] == "status":
            assert call == ["run", "--rm", onboarded, "status"]
    return {image, container, onboarded}


@pytest.mark.parametrize("stage", ["build", "onboard", "commit", "status"])
def test_smoke_failure_preserves_exit_and_cleans_only_owned_resources(docker_boundary, stage):
    result, calls = docker_boundary(stage, fail_stage=stage)
    assert result.returncode == 23, result.stdout + result.stderr
    assert "All checks passed" not in result.stdout
    _assert_owned_cleanup(calls)
    if stage == "status":
        # Valid-looking output must never turn a failed status process green.
        assert "nanobot Status" in result.stdout


def test_concurrent_smoke_runs_use_distinct_resources_and_cleanup(docker_boundary):
    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = list(executor.map(docker_boundary, ["first", "second"]))
    resources = []
    for result, calls in runs:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "All checks passed" in result.stdout
        resources.append(_assert_owned_cleanup(calls))
    assert resources[0].isdisjoint(resources[1])
