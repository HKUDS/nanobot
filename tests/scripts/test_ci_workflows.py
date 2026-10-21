"""Producer/consumer artifact wiring must survive failed-jobs-only retries."""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("platform,step", [("linux", "linux_input"), ("windows", "windows_input")])
def test_native_consumers_receive_immutable_producer_ids(platform, step):
    jobs = workflow("release-candidate.yml")["jobs"]
    key = f"{platform}_artifact_id"
    producer = jobs["candidate"]
    assert producer["outputs"][key] == "${{ steps." + step + ".outputs.artifact-id }}"
    upload = next(item for item in producer["steps"] if item.get("id") == step)
    assert upload["uses"] == "actions/upload-artifact@v4"
    assert jobs["native"]["with"][key] == "${{ needs.candidate.outputs." + key + " }}"
    consumer = workflow("native-acceptance.yml")["jobs"]["native"]
    download = next(item for item in consumer["steps"] if item.get("uses") == "actions/download-artifact@v4")
    assert "inputs." + key in download["with"]["artifact-ids"]
    assert "name" not in download["with"]
    assert download["with"]["merge-multiple"] == "true"


def test_accepted_handoff_uses_the_producer_id_and_requires_native_success():
    jobs = workflow("release-candidate.yml")["jobs"]
    assert jobs["candidate"]["outputs"]["prepared_artifact_id"] == "${{ steps.prepared.outputs.artifact-id }}"
    verified = jobs["verified"]
    assert set(verified["needs"]) == {"candidate", "native"}
    gate = verified["steps"][0]
    assert gate["env"]["NATIVE_RESULT"] == "${{ needs.native.result }}"
    assert gate["run"] == 'test "$BUILD_RESULT" = success && test "$NATIVE_RESULT" = success'
    download = next(item for item in verified["steps"] if item.get("uses") == "actions/download-artifact@v4")
    assert download["with"]["artifact-ids"] == "${{ needs.candidate.outputs.prepared_artifact_id }}"
    assert download["with"]["merge-multiple"] == "true"
    assert "name" not in download["with"]


def test_windows_installer_matrix_has_an_independent_required_job():
    jobs = workflow("ci.yml")["jobs"]
    installer = jobs["windows_installers"]
    assert installer["runs-on"] == "windows-latest"
    assert "native_required" in installer["if"] and "python_required" in installer["if"]
    assert "github.event_name != 'push'" in installer["if"]
    commands = [step.get("run", "") for step in installer["steps"]]
    assert any("tests/test_install_scripts.py" in command and "-n 4" in command for command in commands)
    assert not any("tests/test_install_scripts.py" in step.get("run", "")
                   for step in jobs["windows_process"]["steps"])
    assert "windows_installers" in jobs["required"]["needs"]
