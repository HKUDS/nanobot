import json
from pathlib import Path

from nanobot.runtime_health import RuntimeHealthState


def test_runtime_health_tracks_active_dispatches(tmp_path: Path) -> None:
    state_path = tmp_path / "runtime-health.json"
    state = RuntimeHealthState(path=state_path, min_write_interval_s=999)

    state.mark_dispatch_start("telegram:1")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["active_dispatches"] == 1
    assert isinstance(payload["oldest_dispatch_started_at"], float)

    state.mark_dispatch_end("telegram:1")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["active_dispatches"] == 0
    assert payload["oldest_dispatch_started_at"] is None


def test_runtime_health_tracks_outbound_send(tmp_path: Path) -> None:
    state_path = tmp_path / "runtime-health.json"
    state = RuntimeHealthState(path=state_path, min_write_interval_s=999)

    state.mark_outbound_send_start(channel="telegram")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["outbound_active"] == 1
    assert payload["outbound_channel"] == "telegram"

    state.mark_outbound_send_ok(channel="telegram")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["outbound_active"] == 0
    assert payload["last_outbound_error"] == ""
