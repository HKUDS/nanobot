"""Keep acceptance evidence honest: real target bytes and fail-closed fixtures."""

import asyncio
import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import httpx
import pytest

from nanobot.release_feed import ReleaseFeed
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
