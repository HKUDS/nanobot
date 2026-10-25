"""Protect the required-check contract when GitHub skips conditional jobs."""

import pytest

from scripts.ci_gate import check_results


def results(*domains):
    return {
        "changes": {"result": "success", "outputs": {
            f"{domain}_required": str(domain in domains).lower()
            for domain in ("python", "webui", "tui", "docker", "native")
        }},
        **{job: {"result": "skipped"} for job in (
            "test", "windows_process", "windows_installers", "webui_checks", "webui_browser", "webui", "tui", "docker", "native",
        )},
    }


def test_documentation_needs_no_product_jobs():
    assert check_results(results(), "pull_request") == []


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_selected_job_must_succeed(result):
    needs = results("webui")
    for job in ("webui_checks", "webui_browser", "webui"):
        needs[job]["result"] = "success"
    needs["webui_browser"]["result"] = result
    assert check_results(needs, "pull_request")


def test_native_runs_on_high_risk_pr_but_not_main_push():
    needs = results("native")
    assert check_results(needs, "pull_request")
    assert check_results(needs, "push") == []
    needs["native"]["result"] = "success"
    assert check_results(needs, "pull_request") == []


def test_failed_or_incomplete_selection_is_not_documentation_only():
    needs = results()
    needs["changes"]["result"] = "failure"
    assert check_results(needs, "pull_request")
    needs["changes"]["result"] = "success"
    del needs["changes"]["outputs"]["native_required"]
    assert check_results(needs, "pull_request")


def test_unexpected_failure_is_not_ignored():
    needs = results()
    needs["native"]["result"] = "cancelled"
    assert check_results(needs, "push")


def test_selected_windows_installers_are_required_independently_of_process_tests():
    needs = results("python", "native")
    for job in ("test", "windows_process", "native"):
        needs[job]["result"] = "success"
    assert check_results(needs, "pull_request") == ["windows_installers: required, got skipped"]
    needs["windows_installers"]["result"] = "success"
    assert check_results(needs, "pull_request") == []
    needs["windows_installers"]["result"] = "skipped"
    needs["native"]["result"] = "skipped"
    assert check_results(needs, "push") == []
