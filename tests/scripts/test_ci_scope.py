"""Path policy and real git range regressions for the CI selector."""

import html
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.ci_scope import JOBS, classify_paths, select_scope

ROOT = Path(__file__).resolve().parents[2]


def selected(result):
    return {name.removesuffix("_required") for name, value in result["outputs"].items() if value}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/releasing.md", set()),
        ("webui/README.md", set()),
        ("README.md", {"docker"}),
        ("Dockerfile", {"docker"}),
        ("entrypoint.sh", {"docker"}),
        ("tests/test_docker_config.py", {"python", "docker"}),
        ("tests/test_docker_smoke.py", {"python", "docker"}),
        ("tests/test_docker.sh", {"docker"}),
        ("tests/webui/fixtures/runtime-config-keys.json", {"python", "webui"}),
        ("tests/session/fixtures/sqlite_v1.sql", {"python"}),
        ("scripts/docker_upgrade_smoke.py", {"docker"}),
        ("tests/fixtures/sigstore/bundle_v3.txt", {"python", "native"}),
        ("tests/fixtures/sigstore/bundle_v3.txt.sigstore", {"python", "native"}),
        ("tests/fixtures/sigstore/README.md", set()),
        ("tests/fixtures/sigstore/LICENSE", set()),
        ("webui/package.json", {"webui", "docker"}),
        ("nanobot/channels/discord/webui/index.ts", {"webui", "docker"}),
        ("tui/package.json", {"tui", "native"}),
        ("tui/scripts/build.ts", {"tui", "native"}),
        ("tui/src/composer/textarea.ts", {"tui"}),
        ("nanobot/channels/websocket/runtime.py", {"python", "webui", "tui", "docker", "native"}),
        ("nanobot/providers/registry.py", {"python", "docker"}),
        ("nanobot/webui/native_file_picker.py", {"python", "webui", "docker"}),
        ("nanobot/webui/client_contract.py", {"python", "webui", "tui", "docker"}),
        ("nanobot/webui/forking.py", {"python", "webui", "tui", "docker"}),
        ("nanobot/cli/webui.py", {"python", "docker", "native"}),
        ("nanobot/webui/ws_http.py", {"python", "webui", "tui", "docker"}),
        ("nanobot/session/session_messages.py", {"python", "webui", "tui", "docker"}),
        ("packages/client-events/notifications.ts", {"webui", "tui", "docker"}),
        ("nanobot/update_recovery.py", {"python", "docker", "native"}),
        ("nanobot/release_trust.py", {"python", "docker", "native"}),
        ("nanobot/gateway/runtime.py", {"python", "docker", "native"}),
        ("nanobot/process_runtime.py", {"python", "docker", "native"}),
        ("nanobot/cli/entry.py", {"python", "docker", "native"}),
        ("nanobot/utils/atomic_file.py", {"python", "docker", "native"}),
        ("tests/test_update_backup.py", {"python", "native"}),
        ("tests/test_install_scripts.py", {"python", "native"}),
        ("tests/providers/test_cached_tokens.py", {"python"}),
        ("scripts/pytest_timing.py", {"python"}),
        ("tests/scripts/test_pytest_timing.py", {"python"}),
        ("scripts/verify_packaged_update.py", {"python", "docker", "native"}),
        ("scripts/check_client_import_boundaries.mjs", {"webui", "tui"}),
        (".github/workflows/release-candidate.yml", {"python", "native"}),
        (".github/workflows/release-approve.yml", {"python", "native"}),
        (".github/workflows/tui-release.yml", {"python", "tui", "native"}),
        ("pyproject.toml", {"python", "webui", "tui", "docker", "native"}),
        ("hatch_build.py", {"python", "webui", "tui", "docker", "native"}),
        ("scripts/install_channel_dependencies.py", {"python", "webui", "tui", "docker", "native"}),
        (".github/workflows/ci.yml", {"python", "webui", "tui", "docker", "native"}),
        ("scripts/ci_scope.py", {"python", "webui", "tui", "docker", "native"}),
        ("nanobot/webui/build.py", {"python", "webui", "tui", "docker", "native"}),
        ("nanobot/webui/local_client_assets.py", {"python", "webui", "docker", "native"}),
    ],
)
def test_existing_path_policy(path, expected):
    # These are reachable repository inputs, not merely invented glob matches.
    assert (ROOT / path).is_file()
    result = classify_paths([path])
    assert selected(result) == expected
    assert result["paths"][0]["reason"]


@pytest.mark.parametrize("path", [
    "new-domain/source.txt", ".github/workflows/publish-index.yml", "uv.lock",
    "tests/webui/fixtures/new-contract.json", "tests/fixtures/sigstore/new-proof.sigstore",
])
def test_new_or_cross_domain_paths_require_every_job(path):
    assert all(classify_paths([path])["outputs"].values())


