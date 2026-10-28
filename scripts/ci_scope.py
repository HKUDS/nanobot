#!/usr/bin/env python3
"""Conservative, stdlib-only CI path selection; importable without running git.

Rules describe validation needs, not event policy: the workflow may restrict native
acceptance to PRs, but dispatch and fallback still request every validation lane.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

JOBS = ("python_required", "webui_required", "tui_required", "docker_required", "native_required")
ALL = frozenset(JOBS)
PYTHON = frozenset({"python_required"})
DOCKER = frozenset({"docker_required"})
WEBUI = frozenset({"webui_required"})
TUI = frozenset({"tui_required"})
NATIVE = frozenset({"native_required"})

# Ordered first-match rules. Keep Docker README inputs before documentation rules,
# and embedded channel frontend trees before the Python production catch-all.
RULES = (
    ((".github/workflows/ci.yml", ".github/workflows/native-acceptance.yml",
      "scripts/ci_scope.py", "tests/scripts/test_ci_scope.py",
      "scripts/native_acceptance_input.py", "tests/scripts/test_native_acceptance_input.py",
      "scripts/ci_gate.py", "tests/scripts/test_ci_gate.py", "tests/scripts/test_ci_workflows.py"),
     ALL, "CI selector or execution contract"),
    ((".github/workflows/release-candidate.yml", ".github/workflows/release-approve.yml"),
     PYTHON | NATIVE, "release workflow (including Python parse/collection validation)"),
    ((".github/workflows/tui-release.yml",), PYTHON | TUI | NATIVE, "native TUI publication workflow"),
    ((".github/workflows/*",), ALL, "unknown workflow"),
    (("pyproject.toml", "uv.lock", "hatch_build.py", "nanobot/webui/build.py", "scripts/install*",
      "scripts/build*"), ALL, "cross-domain dependency, build or installation contract"),
    (("tests/test_docker*.py",), PYTHON | DOCKER, "Docker Python regression tests"),
    (("Dockerfile", "Dockerfile.*", ".dockerignore", "docker-compose*.yml", "entrypoint.sh",
      "render-config.json", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
      "tests/test_docker*", "scripts/docker_compose_smoke.py"), DOCKER, "Docker input or acceptance"),
    # Shared fixture consumers live in tests/webui and webui/src/tests; the
    # SQLite migration and release-trust fixtures have separate Python owners.
    (("tests/webui/fixtures/runtime-config-keys.json",), PYTHON | WEBUI,
     "shared Python and WebUI runtime configuration test contract"),
    (("tests/session/fixtures/sqlite_v1.sql",), PYTHON, "Python session schema migration fixture"),
    (("tests/fixtures/sigstore/bundle_v3.txt", "tests/fixtures/sigstore/bundle_v3.txt.sigstore"),
     PYTHON | NATIVE, "release trust verification fixtures"),
    (("tests/fixtures/sigstore/README.md", "tests/fixtures/sigstore/LICENSE"),
     frozenset(), "test fixture provenance and license"),
    (("docs/*", ".agent/*", ".github/ISSUE_TEMPLATE/*", "AGENTS.md", "CLAUDE.md",
      "COMMUNICATION.md", "CONTRIBUTING.md", "SECURITY.md", "webui/README.md",
      "tui/README.md", "render.yaml", "images/*"), frozenset(), "documentation only"),
    (("scripts/check_client_import_boundaries.*",), WEBUI | TUI, "shared client import boundary checker"),
    (("packages/client-events/*",), WEBUI | TUI | DOCKER, "shared client event protocol"),
    (("webui/*", "nanobot/channels/*/webui/*", "nanobot/channels/*/tests/webui/*"),
     WEBUI | DOCKER, "WebUI source or embedded channel frontend"),
    (("tui/scripts/package-release.py", "tui/scripts/release-notices.ts", "tui/scripts/prepare-target.ts",
      "tui/scripts/build.ts", "tui/package.json", "tui/bun.lock"), TUI | NATIVE, "native TUI packaging or dependencies"),
    (("tui/*",), TUI, "TUI functionality"),
    (("nanobot/channels/websocket/runtime.py", "nanobot/webui/gateway_endpoint.py"),
     PYTHON | DOCKER | WEBUI | TUI | NATIVE, "shared gateway lifecycle and client protocol"),
    # These modules own wire events, transport and session representations used
    # by both clients. Other backend WebUI modules need only the WebUI consumer.
    (("nanobot/webui/client_contract.py", "nanobot/webui/outbound_*.py",
      "nanobot/webui/inbound_commands.py", "nanobot/webui/ws_http.py",
      "nanobot/webui/gateway_*.py", "nanobot/webui/session_*.py",
      "nanobot/webui/history.py", "nanobot/webui/transcript.py",
      "nanobot/webui/sidebar_state.py", "nanobot/webui/settings_*.py",
      "nanobot/webui/workspaces.py", "nanobot/webui/skills_api.py",
      "nanobot/webui/cli_apps_api.py", "nanobot/webui/mcp_presets_api.py",
      "nanobot/webui/recovery.py", "nanobot/webui/forking.py", "nanobot/session/*", "nanobot/events.py",
      "nanobot/bus/events.py", "nanobot/api/*", "nanobot/channels/websocket/*.py"),
     PYTHON | DOCKER | WEBUI | TUI, "shared backend client protocol, transport or session representation"),
    (("nanobot/webui/local_client_assets.py",), PYTHON | DOCKER | WEBUI | NATIVE,
     "installed client asset discovery"),
    (("nanobot/webui/*",), PYTHON | DOCKER | WEBUI, "WebUI backend"),
    (("nanobot/update*", "nanobot/release*", "nanobot/installation*", "nanobot/bun.py",
      "nanobot/build_info.py", "nanobot/__init__.py", "nanobot/__main__.py",
      "nanobot/nanobot.py", "nanobot/process_runtime.py", "nanobot/runtime_admission.py", "nanobot/data_access.py",
      "nanobot/gateway/*", "nanobot/cli/entry.py", "nanobot/cli/commands.py",
      "nanobot/cli/gateway*.py", "nanobot/cli/update.py", "nanobot/cli/process_identity.py",
      "nanobot/cli/desktop*.py", "nanobot/cli/tui_launcher.py", "nanobot/cli/dock.py",
      "nanobot/cli/_macos_dock.py", "nanobot/cli/runtime_config.py", "nanobot/cli/webui.py", "nanobot/cli/webui_support.py",
      "nanobot/config/paths.py", "nanobot/utils/rotating_output.py",
      "nanobot/utils/atomic_file.py", "nanobot/utils/file_io.py", "nanobot/utils/runtime.py",
      "nanobot/utils/restart.py"),
     PYTHON | DOCKER | NATIVE, "installed application lifecycle, update or runtime"),
    (("nanobot/*",), PYTHON | DOCKER, "Python production source"),
    (("tests/test_update*", "tests/test_windows_update*", "tests/test_release*",
      "tests/test_install*", "tests/test_packaged_update*", "tests/test_bun.py",
      "tests/test_build_info.py", "tests/gateway/*", "tests/cli/test_entry.py",
      "tests/cli/test_commands.py", "tests/cli/test_gateway*", "tests/cli/test_process_identity.py",
      "tests/cli/test_desktop*", "tests/cli/test_tui*", "tests/cli/test_restart*",
      "tests/utils/test_atomic*", "tests/utils/test_file_io*", "tests/test_process*",
      "tests/test_runtime*", "scripts/verify_*", "scripts/release_*",
      ".github/release-signing-requirements.*"), PYTHON | NATIVE, "lifecycle or installed-release verification"),
    (("tests/*.py", "conftest.py", "scripts/*.py"), PYTHON, "Python tests or tooling"),
)


def classify_paths(paths: list[str]) -> dict:
    """Select the union of requirements, preserving a reason for every path."""
    required = set()
    decisions = []
    for path in paths:
        for patterns, jobs, reason in RULES:
            if any(fnmatchcase(path, pattern) for pattern in patterns):
                break
        else:
            jobs, reason = ALL, "unknown path; conservative full validation"
        required.update(jobs)
        decisions.append({"path": path, "reason": reason, "jobs": sorted(jobs)})
    if not paths:
        required.update(ALL)
    return {
        "outputs": {job: job in required for job in JOBS},
        "reason": "classified changed paths" if paths else "empty diff; conservative full validation",
        "paths": decisions,
    }


def select_scope(event: str, base: str, head: str, *, cwd: Path | None = None) -> dict:
    """Use merge-base diff for PRs, endpoint diff for pushes, full for dispatch."""
    if event == "workflow_dispatch":
        result = classify_paths([])
        result["reason"] = "manual dispatch; full validation"
        return result
    if event not in {"pull_request", "push"}:
        raise ValueError(f"unsupported event: {event}")
    # Accept only commit IDs, never option-like revision expressions from env.
    if not all(re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", sha) for sha in (base, head)):
        result = classify_paths([])
        result["reason"] = "invalid or missing commit SHA; conservative full validation"
        return result
    diff_range = f"{base}{'...' if event == 'pull_request' else '..'}{head}"
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", diff_range, "--"],
            cwd=cwd, check=True, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result = classify_paths([])
        result["reason"] = f"git diff unavailable ({type(exc).__name__}); conservative full validation"
        return result
    paths = diff.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    result = classify_paths([path for path in paths if path])
    result["diff_range"] = diff_range
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, choices=("pull_request", "push", "workflow_dispatch"))
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    args = parser.parse_args()
    result = select_scope(args.event, args.base, args.head)
    report = json.dumps(result, indent=2, ensure_ascii=True)
    print(report)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            for job, required in result["outputs"].items():
                stream.write(f"{job}={str(required).lower()}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            # JSON escapes path newlines; HTML escaping also prevents Markdown or
            # raw HTML in filenames from escaping the summary's preformatted block.
            stream.write("## CI scope\n\n<pre>" + html.escape(report) + "</pre>\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
