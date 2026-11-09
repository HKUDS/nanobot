from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--timing-report", help="Write phase timings as JSON, with one file per worker")


def pytest_configure(config: pytest.Config) -> None:
    path = config.getoption("--timing-report")
    if path:
        config.pluginmanager.register(_TimingReport(config, Path(path)), "phase-timing-report")


class _TimingReport:
    def __init__(self, config: pytest.Config, path: Path) -> None:
        self.started = time.perf_counter()
        self.path = path
        self.worker = getattr(config, "workerinput", {}).get("workerid", "controller")
        self.args = list(config.invocation_params.args)
        self.collection_seconds: float | None = None
        self.worker_collection: dict[str, dict[str, float | int]] = {}
        self.cases: dict[str, dict] = {}

    def pytest_collection_finish(self) -> None:
        self.collection_seconds = time.perf_counter() - self.started

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node, ids: list[str]) -> None:
        self.worker_collection[node.gateway.id] = {
            "ready_seconds": time.perf_counter() - self.started,
            "items": len(ids),
        }

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        case = self.cases.setdefault(report.nodeid, {
            "worker": getattr(report, "worker_id", self.worker), "phases": {},
        })
        case["phases"][report.when] = {
            "seconds": report.duration, "outcome": report.outcome,
        }

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        elapsed = time.perf_counter() - self.started
        path = self.path
        if self.worker != "controller":
            path = path.with_stem(f"{path.stem}-{self.worker}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "worker": self.worker,
            "args": self.args,
            "exitstatus": int(exitstatus),
            "configured_to_finish_seconds": elapsed,
            "collection_finish_seconds": self.collection_seconds,
            "worker_collection": self.worker_collection,
            "cases": self.cases,
        }, indent=2), encoding="utf-8")