def test_union_preserves_each_reason():
    result = classify_paths(["docs/releasing.md", "tui/package.json", "nanobot/providers/registry.py"])
    assert selected(result) == {"python", "docker", "tui", "native"}
    assert len(result["paths"]) == 3


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["tests/webui/fixtures/runtime-config-keys.json", "tests/session/fixtures/sqlite_v1.sql"],
         {"python", "webui"}),
        (["tests/webui/fixtures/runtime-config-keys.json", "nanobot/webui/settings_runtime.py",
          "webui/src/tests/settings-runtime-config.test.tsx"],
         {"python", "webui", "tui", "docker"}),
        (["tests/webui/fixtures/runtime-config-keys.json", "tests/fixtures/sigstore/bundle_v3.txt"],
         {"python", "webui", "native"}),
        (["tests/session/fixtures/sqlite_v1.sql", "tests/webui/fixtures/new-contract.json"],
         {"python", "webui", "tui", "docker", "native"}),
    ],
)
def test_fixture_requirements_combine_with_other_changed_paths(paths, expected):
    result = classify_paths(paths)
    assert selected(result) == expected
    assert len(result["paths"]) == len(paths)


@pytest.fixture
def repo(tmp_path):
    def git(*args, input=None):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True, input=input,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "CI scope test")
    git("config", "user.email", "ci-scope@example.invalid")

    def commit(path, text):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git("add", "--all")
        git("commit", "-m", "fixture change")
        return git("rev-parse", "HEAD")

    return tmp_path, git, commit


def test_push_includes_all_commits_not_only_last(repo):
    cwd, _, commit = repo
    base = commit("docs/guide.md", "initial")
    commit("nanobot/providers/new.py", "production")
    head = commit("webui/src/new.ts", "frontend")
    result = select_scope("push", base, head, cwd=cwd)
    assert selected(result) == {"python", "webui", "docker"}
    assert result["diff_range"] == f"{base}..{head}"


def test_pr_uses_merge_base_not_base_tip(repo):
    cwd, git, commit = repo
    commit("docs/guide.md", "initial")
    git("checkout", "-b", "feature")
    head = commit("webui/src/new.ts", "frontend")
    git("checkout", "main")
    base = commit("tui/src/base-only.ts", "base branch only")
    assert selected(select_scope("pull_request", base, head, cwd=cwd)) == {"webui", "docker"}
    assert selected(select_scope("push", base, head, cwd=cwd)) == {"webui", "docker", "tui"}


def test_rename_and_delete_keep_old_domain(repo):
    cwd, git, commit = repo
    commit("nanobot/providers/old.py", "production")
    base = commit("tui/src/removed.ts", "native package")
    target = cwd / "docs" / "renamed file.md"
    target.parent.mkdir()
    (cwd / "nanobot/providers/old.py").rename(target)
    (cwd / "tui/src/removed.ts").unlink()
    git("add", "--all")
    git("commit", "-m", "rename and delete")
    result = select_scope("push", base, git("rev-parse", "HEAD"), cwd=cwd)
    assert selected(result) == {"python", "docker", "tui"}
    assert {item["path"] for item in result["paths"]} == {
        "nanobot/providers/old.py", "tui/src/removed.ts", "docs/renamed file.md",
    }


def test_empty_missing_and_invalid_diff_are_full(repo):
    cwd, _, commit = repo
    head = commit("docs/guide.md", "initial")
    for base, expected in [(head, "empty diff"), ("0" * 40, "git diff unavailable"), ("--help", "invalid")]:
        result = select_scope("push", base, head, cwd=cwd)
        assert all(result["outputs"].values())
        assert expected in result["reason"]


def test_non_repository_and_dispatch_are_full(tmp_path):
    result = select_scope("pull_request", "1" * 40, "2" * 40, cwd=tmp_path)
    assert all(result["outputs"].values())
    assert "git diff unavailable" in result["reason"]
    result = select_scope("workflow_dispatch", "", "", cwd=tmp_path)
    assert all(result["outputs"].values())
    assert "manual dispatch" in result["reason"]


def test_cli_emits_only_fixed_boolean_outputs_and_escaped_summary(repo):
    cwd, git, commit = repo
    base = commit("docs/guide.md", "initial")
    # A PR authored on Unix can contain names Windows cannot check out or add
    # to its index. Build the actual Git tree directly, without materializing it.
    blob = git("rev-parse", "HEAD:docs/guide.md")
    subtree = git("mktree", "-z", input=f"100644 blob {blob}\t```\npython_required=false<script>.ts\0")
    tree = git("mktree", "-z", input=f"040000 tree {subtree}\twebui\0")
    head = git("commit-tree", tree, "-p", base, "-m", "untrusted filename")
    output, summary = cwd / "output", cwd / "summary"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci_scope.py"), "--event", "push", "--base", base, "--head", head],
        cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)},
    )
    result = json.loads(proc.stdout)
    assert selected(result) == {"webui", "docker"}
    assert output.read_text().splitlines() == [
        f"{job}={str(result['outputs'][job]).lower()}" for job in JOBS
    ]
    assert "&lt;script&gt;" in summary.read_text()
    assert "\\npython_required=false" in summary.read_text()
    summary_json = summary.read_text().split("<pre>", 1)[1].removesuffix("</pre>\n")
    assert json.loads(html.unescape(summary_json)) == result


def test_every_frozen_worker_source_selects_native_acceptance(tmp_path):
    from nanobot.update_jobs import _worker_archive

    archive = tmp_path / "worker.pyz"
    _worker_archive(archive)
    with ZipFile(archive) as bundle:
        sources = ["nanobot/" + name.removeprefix("_nanobot_update/")
                   for name in bundle.namelist()
                   if name.startswith("_nanobot_update/") and not name.endswith("__init__.py")]
    assert sources
    for path in sources:
        assert classify_paths([path])["outputs"]["native_required"], path
