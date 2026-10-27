"""Keep acceptance evidence honest: real target bytes and fail-closed fixtures."""

import asyncio
import csv
import hashlib
import io
import json
import socket
import subprocess
import sys
import textwrap
from argparse import Namespace
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import httpx
import pytest

from nanobot.release_feed import ReleaseFeed
from scripts import verify_packaged_update as probe
from scripts.verify_packaged_update import (
    Timings,
    assert_canonical_preserved,
    assert_history_preserved,
    canonical_records,
    digest,
    feed_records,
    fixture_wheel,
    replace_once,
)


def test_historical_projection_defaults_do_not_mask_history_loss():
    # Real retained packages omit unknown timestamps and an inactive goal from
    # their public projection, although the latter is already in their JSONL.
    events = [{"event": "user_message", "projection_id": "input", "text": "Keep this"},
              {"event": "turn_end", "projection_id": "complete"}]
    before = {"events": events, "completed_turn_ids": ["turn"]}
    projected = [{**events[0], "created_at_ms": 0},
                 {**events[1], "created_at_ms": 0, "goal_state": {"active": False}}]
    after = {**before, "events": projected}
    assert_history_preserved(before, after)
    assert_history_preserved(after, after)
    for change in ({"text": "Changed"}, {"projection_id": "changed"}, {"created_at_ms": 123}):
        with pytest.raises(AssertionError):
            assert_history_preserved(before, {**after, "events": [{**projected[0], **change}, projected[1]]})
    with pytest.raises(AssertionError):
        assert_history_preserved(before, {**after, "events": [projected[0], {**projected[1], "goal_state": {"active": True}}]})
    with pytest.raises(AssertionError):
        assert_history_preserved(before, {**after, "events": projected[:1]})
    with pytest.raises(AssertionError):
        assert_history_preserved(before, {**after, "completed_turn_ids": []})
    with pytest.raises(AssertionError):
        assert_history_preserved(after, before)


def test_display_migration_allows_an_empty_owner_without_masking_context_loss(tmp_path):
    from nanobot.session.display_history import HistoryFact, HistoryImport, HistoryKind
    from nanobot.session.manager import Session
    from nanobot.session.sqlite_store import SqliteSessionStore

    store = SqliteSessionStore(tmp_path)
    store.initialize(tmp_path)
    session = Session(key="websocket:canonical-only")
    session.add_message("user", "Keep this original context")
    store.save(session)
    before = canonical_records(store.path)
    store.migrate_history("acceptance-import", lambda _: [HistoryImport(
        key="websocket:display-only", facts=[HistoryFact(HistoryKind.ANSWER, {"text": "Display only"})],
    )])
    after = canonical_records(store.path)
    assert_canonical_preserved(before, after)
    assert_canonical_preserved(after, after)
    # The real /api/sessions read allocates the newly imported owner's handle.
    store.update_metadata("websocket:display-only", {"session_handle": "jeno"})
    after = canonical_records(store.path)
    assert_canonical_preserved(before, after)
    with pytest.raises(AssertionError):
        assert_canonical_preserved(before, {**after, "messages": []})
    with pytest.raises(AssertionError):
        assert_canonical_preserved(before, {**after, "sessions": after["sessions"][1:]})
    store.update_metadata("websocket:display-only", {"unexpected": "context"})
    with pytest.raises(AssertionError):
        assert_canonical_preserved(before, canonical_records(store.path))


def wheel(tmp_path, version, *, worker=b"# worker\n", fallback=b"# fallback\n"):
    path = tmp_path / f"nanobot_ai-{version}-py3-none-manylinux_2_17_x86_64.whl"
    with ZipFile(path, "w") as archive:
        archive.writestr(f"nanobot_ai-{version}.dist-info/METADATA", f"Name: nanobot-ai\nVersion: {version}\n")
        archive.writestr("nanobot/__init__.py", "# unchanged application\n")
        archive.writestr("nanobot/release_feed.py", "transport=transport or PinnedDNSAsyncTransport(),\n")
        archive.writestr("nanobot/update_worker.py", worker)
        archive.writestr("nanobot/update_fallback.py", fallback)
        binary = ZipInfo("nanobot/tui/bin/nanobot-tui")
        binary.external_attr = 0o100755 << 16
        archive.writestr(binary, b"native executable fixture")
    return path


