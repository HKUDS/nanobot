from __future__ import annotations

from nanobot.agent.verification_state import (
    analyze_verification_result,
    append_verification_feedback,
)


def test_analyze_pytest_failure_extracts_actionable_summary():
    output = """\
FAILED ../tests/test_outputs.py::test_regex_matches_dates - AssertionError: Expected dates
E       AssertionError: Expected ['2025-01-09'], but got ['bad']
E       FileNotFoundError: [Errno 2] No such file or directory: '/app/out.txt'
============================== 1 failed in 0.05s ===============================
Exit code: 1
"""

    analysis = analyze_verification_result(
        command="pytest /tests/test_outputs.py",
        output=output,
        exit_code=1,
    )

    assert analysis is not None
    assert analysis.status == "failed"
    assert analysis.failed_tests == ("../tests/test_outputs.py::test_regex_matches_dates",)
    assert any("AssertionError" in item for item in analysis.primary_errors)
    assert "/app/out.txt" in analysis.missing_artifacts


def test_append_verification_feedback_tells_agent_not_to_finish():
    analysis = analyze_verification_result(
        command="python /app/test_outputs.py",
        output="FAILED test_outputs.py::test_file\nAssertionError: missing\nExit code: 1",
        exit_code=1,
    )

    feedback = append_verification_feedback("raw output\nExit code: 1", analysis)

    assert "[Verification Feedback]" in feedback
    assert "Do not call complete_goal" in feedback
    assert "Next action" in feedback


def test_analyze_passing_test_records_success_without_feedback():
    analysis = analyze_verification_result(
        command="pytest",
        output="============================== 3 passed in 0.10s ==============================\nExit code: 0",
        exit_code=0,
    )

    assert analysis is not None
    assert analysis.status == "passed"
    assert append_verification_feedback("ok", analysis) == "ok"


def test_analyze_command_not_found_as_failed_check():
    output = """\
STDERR:
/usr/bin/bash: line 1: python3: command not found

Exit code: 127
"""

    analysis = analyze_verification_result(
        command="python3 - <<'PY'\nprint('quick verification')\nPY",
        output=output,
        exit_code=127,
    )

    assert analysis is not None
    assert analysis.status == "failed"
    assert any("command not found" in item for item in analysis.primary_errors)


def test_analyze_artifact_comparison_success_records_pass():
    output = """\
run_exit:0
0d115b98  /app/image.ppm
0d115b98  /tmp/orig.ppm
cmp_exit:0
      7      21    1024

Exit code: 0
"""

    analysis = analyze_verification_result(
        command=(
            "cd /usr/bin && gcc -static -o /app/reversed_final /app/mystery.c -lm "
            "&& (cd /app && ./reversed_final >/tmp/final_out 2>/tmp/final_err); "
            "sha256sum /app/image.ppm /tmp/orig.ppm; "
            "cmp -s /app/image.ppm /tmp/orig.ppm; echo cmp_exit:$?"
        ),
        output=output,
        exit_code=0,
    )

    assert analysis is not None
    assert analysis.status == "passed"
    assert append_verification_feedback("ok", analysis) == "ok"


def test_analyze_plain_checksum_without_success_marker_is_ignored():
    analysis = analyze_verification_result(
        command="sha256sum /app/image.ppm /tmp/orig.ppm",
        output="0d115b98  /app/image.ppm\n0d115b98  /tmp/orig.ppm\nExit code: 0",
        exit_code=0,
    )

    assert analysis is None


def test_analyze_named_comparison_markers_record_pass():
    output = """\
ppm:0
stderr:0
stdout:0
      4      26    1011
1821 mystery.c

Exit code: 0
"""

    analysis = analyze_verification_result(
        command=(
            "gcc -static -O2 -o reversed mystery.c -lm\n"
            "./reversed > vrout.txt 2> vrerr.txt\n"
            "cp image.ppm rev.ppm\n"
            "./mystery > voout.txt 2> voerr.txt\n"
            "cmp image.ppm rev.ppm\n"
            "printf 'ppm:%s\\n' $?\n"
            "cmp voerr.txt vrerr.txt\n"
            "printf 'stderr:%s\\n' $?\n"
            "cmp voout.txt vrout.txt\n"
            "printf 'stdout:%s\\n' $?"
        ),
        output=output,
        exit_code=0,
    )

    assert analysis is not None
    assert analysis.status == "passed"


def test_analyze_named_comparison_marker_failure_records_failed():
    output = """\
ppm:0
stderr:1
stdout:0

Exit code: 0
"""

    analysis = analyze_verification_result(
        command=(
            "cmp image.ppm rev.ppm; printf 'ppm:%s\\n' $?; "
            "cmp voerr.txt vrerr.txt; printf 'stderr:%s\\n' $?; "
            "cmp voout.txt vrout.txt; printf 'stdout:%s\\n' $?"
        ),
        output=output,
        exit_code=0,
    )

    assert analysis is not None
    assert analysis.status == "failed"


def test_analyze_plain_run_status_marker_without_comparison_is_ignored():
    analysis = analyze_verification_result(
        command="gcc -static -O2 -o reversed mystery.c -lm && ./reversed",
        output="rc:0\nExit code: 0",
        exit_code=0,
    )

    assert analysis is None
