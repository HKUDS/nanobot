"""Task type taxonomy and classification for delegation contracts.

Provides ``TASK_TYPES`` — a taxonomy of delegation task categories — and two
classifier functions extracted from ``DelegationDispatcher``:

- ``classify_task_type`` — map a role + task description to a task type key.
- ``has_parallel_structure`` — detect enumerated independent subtasks in text.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Task type taxonomy
# ---------------------------------------------------------------------------

TASK_TYPES: dict[str, dict[str, Any]] = {
    "local_code_analysis": {
        "prefer": ["read_file", "list_dir", "exec"],
        "avoid_first": ["web_search", "web_fetch"],
        "evidence": "file paths + code excerpts with line numbers",
        "completion": (
            "Stop when you have inspected the relevant files and can answer "
            "the question with evidence. Do not exhaustively scan every file "
            "unless the task explicitly asks for it."
        ),
        "anti_hallucination": (
            "Do not infer architecture from naming alone. "
            "Distinguish inspected evidence vs assumption. "
            "Say 'not found' when absent. Cite inspected file paths."
        ),
    },
    "repo_architecture": {
        "prefer": ["read_file", "list_dir", "exec"],
        "avoid_first": ["web_search"],
        "evidence": "file paths, module relationships, code excerpts",
        "completion": (
            "Stop when you have mapped the relevant module structure "
            "and key interfaces. Focus on structure, not every detail."
        ),
        "anti_hallucination": (
            "Only describe architecture you have verified by reading files. "
            "Do not infer from file names alone. Cite every claim."
        ),
    },
    "web_research": {
        "prefer": ["web_search", "web_fetch"],
        "avoid_first": ["exec", "write_file"],
        "evidence": "URLs, quoted excerpts, publication dates",
        "completion": (
            "Stop after finding 3-5 high-quality sources that answer "
            "the question. Cross-reference when possible."
        ),
        "anti_hallucination": (
            "Cite URLs for every claim. Distinguish search results from "
            "your own analysis. Say 'no results found' when searches fail."
        ),
    },
    "report_writing": {
        "prefer": ["write_file", "read_file"],
        "avoid_first": ["exec", "web_search"],
        "evidence": "references to source findings from other agents",
        "completion": (
            "Stop after producing the requested document. Base all content on prior agent findings."
        ),
        "anti_hallucination": (
            "Use ONLY data from prior agent findings (scratchpad). "
            "Do not invent statistics, metrics, or file paths. "
            "If data is missing, note it as a gap."
        ),
    },
    "bug_investigation": {
        "prefer": ["read_file", "exec", "list_dir"],
        "avoid_first": ["web_search", "write_file"],
        "evidence": "error messages, stack traces, file paths + line numbers",
        "completion": (
            "Stop when you have identified the root cause with evidence, "
            "or when you have exhausted reasonable investigation paths."
        ),
        "anti_hallucination": (
            "Report only errors and behavior you have observed via tools. "
            "Do not guess root causes without evidence."
        ),
    },
    "hybrid": {
        "prefer": ["web_search", "web_fetch", "read_file", "list_dir"],
        "avoid_first": ["exec", "write_file"],
        "evidence": "URLs + file paths, cross-referenced",
        "completion": "Stop after gathering external sources AND verifying against local codebase.",
        "anti_hallucination": "Cite URLs for external claims, file paths for local claims.",
    },
    "general": {
        "prefer": [],
        "avoid_first": [],
        "evidence": "tool output excerpts",
        "completion": "Stop when the task objective is met.",
        "anti_hallucination": ("Ground all claims in tool output. Say 'unknown' when unsure."),
    },
}


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------


def classify_task_type(role: str, task: str) -> str:
    """Classify a delegation task into a task type from the taxonomy.

    Returns one of the keys from ``TASK_TYPES``: ``report_writing``,
    ``bug_investigation``, ``hybrid``, ``repo_architecture``,
    ``local_code_analysis``, ``web_research``, or ``general``.

    Uses a two-pass approach: first computes boolean flags for each
    signal category, then applies priority rules.

    **Pass 1 — Flags:**

    - ``has_bug`` — bug/error/crash keywords (only when ``role == "code"``)
    - ``has_arch`` — architecture/design/structure keywords
    - ``has_code`` — code/module/file/function keywords
    - ``has_web`` — latest/current/news/trend/benchmark keywords
    - ``has_project`` — our/this project/nanobot/workspace/codebase keywords

    **Pass 2 — Priority rules:**

    1. ``role == "writing"`` → ``report_writing``
    2. ``role == "code" and has_bug`` → ``bug_investigation``
    3. ``has_web and (has_arch or has_code or has_project)`` → ``hybrid``
    4. ``has_arch`` → ``repo_architecture``
    5. ``has_code or role == "code"`` → ``local_code_analysis``
    6. ``has_web`` → ``web_research``
    7. ``role == "research" and has_project`` → ``repo_architecture``
    8. ``role == "research"`` → ``web_research``
    9. else → ``general``
    """
    task_lower = task.lower()

    # -- Signal tuples --
    code_signals = (
        "code",
        "module",
        "file",
        "function",
        "class",
        "test",
        "import",
        "line",
        "bug",
        "error",
        "refactor",
        "implement",
        "source",
        "python",
        ".py",
        "coverage",
        "lint",
        "scan",
    )
    bug_signals = ("bug", "error", "crash", "fail", "exception", "broken", "fix")
    web_signals = (
        "latest",
        "current",
        "news",
        "trend",
        "benchmark",
        "compare with",
        "industry",
        "best practice",
        "state of the art",
    )
    arch_signals = (
        "architecture",
        "subsystem",
        "design",
        "structure",
        "pattern",
        "how does",
        "relationship",
        "dependency",
    )
    project_signals = (
        "our",
        "this project",
        "nanobot",
        "workspace",
        "codebase",
    )

    # -- Pass 1: compute boolean flags --
    has_bug = role == "code" and any(s in task_lower for s in bug_signals)
    has_arch = any(s in task_lower for s in arch_signals)
    has_code = any(s in task_lower for s in code_signals)
    has_web = any(s in task_lower for s in web_signals)
    has_project = any(s in task_lower for s in project_signals)

    # -- Pass 2: priority rules --
    if role == "writing":
        return "report_writing"
    if has_bug:
        return "bug_investigation"
    if has_web and (has_arch or has_code or has_project):
        return "hybrid"
    if has_arch:
        return "repo_architecture"
    if has_code or role == "code":
        return "local_code_analysis"
    if has_web:
        return "web_research"
    if role == "research" and has_project:
        return "repo_architecture"
    if role == "research":
        return "web_research"
    return "general"


def has_parallel_structure(text: str) -> bool:
    """Detect enumerated independent subtasks in the user message.

    Returns True when any of the five structural patterns are present.
    Each pattern is specific enough to avoid false positives on natural prose.
    """
    text_lower = text.strip().lower()
    if re.search(
        r"\b(two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
        r"(areas?|parts?|aspects?|sections?|components?|topics?|items?|tasks?"
        r"|dimensions?|categories?|modules?|files?|layers?)",
        text_lower,
    ):
        return True
    if re.search(r"(?:[^,]+,\s*){2,}(?:and|&)\s+[^,.]+", text_lower):
        return True
    if re.search(r":\s*[^,]+(?:,\s*[^,]+){2,}", text_lower):
        return True
    if len(re.findall(r"(?:^|\s)(?:\d+[.)\]]|[a-z][.)\]])\s", text_lower)) >= 3:
        return True
    if re.search(r"\bacross\b.+,.+(?:,|and)\s+", text_lower):
        return True
    return False
