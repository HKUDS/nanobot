from __future__ import annotations

from nanobot.coordination.task_types import classify_task_type


def test_classify_task_type_paths() -> None:
    assert classify_task_type("writing", "write a summary") == "report_writing"
    assert classify_task_type("code", "fix this bug") == "bug_investigation"
    assert classify_task_type("research", "architecture dependency map") == "repo_architecture"
    assert classify_task_type("research", "current industry trends") == "web_research"
    assert classify_task_type("research", "nanobot architecture overview") == "repo_architecture"
    assert classify_task_type("general", "hello world") == "general"
    # hybrid: web + arch/code/project signals combined
    assert classify_task_type("research", "architecture of best practice DI frameworks") == "hybrid"
    assert (
        classify_task_type("research", "compare our codebase with current industry best practices")
        == "hybrid"
    )
    assert (
        classify_task_type("research", "latest best practices for Python module structure")
        == "hybrid"
    )
