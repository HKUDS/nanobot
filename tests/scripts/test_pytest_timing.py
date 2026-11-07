import json

import pytest

pytest_plugins = ["pytester"]


def test_timing_report_preserves_phases_and_failed_results(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makepyfile(
        "import pytest\n"
        "def test_pass(): pass\n"
        "def test_fail(): assert False\n"
        "@pytest.mark.skip(reason='sample')\n"
        "def test_skip(): pass\n",
    )
    output = pytester.path / "timings" / "sample.json"
    result = pytester.runpytest_inprocess(
        "-p", "scripts.pytest_timing", "--timing-report", str(output),
    )
    result.assert_outcomes(passed=1, failed=1, skipped=1)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["exitstatus"] == 1
    cases = {key.rsplit("::", 1)[-1]: value for key, value in report["cases"].items()}
    assert cases["test_pass"]["phases"]["call"]["outcome"] == "passed"
    assert cases["test_fail"]["phases"]["call"]["outcome"] == "failed"
    assert cases["test_skip"]["phases"]["setup"]["outcome"] == "skipped"
    assert sum(phase["seconds"] for case in cases.values()
               for phase in case["phases"].values()) > 0
    assert 0 < report["collection_finish_seconds"] <= report["configured_to_finish_seconds"]
