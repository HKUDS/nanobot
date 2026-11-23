"""Plan candidate preparation and write draft notes; never publish a release."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from packaging.version import Version
from pydantic import BaseModel

from nanobot.releases import release_version

ROOT = Path(__file__).resolve().parents[1]


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True, encoding="utf-8", timeout=30).stdout.strip()


class WorkflowRun(BaseModel):
    head_sha: str
    display_title: str
    event: str
    run_number: int
    run_attempt: int
    status: str
    conclusion: str | None


class WorkflowRuns(BaseModel):
    workflow_runs: list[WorkflowRun]


def workflow_runs(workflow: str, source: str, query: str) -> list[WorkflowRun]:
    result = subprocess.run(
        ["gh", "api", f"repos/HKUDS/nanobot/actions/workflows/{workflow}/runs"
         f"?head_sha={source}&per_page=100&{query}"],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    return WorkflowRuns.model_validate_json(result.stdout).workflow_runs


def daily_needed(source: str, base: str, ci: list[WorkflowRun], candidates: list[WorkflowRun]) -> bool:
    """Only prepare the scheduled main SHA after its latest push CI succeeds."""
    matching = [run for run in ci if run.head_sha == source and run.event == "push"]
    latest = max(matching, key=lambda run: (run.run_number, run.run_attempt), default=None)
    if latest is None or latest.status != "completed" or latest.conclusion != "success":
        raise ValueError("The scheduled source has no successful latest push CI; wait for CI or repair it")
    title = f"Candidate preview {base} from {source}"
    return not any(
        run.head_sha == source and run.display_title == title
        and run.event in {"schedule", "workflow_dispatch"}
        and run.status == "completed" and run.conclusion == "success"
        for run in candidates
    )


def previous_tag(root: Path, source: str, version: str) -> str:
    """Choose the preceding release on this source line, not the newest tag by date."""
    target = Version(version)
    candidates: list[tuple[Version, str]] = []
    for tag in git(root, "tag", "--list", "v*").splitlines():
        try:
            parsed = Version(release_version(tag[1:]))
        except ValueError:
            continue
        if parsed >= target or (not target.is_prerelease and parsed.is_prerelease):
            continue
        candidates.append((parsed, tag))
    for parsed, tag in sorted(candidates, reverse=True):
        # Preview preparation adds a version-only child that is not merged into main.
        ref = f"{tag}^" if parsed.is_devrelease else tag
        result = subprocess.run(["git", "merge-base", "--is-ancestor", ref, source], cwd=root,
                                capture_output=True, check=False, timeout=30)
        if result.returncode == 0:
            return tag
        if result.returncode != 1:
            raise ValueError(f"Cannot resolve release history for {tag}")
    raise ValueError("No preceding release on this source line; review the release range manually")


def render_notes(root: Path, *, source: str, version: str) -> str:
    previous = previous_tag(root, source, version)
    changes = git(root, "log", "--format=- %s (%h)", f"{previous}..{source}")
    return (
        f"# {version}\n\nChanges since {previous}:\n\n{changes or 'No code changes.'}\n\n"
        f"Source: `{source}`\n\n"
        "Draft generated from commit subjects. Review required upgrade instructions and "
        "coordinated disclosure wording before publication.\n"
    )


def plan(root: Path, *, source: str, base: str, channel: str, sequence: int, scheduled: bool) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("Use an exact full source commit SHA")
    # Both channels require a final base. Keep the candidate workflow's existing sequence.
    parsed = Version(release_version(base))
    if parsed.is_prerelease or parsed.is_postrelease or sequence < 1:
        raise ValueError("Use a final base and a positive candidate sequence")
    version = f"{base}.dev{sequence}" if channel == "preview" else base
    if channel not in {"stable", "preview"} or (scheduled and channel != "preview"):
        raise ValueError("Scheduled preparation is Preview only")
    if git(root, "tag", "--list", f"v{version}") or git(root, "tag", "--list", f"v{base}"):
        raise ValueError("Version or stable base is already tagged; choose an unused version")
    prepare = True
    if scheduled:
        prepare = daily_needed(
            source, base,
            workflow_runs("ci.yml", source, "event=push"),
            workflow_runs("release-candidate.yml", source, "status=success&branch=main"),
        )
    return {"prepare": str(prepare).lower(), "source_commit": source, "base": base,
            "channel": channel, "version": version}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--channel", required=True, choices=("stable", "preview"))
    parser.add_argument("--sequence", required=True, type=int)
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-output", required=True, type=Path)
    args = parser.parse_args()
    result = plan(ROOT, source=args.source_commit, base=args.base, channel=args.channel,
                  sequence=args.sequence, scheduled=args.scheduled)
    if result["prepare"] == "true":
        notes = render_notes(ROOT, source=result["source_commit"], version=result["version"])
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "release-notes.md").write_text(notes, encoding="utf-8")
        (args.output / "plan.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with args.github_output.open("a", encoding="utf-8") as stream:
        stream.writelines(f"{key}={value}\n" for key, value in result.items())
    print(json.dumps(result))


if __name__ == "__main__":
    main()
