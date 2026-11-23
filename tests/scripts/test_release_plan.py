import json
import sys

import pytest
import yaml

from scripts import release_plan
from scripts.release_plan import WorkflowRun, daily_needed, git, plan, previous_tag, render_notes

SOURCE = "a" * 40


def run(*, number=1, attempt=1, status="completed", conclusion="success", source=SOURCE,
        event="push", title="CI"):
    return WorkflowRun(head_sha=source, display_title=title, event=event, run_number=number,
                       run_attempt=attempt, status=status, conclusion=conclusion)


def test_daily_preparation_requires_latest_exact_source_ci():
    assert daily_needed(SOURCE, "0.4.1", [run()], [])
    for ci in ([], [run(source="b" * 40)], [run(event="pull_request")],
               [run(), run(number=2, conclusion="failure")],
               [run(), run(attempt=2, status="in_progress", conclusion=None)]):
        with pytest.raises(ValueError, match="latest push CI"):
            daily_needed(SOURCE, "0.4.1", ci, [])


def test_daily_preparation_skips_same_base_and_source_but_retries_failed_candidates():
    previous = run(event="schedule", title=f"Candidate preview 0.4.1 from {SOURCE}")
    assert not daily_needed(SOURCE, "0.4.1", [run()], [previous])
    assert daily_needed(SOURCE, "0.5.0", [run()], [previous])
    for candidate in (previous.model_copy(update={"conclusion": "failure"}),
                      previous.model_copy(update={"display_title": "Disabled daily candidate"}),
                      previous.model_copy(update={"display_title": f"Candidate stable 0.4.1 from {SOURCE}"})):
        assert daily_needed(SOURCE, "0.4.1", [run()], [candidate])


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "commit", "--allow-empty", "-qm", "Initial release")
    git(tmp_path, "tag", "v0.4.0")
    git(tmp_path, "commit", "--allow-empty", "-qm", "Fix delivery")
    source = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "checkout", "--detach", "-q")
    git(tmp_path, "commit", "--allow-empty", "-qm", "Prepare preview")
    git(tmp_path, "tag", "v0.4.1.dev1")
    git(tmp_path, "checkout", "--detach", "-q", source)
    git(tmp_path, "commit", "--allow-empty", "-qm", "Fix startup")
    source = git(tmp_path, "rev-parse", "HEAD")
    return tmp_path, source


def test_notes_follow_release_line_and_skip_preview_version_commits(history):
    root, source = history
    stable = render_notes(root, source=source, version="0.4.1")
    preview = render_notes(root, source=source, version="0.4.1.dev2")
    assert "Changes since v0.4.0" in stable
    assert "Fix delivery" in stable and "Fix startup" in stable
    assert "Changes since v0.4.1.dev1" in preview
    assert "Fix startup" in preview and "Fix delivery" not in preview
    assert "Prepare preview" not in preview
    # A newer tag from another development line must not select unrelated history.
    git(root, "checkout", "--detach", "-q", "v0.4.0")
    git(root, "commit", "--allow-empty", "-qm", "Other line")
    git(root, "tag", "v0.4.2")
    assert previous_tag(root, source, "0.5.0") == "v0.4.0"


def test_manual_stable_and_preview_keep_existing_channel_and_sequence(history, monkeypatch):
    root, source = history
    def no_network(*args):
        pytest.fail("Manual preparation must not depend on the daily scheduler API")
    monkeypatch.setattr(release_plan, "workflow_runs", no_network)
    stable = plan(root, source=source, base="0.4.1", channel="stable", sequence=42, scheduled=False)
    preview = plan(root, source=source, base="0.4.1", channel="preview", sequence=42, scheduled=False)
    assert stable == {"prepare": "true", "source_commit": source, "base": "0.4.1",
                      "channel": "stable", "version": "0.4.1"}
    assert preview["version"] == "0.4.1.dev42"
    with pytest.raises(ValueError, match="already tagged"):
        plan(root, source=source, base="0.4.0", channel="preview", sequence=42, scheduled=False)
    with pytest.raises(ValueError, match="already tagged"):
        plan(root, source=source, base="0.4.1", channel="preview", sequence=1, scheduled=False)


def test_cli_writes_only_local_notes_and_identity(history, tmp_path, monkeypatch):
    root, source = history
    monkeypatch.setattr(release_plan, "ROOT", root)
    output = tmp_path / "notes"
    github_output = tmp_path / "outputs"
    before = git(root, "show-ref")
    monkeypatch.setattr(sys, "argv", ["release_plan", "--source-commit", source, "--base", "0.4.1",
                                     "--channel", "stable", "--sequence", "7", "--output", str(output),
                                     "--github-output", str(github_output)])
    release_plan.main()
    assert "Fix startup" in (output / "release-notes.md").read_text()
    assert json.loads((output / "plan.json").read_text())["version"] == "0.4.1"
    assert "prepare=true\n" in github_output.read_text()
    assert git(root, "show-ref") == before


def test_unchanged_daily_plan_does_not_create_a_candidate_handoff(history, tmp_path, monkeypatch):
    root, source = history
    monkeypatch.setattr(release_plan, "ROOT", root)
    previous = run(source=source, event="schedule", title=f"Candidate preview 0.4.1 from {source}")
    monkeypatch.setattr(release_plan, "workflow_runs", lambda workflow, *_:
                        [run(source=source)] if workflow == "ci.yml" else [previous])
    output = tmp_path / "skipped"
    github_output = tmp_path / "outputs"
    monkeypatch.setattr(sys, "argv", ["release_plan", "--source-commit", source, "--base", "0.4.1",
                                     "--channel", "preview", "--sequence", "7", "--scheduled",
                                     "--output", str(output), "--github-output", str(github_output)])
    release_plan.main()
    assert "prepare=false\n" in github_output.read_text()
    assert not output.exists()


def test_workflow_keeps_preparation_read_only_and_daily_opt_in():
    workflow = yaml.load((release_plan.ROOT / ".github/workflows/release-candidate.yml").read_text(),
                         Loader=yaml.BaseLoader)
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert "vars.NANOBOT_DAILY_CANDIDATES_ENABLED == 'true'" in jobs["plan"]["if"]
    assert "github.event_name == 'workflow_dispatch'" in jobs["plan"]["if"]
    assert "Disabled daily candidate" in workflow["run-name"]
    assert "NANOBOT_DAILY_CANDIDATES_ENABLED" in workflow["run-name"]
    assert jobs["plan"]["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["candidate"]["if"] == "needs.plan.outputs.prepare == 'true'"
    assert "needs.plan.outputs.prepare == 'true'" in jobs["verified"]["if"]
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert workflow["concurrency"]["group"] == "release-candidate-${{ github.event_name }}"
    retained = [step for job in jobs.values() for step in job.get("steps", [])
                if step.get("name") in {"Preserve the verified bytes and independent candidate source",
                                        "Retain accepted installable candidate for separate approval"}]
    assert len(retained) == 2
    assert all("inputs.retain_installable" in step["if"] for step in retained)
