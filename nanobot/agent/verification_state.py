"""Lightweight verification-result detection for coding workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

VerificationStatus = Literal["passed", "failed"]


@dataclass(frozen=True, slots=True)
class VerificationAnalysis:
    """Structured summary of a command that appears to be verification."""

    status: VerificationStatus
    command: str
    exit_code: int | None
    failed_tests: tuple[str, ...] = ()
    primary_errors: tuple[str, ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class VerificationObservation:
    """Latest verification signal observed for a session."""

    analysis: VerificationAnalysis
    sequence: int


_OBSERVATIONS: dict[str, VerificationObservation] = {}
_SEQUENCE = 0

_TEST_COMMAND_RE = re.compile(
    r"(?ix)"
    r"("
    r"\bpytest\b|\bpy\.test\b|\bunittest\b|\bnosetests\b|"
    r"\btest_outputs\.py\b|\brun_tests?(?:\.sh|\.py)?\b|"
    r"\bnpm\s+(?:run\s+)?test\b|\byarn\s+test\b|\bpnpm\s+test\b|"
    r"\bcargo\s+test\b|\bgo\s+test\b|\bctest\b|"
    r"\bmake\s+(?:[^;&|]*\s+)?test\b"
    r")"
)
_ARTIFACT_CHECK_COMMAND_RE = re.compile(
    r"(?ix)"
    r"("
    r"\bcmp\b|"
    r"\bdiff\b|"
    r"\bsha(?:1|224|256|384|512)?sum\b|"
    r"\bmd5sum\b|"
    r"\bgcc\b.*(?:&&|;).*\./|"
    r"\bclang\b.*(?:&&|;).*\./|"
    r"\bpython3?\b.*<<['\"]?PY\b.*\bassert\b"
    r")"
)
_COMPARISON_COMMAND_RE = re.compile(r"(?i)\b(?:cmp|diff)\b")
_FAILURE_RE = re.compile(
    r"(?im)"
    r"("
    r"^FAILED\s+|"
    r"\b\d+\s+failed\b|"
    r"\bAssertionError\b|"
    r"\bFileNotFoundError\b|"
    r"\bTimeoutError\b|"
    r"\bcommand not found\b|"
    r"\bError:\s+Command timed out\b|"
    r"\bFAILURES?\b|"
    r"\bTEST FAILED\b"
    r")"
)
_SUCCESS_RE = re.compile(
    r"(?im)"
    r"("
    r"\b\d+\s+passed\b|"
    r"\bOK\b|"
    r"\bTEST PASSED\b|"
    r"\bExit code:\s*0\b"
    r")"
)
_ARTIFACT_SUCCESS_RE = re.compile(
    r"(?im)"
    r"("
    r"\b(?:cmp|diff|test|verify)_exit:\s*0\b|"
    r"^\s*(?:cmp|diff|match|same|image|ppm|stdout|stderr|out|err)[\w.-]*:\s*0\s*$"
    r")"
)
_ARTIFACT_FAILURE_RE = re.compile(
    r"(?im)"
    r"("
    r"\b(?:cmp|diff|test|verify)_exit:\s*[1-9]\d*\b|"
    r"^\s*(?:cmp|diff|match|same|image|ppm|stdout|stderr|out|err)[\w.-]*:\s*[1-9]\d*\s*$"
    r")"
)
_FAILED_TEST_RE = re.compile(r"(?m)^FAILED\s+([^\s]+)")
_PYTEST_SHORT_RE = re.compile(r"(?m)^_{3,}\s+([A-Za-z0-9_./:-]+)\s+_{3,}$")
_ERROR_LINE_RE = re.compile(
    r"(?m)"
    r"^\s*(?:E\s+)?("
    r"(?:AssertionError|FileNotFoundError|TimeoutError|ValueError|TypeError|RuntimeError)"
    r"(?::[^\n]*)?|"
    r"assert\s+[^\n]+|"
    r"[^:\n]+:\s+line\s+\d+:\s+[^:\n]+:\s+command not found|"
    r"Error:\s+[^\n]+|"
    r"TEST FAILED[^\n]*"
    r")"
)
_MISSING_PATH_RE = re.compile(
    r"(?i)"
    r"(?:No such file or directory:\s*['\"]([^'\"]+)['\"]|"
    r"(?:file|path)\s+([^\s'\"]+)\s+does not exist|"
    r"cannot open file\s+['\"]([^'\"]+)['\"])"
)


def analyze_verification_result(
    *,
    command: str,
    output: str,
    exit_code: int | None,
    timed_out: bool = False,
) -> VerificationAnalysis | None:
    """Return a verification summary when a command/output looks like a test."""

    command = " ".join((command or "").split())
    looks_like_test_command = bool(_TEST_COMMAND_RE.search(command))
    looks_like_artifact_check = bool(_ARTIFACT_CHECK_COMMAND_RE.search(command))
    looks_like_comparison_command = bool(_COMPARISON_COMMAND_RE.search(command))
    looks_like_verification = looks_like_test_command or looks_like_artifact_check
    failure_seen = bool(_FAILURE_RE.search(output))
    success_seen = bool(_SUCCESS_RE.search(output))
    artifact_success_seen = bool(_ARTIFACT_SUCCESS_RE.search(output)) and (
        looks_like_comparison_command or bool(re.search(r"\b(?:test|verify)_exit:\s*0\b", output, flags=re.I))
    )
    artifact_failure_seen = bool(_ARTIFACT_FAILURE_RE.search(output)) and (
        looks_like_comparison_command or bool(re.search(r"\b(?:test|verify)_exit:\s*[1-9]\d*\b", output, flags=re.I))
    )

    if not looks_like_test_command and not failure_seen:
        if not (looks_like_artifact_check and artifact_success_seen and exit_code == 0):
            return None

    if (
        (timed_out and looks_like_verification)
        or (exit_code not in (None, 0) and (looks_like_verification or failure_seen))
        or failure_seen
        or artifact_failure_seen
    ):
        return VerificationAnalysis(
            status="failed",
            command=command,
            exit_code=exit_code,
            failed_tests=_unique(_FAILED_TEST_RE.findall(output), limit=8),
            primary_errors=_extract_primary_errors(output),
            missing_artifacts=_extract_missing_artifacts(output),
            timed_out=timed_out,
        )

    if looks_like_test_command and exit_code == 0 and success_seen:
        return VerificationAnalysis(
            status="passed",
            command=command,
            exit_code=exit_code,
        )

    if looks_like_artifact_check and exit_code == 0 and artifact_success_seen:
        return VerificationAnalysis(
            status="passed",
            command=command,
            exit_code=exit_code,
        )

    return None


def append_verification_feedback(output: str, analysis: VerificationAnalysis | None) -> str:
    """Append model-facing feedback for failed verification results."""

    if analysis is None or analysis.status != "failed":
        return output

    lines = [
        "",
        "[Verification Feedback]",
        "Verification status: failed.",
        "Do not call complete_goal or present the task as finished until this is fixed and a verification passes.",
    ]
    if analysis.command:
        lines.append(f"Command: {analysis.command[:240]}")
    if analysis.exit_code is not None:
        lines.append(f"Exit code: {analysis.exit_code}")
    if analysis.timed_out:
        lines.append("Failure type: command timeout")
    if analysis.failed_tests:
        lines.append("Failed tests:")
        lines.extend(f"- {item}" for item in analysis.failed_tests)
    if analysis.primary_errors:
        lines.append("Primary errors:")
        lines.extend(f"- {item}" for item in analysis.primary_errors)
    if analysis.missing_artifacts:
        lines.append("Missing artifacts:")
        lines.extend(f"- {item}" for item in analysis.missing_artifacts)
    lines.append("Next action: inspect the failing assertion, fix the implementation or artifact, then rerun the most specific verification command.")
    lines.append("[/Verification Feedback]")
    return output.rstrip() + "\n" + "\n".join(lines)


def record_verification_observation(session_key: str | None, analysis: VerificationAnalysis | None) -> None:
    """Remember the latest verification signal for a session."""

    if not session_key or analysis is None:
        return
    global _SEQUENCE
    _SEQUENCE += 1
    _OBSERVATIONS[session_key] = VerificationObservation(
        analysis=analysis,
        sequence=_SEQUENCE,
    )


def latest_verification_observation(session_key: str | None) -> VerificationObservation | None:
    if not session_key:
        return None
    return _OBSERVATIONS.get(session_key)


def clear_verification_observation(session_key: str | None) -> None:
    if session_key:
        _OBSERVATIONS.pop(session_key, None)


def format_completion_gate_message(observation: VerificationObservation) -> str:
    """Build the complete_goal soft-gate message for unresolved failures."""

    analysis = observation.analysis
    lines = [
        "Recent verification appears to have failed, so the goal is not marked complete yet.",
        "Continue fixing the task and rerun verification before completing.",
    ]
    if analysis.command:
        lines.append(f"Last failed verification command: {analysis.command[:240]}")
    if analysis.failed_tests:
        lines.append("Failed tests: " + ", ".join(analysis.failed_tests[:5]))
    if analysis.primary_errors:
        lines.append("Primary error: " + analysis.primary_errors[0])
    if analysis.missing_artifacts:
        lines.append("Missing artifact: " + analysis.missing_artifacts[0])
    lines.append(
        "If you are intentionally stopping with known failures, call complete_goal again with remaining_failures describing them honestly."
    )
    return "\n".join(lines)


def _extract_primary_errors(output: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for match in _ERROR_LINE_RE.findall(output):
        text = " ".join(match.split())
        if text and text not in candidates:
            candidates.append(text[:240])
        if len(candidates) >= 8:
            break
    if not candidates:
        for match in _PYTEST_SHORT_RE.findall(output):
            text = " ".join(match.split())
            if text and text not in candidates:
                candidates.append(text[:240])
            if len(candidates) >= 4:
                break
    return tuple(candidates)


def _extract_missing_artifacts(output: str) -> tuple[str, ...]:
    paths: list[str] = []
    for groups in _MISSING_PATH_RE.findall(output):
        path = next((item for item in groups if item), "")
        if path and path not in paths:
            paths.append(path[:240])
        if len(paths) >= 8:
            break
    return tuple(paths)


def _unique(items: list[str], *, limit: int) -> tuple[str, ...]:
    out: list[str] = []
    for item in items:
        text = " ".join(item.split())
        if text and text not in out:
            out.append(text[:240])
        if len(out) >= limit:
            break
    return tuple(out)