def test_baseline_instrumentation_does_not_modify_the_target(tmp_path):
    source = wheel(tmp_path, "0.3.6")
    before = digest(source)
    baseline = fixture_wheel(source, tmp_path / "baseline", "0.3.5", feed=tmp_path / "feed.json")
    assert digest(source) == before
    with ZipFile(source) as original, ZipFile(baseline) as copied:
        assert copied.read("nanobot/__init__.py") == original.read("nanobot/__init__.py")
        assert "nanobot/_acceptance_feed.py" not in original.namelist()
        assert copied.getinfo("nanobot/tui/bin/nanobot-tui").external_attr == original.getinfo("nanobot/tui/bin/nanobot-tui").external_attr
        records = csv.reader(io.StringIO(copied.read("nanobot_ai-0.3.5.dist-info/RECORD").decode()))
        for name, checksum, size in records:
            if checksum:
                assert int(size) == len(copied.read(name))
                assert checksum.startswith("sha256=")
    with pytest.raises(FileExistsError):
        fixture_wheel(source, tmp_path / "baseline", "0.3.5", feed=tmp_path / "feed.json")


@pytest.mark.parametrize("version,channel", [("0.3.6", "stable"), ("0.3.6.dev42", "preview")])
def test_local_feed_uses_the_real_resolver_and_exact_target_hash(tmp_path, monkeypatch, version, channel):
    from unittest.mock import AsyncMock

    # The packaged lifecycle fixture is deliberately not a public signed release.
    monkeypatch.setattr(ReleaseFeed, "_authorize", AsyncMock())
    from packaging.tags import Tag

    candidate = wheel(tmp_path, version)
    records = feed_records(candidate, "a" * 40)

    def respond(request):
        item = records[str(request.url)]
        return httpx.Response(200, content=candidate.read_bytes() if "file" in item else json.dumps(item["json"]).encode())

    async def check():
        async with ReleaseFeed(tmp_path / "feed", transport=httpx.MockTransport(respond),
                               supported_tags=[Tag("py3", "none", "manylinux_2_17_x86_64")]) as feed:
            target = await feed.latest(channel)
            assert target.version == version
            assert target.artifact.sha256 == hashlib.sha256(candidate.read_bytes()).hexdigest()
            await feed.revalidate(target)
    asyncio.run(check())


def test_changed_fault_seam_is_not_silently_reported_as_fault_coverage():
    with pytest.raises(ValueError, match="seam changed"):
        replace_once(b"new worker", b"old worker", b"fault")
    with pytest.raises(ValueError, match="seam changed"):
        replace_once(b"old old", b"old", b"fault")


def test_consecutive_feed_advances_generation_without_rewriting_a_release(tmp_path):
    from nanobot.release_feed import CATALOGUE_URL
    from nanobot.releases import ReleaseCatalogue

    intermediate = wheel(tmp_path, "0.3.6.dev0")
    target = wheel(tmp_path, "0.3.6.dev2")
    previous = ReleaseCatalogue.model_validate(feed_records(intermediate, "a" * 40)[CATALOGUE_URL]["json"])
    current = ReleaseCatalogue.model_validate(feed_records(target, "b" * 40, generation=2)[CATALOGUE_URL]["json"])
    current.validate_successor(previous)
    with pytest.raises(ValueError, match="newer generation"):
        current.model_copy(update={"generation": 1}).validate_successor(previous)


@pytest.mark.parametrize("scenario,marker", [
    ("worker-exit", b"os._exit(91)"),
    ("metadata-loss", b"os._exit(92)"),
    ("backup-failure", b"Injected backup write failure"),
    ("restore-interruption", b"Injected rename interruption"),
])
def test_windows_packaged_sources_keep_fault_injection_reachable(tmp_path, scenario, marker):
    package = Path(__file__).resolve().parents[1] / "nanobot"
    def windows_source(name):
        return (package / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    source = wheel(tmp_path, "0.3.6", worker=windows_source("update_worker.py"),
                   fallback=windows_source("update_fallback.py"))
    before = digest(source)
    baseline = fixture_wheel(source, tmp_path / "baseline", "0.3.5", feed=tmp_path / "feed.json", scenario=scenario)
    with ZipFile(baseline) as archive:
        name = "update_fallback.py" if scenario == "restore-interruption" else "update_worker.py"
        content = archive.read("nanobot/" + name)
        assert content.count(marker) == 1
        if scenario != "restore-interruption":
            assert repr(str(tmp_path / "injected-fault")).encode() in content
        compile(content, name, "exec")
    assert digest(source) == before


def test_unisolated_probe_refuses_before_creating_output(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/verify_packaged_update.py"
    output = tmp_path / "must-not-exist"
    result = subprocess.run([sys.executable, str(script), "--output", str(output)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and "python -I" in result.stderr
    assert not output.exists()


def test_timings_checkpoint_real_fixture_and_keep_result_schema_separate(tmp_path, capsys):
    output = tmp_path / "packaged-update-timings.json"
    timings = Timings(output)
    source = wheel(tmp_path, "0.3.6")
    with timings.measure("scenario_total", scenario="upgrade"):
        with timings.measure("fixture", scenario="upgrade", journey=1):
            baseline = fixture_wheel(source, tmp_path / "baseline", "0.3.5", feed=tmp_path / "feed.json")
        # Evidence is available before the outer context exits.
        checkpoint = json.loads(output.read_text())
        assert checkpoint["clock"] == "perf_counter"
        assert checkpoint["schema_version"] == 1
        assert len(checkpoint["timings"]) == 1
        assert checkpoint["timings"][0]["phase"] == "fixture"
        assert baseline.exists()
        for number in (1, 2):
            with timings.measure("verify", scenario="upgrade", journey=number):
                assert digest(source) != digest(baseline)
    records = json.loads(output.read_text())["timings"]
    assert [(row["phase"], row["journey"]) for row in records] == [
        ("fixture", 1), ("verify", 1), ("verify", 2), ("scenario_total", None)]
    assert all(row["status"] == "succeeded" and row["seconds"] >= 0 for row in records)
    assert records[-1]["seconds"] >= sum(row["seconds"] for row in records[:-1])
    assert not (tmp_path / "result.json").exists()
    assert not (tmp_path / "packaged-update-report.json").exists()
    stdout = capsys.readouterr().out
    assert "TIMING upgrade/1/fixture:" in stdout
    assert "TIMING upgrade/2/verify:" in stdout
    assert "TIMING upgrade/scenario_total:" in stdout


@pytest.mark.parametrize("failure", ["exit", "timeout", "assertion"])
def test_timings_persist_failure_and_finally_cleanup_without_exporting_secrets(tmp_path, capsys, failure):
    output = tmp_path / "packaged-update-timings.json"
    timings = Timings(output)
    secret = "sensitive-token-must-stay-local"
    error = {"exit": subprocess.CalledProcessError, "timeout": subprocess.TimeoutExpired,
             "assertion": AssertionError}[failure]
    with pytest.raises(error):
        with timings.measure("scenario_total", scenario="restart-failure"):
            try:
                with timings.measure("worker", scenario="restart-failure", journey=2):
                    if failure == "assertion":
                        raise AssertionError(secret)
                    command = ("raise SystemExit(91)" if failure == "exit" else "import time; time.sleep(30)")
                    subprocess.run([sys.executable, "-I", "-c", command, secret], check=True,
                                   capture_output=True, timeout=0.1 if failure == "timeout" else 10)
            finally:
                with timings.measure("cleanup", scenario="restart-failure"):
                    # Read the failed phase from disk before cleanup completes.
                    assert json.loads(output.read_text())["timings"][0]["status"] == "failed"
                    (tmp_path / "cleaned").touch()
    assert (tmp_path / "cleaned").exists()
    document = output.read_text()
    records = json.loads(document)["timings"]
    assert [(row["phase"], row["status"]) for row in records] == [
        ("worker", "failed"), ("cleanup", "succeeded"), ("scenario_total", "failed")]
    assert all(row["seconds"] >= 0 for row in records)
    assert records[-1]["seconds"] >= sum(row["seconds"] for row in records[:-1])
    assert secret not in document
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "TIMING restart-failure/2/worker:" in captured.out
    assert "TIMING restart-failure/scenario_total:" in captured.out


def test_worker_count_must_be_positive_before_creating_output(tmp_path):
    script = Path(probe.__file__).resolve()
    output = tmp_path / "must-not-exist"
    result = subprocess.run([sys.executable, "-I", str(script), "--output", str(output), "--workers", "0"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and "--workers" in result.stderr
    assert not output.exists()


def test_lanes_balance_all_nine_scenarios_without_splitting_fifteen_journeys():
    scenarios = list(probe.SCENARIOS)
    assert probe.scenario_groups(scenarios, 1) == [scenarios]
    groups = probe.scenario_groups(scenarios, 2)
    assert groups == [
        ["upgrade", "skipped-preview", "import-failure", "backup-failure", "restore-interruption"],
        ["upgrade-again", "restart-failure", "worker-exit", "metadata-loss"],
    ]
    assert sorted(scenario for group in groups for scenario in group) == sorted(scenarios)
    assert [sum(1 + (scenario in probe.TWO_JOURNEY_SCENARIOS) for scenario in group) for group in groups] == [8, 7]
    assert probe.scenario_groups(["metadata-loss"], 2) == [["metadata-loss"]]
    for workers in (3, 4):
        groups = probe.scenario_groups(scenarios, workers)
        assert len(groups) == workers
        assert sorted(scenario for group in groups for scenario in group) == sorted(scenarios)
        assert sum(1 + (scenario in probe.TWO_JOURNEY_SCENARIOS)
                   for group in groups for scenario in group) == 15


def parallel_controller(tmp_path, monkeypatch, *, mode="success"):
    """Real stdlib-only controllers exercise orchestration, not native acceptance."""
    script = tmp_path / "fake_controller.py"
    script.write_text(f"MODE = {mode!r}\nTWO = {sorted(probe.TWO_JOURNEY_SCENARIOS)!r}\n" + textwrap.dedent('''\
        import argparse
        import hashlib
        import json
        import os
        import subprocess
        import sys
        import time
        from pathlib import Path

        parser = argparse.ArgumentParser()
        parser.add_argument("--wheel", type=Path)
        parser.add_argument("--commit")
        parser.add_argument("--output", type=Path)
        parser.add_argument("--workers", type=int)
        parser.add_argument("--scenario", action="append")
        parser.add_argument("--baseline-wheel")
        parser.add_argument("--dock", action="store_true")
        args = parser.parse_args()
        output, lane = args.output, args.output.parent
        output.mkdir()
        worker = int(lane.name[-1])
        def write(path, value):
            path.write_text(json.dumps(value), encoding="utf-8")
        keys = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
                "XDG_DATA_HOME", "XDG_CACHE_HOME", "TMPDIR", "TMP", "TEMP", "PIP_INDEX_URL")
        write(lane / "environment.json", {"env": {key: os.environ.get(key) for key in keys},
              "workers": args.workers, "baseline_wheel": args.baseline_wheel,
              "isolated": sys.flags.isolated, "no_bytecode": sys.flags.dont_write_bytecode, "pid": os.getpid()})
        (lane / "ready").touch()
        # A serial parent would time out here instead of ever starting lane 2.
        deadline = time.monotonic() + 8
        while not all((lane.parent / f"lane-{number}/ready").exists() for number in (1, 2)):
            if time.monotonic() > deadline:
                raise RuntimeError("Controllers did not overlap")
            time.sleep(0.02)
        secret = "temporary-api-token-must-stay-in-private-logs"
        print(secret, flush=True)
        print(secret, file=sys.stderr, flush=True)
        write(output / "packaged-update-timings.json", {"schema_version": 1, "clock": "perf_counter",
              "timings": [{"phase": "fixture", "scenario": args.scenario[0], "journey": 1,
                           "seconds": 0.01, "status": "failed" if MODE == "exit" and worker == 1 else "succeeded"}]})
        if MODE == "timeout" or (MODE == "exit-with-child" and worker == 1):
            # The descendant owns a real listener, even if its controller exits.
            child = "import json, socket, sys, time; from pathlib import Path; " \
                    "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(); " \
                    "Path(sys.argv[1]).write_text(json.dumps(s.getsockname()[1])); " \
                    "deadline = time.monotonic() + 60; " \
                    "exec('while time.monotonic() < deadline and not Path(sys.argv[2]).exists(): time.sleep(0.02)')"
            subprocess.Popen([sys.executable, "-I", "-c", child,
                              str(lane / "listener.json"), str(lane / "stop-listener")])
            if MODE == "exit-with-child":
                deadline = time.monotonic() + 8
                while not (lane / "listener.json").exists():
                    if time.monotonic() > deadline:
                        raise RuntimeError("Descendant listener did not start")
                    time.sleep(0.02)
                raise SystemExit(92)
            time.sleep(60)
        if MODE == "exit" and worker == 1:
            raise SystemExit(91)
        if worker == 1:
            time.sleep(0.2)
        results = []
        for scenario in args.scenario:
            result = {"scenario": scenario, "phase": "succeeded"}
            if scenario in TWO:
                result["subsequent_update"] = {"scenario": "upgrade", "phase": "succeeded"}
            if MODE == "missing-journey" and scenario == "import-failure":
                del result["subsequent_update"]
            case = output / scenario
            case.mkdir()
            write(case / "result.json", result)
            results.append(result)
        write(output / "packaged-update-report.json", {
            "target_sha256": "0" * 64 if MODE == "wrong-hash" else hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
            "candidate_commit": args.commit, "version": "0.3.6", "scenarios": results})
        (lane / "finished").write_text(str(time.monotonic()))
        '''), encoding="utf-8")
    monkeypatch.setattr(probe, "__file__", str(script))
    target = wheel(tmp_path, "0.3.6")
    baseline = wheel(tmp_path, "0.3.5")
    root = tmp_path / "evidence"
    root.mkdir()
    args = Namespace(wheel=target, baseline_wheel=baseline, output=root, commit="a" * 40,
                     workers=2, dock=False, scenario=None)
    return args, root, Timings(root / "packaged-update-timings.json")


def test_parallel_controllers_isolate_accounts_and_merge_in_scenario_order(tmp_path, monkeypatch, capsys):
    args, root, timings = parallel_controller(tmp_path, monkeypatch)
    monkeypatch.setenv("PIP_INDEX_URL", "https://user:private-credential@example.invalid")
    original_hash = digest(args.wheel)
    results = probe.run_parallel(args, root, args.wheel, "0.3.6", original_hash, list(probe.SCENARIOS), timings)
    assert [result["scenario"] for result in results] == list(probe.SCENARIOS)
    assert sum(1 + ("subsequent_update" in result) for result in results) == 15
    assert digest(args.wheel) == original_hash
    assert float((root / "lane-2/finished").read_text()) < float((root / "lane-1/finished").read_text())
    controllers = [json.loads((root / f"lane-{number}/environment.json").read_text()) for number in (1, 2)]
    assert controllers[0]["pid"] != controllers[1]["pid"]
    for number, controller in enumerate(controllers, 1):
        assert controller["workers"] == 1 and controller["isolated"] and controller["no_bytecode"]
        assert controller["baseline_wheel"] == str(args.baseline_wheel.resolve())
        for key, value in controller["env"].items():
            if key == "PIP_INDEX_URL":
                assert value is None
            else:
                assert Path(value).is_relative_to(root / f"lane-{number}")
    checkpoint = (root / "packaged-update-timings.json").read_text()
    records = json.loads(checkpoint)["timings"]
    assert [record.get("worker") for record in records] == [1, 2, None]
    assert records[-1]["phase"] == "parallel_total" and records[-1]["status"] == "succeeded"
    assert all(record["seconds"] >= 0 for record in records)
    captured = capsys.readouterr()
    assert "temporary-api-token" not in checkpoint + captured.out + captured.err
    assert "private-credential" not in checkpoint + captured.out + captured.err
    assert "temporary-api-token" in (root / "lane-1/controller.log").read_text()


def test_parallel_failure_is_real_and_allows_other_lane_to_finish_cleanup(tmp_path, monkeypatch, capsys):
    args, root, timings = parallel_controller(tmp_path, monkeypatch, mode="exit")
    with pytest.raises(RuntimeError, match="lane failed"):
        probe.run_parallel(args, root, args.wheel, "0.3.6", digest(args.wheel), list(probe.SCENARIOS), timings)
    assert (root / "lane-2/finished").exists()
    records = json.loads(timings.output.read_text())["timings"]
    assert [(record.get("worker"), record["status"]) for record in records] == [
        (1, "failed"), (2, "succeeded"), (None, "failed")]
    assert not (root / "packaged-update-report.json").exists()
    captured = capsys.readouterr()
    assert "status 91" in captured.out
    assert "temporary-api-token" not in timings.output.read_text() + captured.out + captured.err


def test_parallel_deadline_kills_owned_controller_trees_and_their_listeners(tmp_path, monkeypatch, capsys):
    from scripts.verify_installed_release import _wait_for_closed_listeners

    args, root, timings = parallel_controller(tmp_path, monkeypatch, mode="timeout")
    monkeypatch.setattr(probe, "LANE_TIMEOUT", 5)
    with pytest.raises(RuntimeError, match="lane failed"):
        probe.run_parallel(args, root, args.wheel, "0.3.6", digest(args.wheel), list(probe.SCENARIOS), timings)
    ports = tuple(json.loads((root / f"lane-{number}/listener.json").read_text()) for number in (1, 2))
    _wait_for_closed_listeners(ports)
    assert json.loads(timings.output.read_text())["timings"][-1]["status"] == "failed"
    captured = capsys.readouterr()
    assert "deadline exceeded" in captured.out
    assert "temporary-api-token" not in timings.output.read_text() + captured.out + captured.err


def test_exited_controller_cannot_leave_a_descendant_listener_running(tmp_path, monkeypatch):
    from scripts.verify_installed_release import _wait_for_closed_listeners

    args, root, timings = parallel_controller(tmp_path, monkeypatch, mode="exit-with-child")
    listener = root / "lane-1/listener.json"
    try:
        with pytest.raises(RuntimeError, match="lane failed"):
            probe.run_parallel(args, root, args.wheel, "0.3.6", digest(args.wheel), list(probe.SCENARIOS), timings)
        _wait_for_closed_listeners((json.loads(listener.read_text()),))
    finally:
        # A red baseline must not leak the process it deliberately exposed.
        (root / "lane-1/stop-listener").touch()
        if listener.exists():
            _wait_for_closed_listeners((json.loads(listener.read_text()),))


@pytest.mark.parametrize("mode,message", [("wrong-hash", "original candidate"), ("missing-journey", "every required")])
def test_parallel_reports_must_prove_original_hash_and_complete_journey_coverage(tmp_path, monkeypatch, mode, message):
    args, root, timings = parallel_controller(tmp_path, monkeypatch, mode=mode)
    with pytest.raises(ValueError, match=message):
        probe.run_parallel(args, root, args.wheel, "0.3.6", digest(args.wheel), list(probe.SCENARIOS), timings)
    assert json.loads(timings.output.read_text())["timings"][-1]["status"] == "failed"


@pytest.mark.parametrize("stop_failure", [False, True])
def test_abnormal_lane_cleanup_does_not_depend_on_the_mutable_venv(tmp_path, monkeypatch, stop_failure):
    root = tmp_path / "lane-1/run"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    configs = []
    for scenario in ("upgrade", "metadata-loss"):
        config = root / scenario / "account/.nanobot/config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"gateway": {"port": port}, "channels": {"websocket": {"port": port}}}))
        configs.append(config)
    calls = []
    def stop(command, **kwargs):
        calls.append((command, kwargs))
        if stop_failure and len(calls) == 1:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(probe.subprocess, "run", stop)
    if stop_failure:
        with pytest.raises(RuntimeError, match="bounded cleanup"):
            probe.cleanup_lane(root, ["upgrade", "worker-exit", "metadata-loss"])
    else:
        probe.cleanup_lane(root, ["upgrade", "worker-exit", "metadata-loss"])
    assert len(calls) == 2  # Still try the second account if the first stop failed.
    for (command, options), config in zip(calls, configs, strict=True):
        assert command == [sys.executable, "-I", "-B", "-m", "nanobot", "gateway", "stop", "--config", str(config)]
        assert options["env"]["HOME"] == str(config.parent.parent) and options["cwd"] == config.parents[2]
        assert options["check"] and options["timeout"] == 60
        assert options["stdout"] is options["stderr"]
    assert not (root / "managed").exists()


@pytest.mark.parametrize("workers", [1, 2])
def test_serial_dispatch_reports_one_lane_and_checks_original_hash_at_the_end(tmp_path, monkeypatch, workers):
    import scripts.build_tui_wheels

    target = wheel(tmp_path, "0.3.6")
    monkeypatch.setattr(scripts.build_tui_wheels, "wheel_files", lambda *args, **kwargs: (
        {"nanobot/_build_commit.txt": b"a" * 40}, None, None))
    args = Namespace(wheel=target, baseline_wheel=None, output=tmp_path / "serial", commit="a" * 40,
                     workers=workers, dock=False, scenario=["upgrade"])
    calls = []
    def serial(args, root, selected, version, original_hash, scenarios, timings):
        calls.append(root / "managed")
        return [{"scenario": "upgrade"}]
    monkeypatch.setattr(probe, "run_serial", serial)
    report = probe.run(args)
    assert calls == [args.output / "managed"]
    assert (report["workers"], report["scenario_count"], report["journey_count"]) == (1, 1, 1)
    args.output = tmp_path / "mutated"
    def mutate(*args):
        target.write_bytes(b"changed target")
        return [{"scenario": "upgrade"}]
    monkeypatch.setattr(probe, "run_serial", mutate)
    with pytest.raises(AssertionError):
        probe.run(args)


def test_controller_error_does_not_print_exception_values_or_commands(tmp_path):
    secret = "temporary-credential-must-not-appear"
    target = tmp_path / (secret + ".whl")
    result = subprocess.run([sys.executable, "-I", str(Path(probe.__file__).resolve()), "--wheel", str(target),
                             "--commit", "a" * 40, "--output", str(tmp_path / "evidence")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and "FileNotFoundError" in result.stderr
    assert secret not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("version,baseline_version", [
    ("0.3.6", None), ("0.4.0", None), ("1.0.0", None), ("0.4.0", "0.3.5"),
])
def test_serial_lanes_install_dependencies_once_and_keep_recovery_chains_on_the_same_venv(
    tmp_path, monkeypatch, version, baseline_version,
):
    package = Path(__file__).resolve().parents[1] / "nanobot"
    target = wheel(tmp_path, version, worker=(package / "update_worker.py").read_bytes(),
                   fallback=(package / "update_fallback.py").read_bytes())
    baseline = (wheel(tmp_path, baseline_version, worker=(package / "update_worker.py").read_bytes(),
                      fallback=(package / "update_fallback.py").read_bytes()) if baseline_version else None)
    original_hash = digest(target)
    installations, dependencies, baselines, stages = [], [], [], {}
    def execute(command, **options):
        if "venv" in command:
            installations.append(Path(command[-1]))
            Path(command[-1]).mkdir()
        elif "pip" in command:
            (baselines if "--no-deps" in command else dependencies).append(command[0])
        elif "--phase" in command:
            phase = command[command.index("--phase") + 1]
            case_root = Path(command[command.index("--output") + 1])
            rows = stages.setdefault(case_root, [])
            rows.append((phase, command[0]))
            if phase == "prepare":
                number = sum(stage == "prepare" for stage, _ in rows)
                job = case_root / f"job-{number}"
                job.mkdir()
                probe.write(case_root / "launch.json", {"directory": str(job),
                            "command": ["fixture-worker", str(case_root), command[0]]})
            else:
                case = probe.read(case_root / "case.json")
                restored = case["scenario"] in probe.TWO_JOURNEY_SCENARIOS and case["scenario"] != "upgrade-again"
                probe.write(case_root / "result.json", {
                    **case, "phase": "restored" if restored else "succeeded",
                    "running_version": case["baseline_version"] if restored else case["target_version"],
                })
        elif command[0] == "fixture-worker":
            stages[Path(command[1])].append(("worker", command[2]))
        elif "gateway" in command:
            case_root = Path(command[-1]).parents[2]
            stages[case_root].append(("cleanup", command[0]))
        else:
            pytest.fail("Unexpected verifier subprocess")
    monkeypatch.setattr(probe.subprocess, "run", execute)
    results = []
    for worker, scenarios in enumerate(probe.scenario_groups(list(probe.SCENARIOS), 2), 1):
        root = tmp_path / f"lane-{worker}/run"
        root.mkdir(parents=True)
        args = Namespace(baseline_wheel=baseline, commit="a" * 40, dock=False)
        results.extend(probe.run_serial(args, root, target, version, original_hash, scenarios,
                                        Timings(root / "packaged-update-timings.json")))
    assert len(installations) == len(dependencies) == 2 and len(set(installations)) == 2
    assert len(baselines) == 9 and len(stages) == 9
    assert sum(1 + ("subsequent_update" in result) for result in results) == 15
    assert digest(target) == original_hash
    upgrade = next(result for result in results if result["scenario"] == "upgrade")
    assert upgrade["baseline_source_sha256"] == digest(baseline or target)
    assert upgrade["target_version"] == version
    if baseline_version:
        assert upgrade["baseline_version"] == baseline_version
        assert upgrade["baseline_kind"] == "instrumented historical wheel"
    for case_root, rows in stages.items():
        journeys = 1 + (case_root.name in probe.TWO_JOURNEY_SCENARIOS)
        assert [stage for stage, _ in rows] == ["prepare", "worker", "verify"] * journeys + ["cleanup"]
        interpreters = {python for _, python in rows}
        assert len(interpreters) == 1
        assert Path(next(iter(interpreters))).is_relative_to(case_root.parent / "managed")
