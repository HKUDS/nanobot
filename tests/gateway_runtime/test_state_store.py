import threading
from pathlib import Path

from nanobot.gateway_runtime.state_store import (
    GatewayStateStore,
    build_gateway_instance_key,
)


def test_write_and_read_state_round_trip(tmp_path) -> None:
    store = GatewayStateStore(data_dir=tmp_path)

    payload = {
        "mode": "foreground_legacy",
        "started_at": "2026-03-03T10:00:00Z",
        "reason": "rollout_off",
    }
    store.write_state(payload)

    assert store.read_state() == payload


def test_read_state_recovers_from_corrupted_file(tmp_path) -> None:
    store = GatewayStateStore(data_dir=tmp_path)
    state_path = store.state_path
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{broken-json", encoding="utf-8")

    result = store.read_state()

    assert result is None
    assert state_path.exists()


def test_write_read_and_clear_pid(tmp_path) -> None:
    store = GatewayStateStore(data_dir=tmp_path)

    store.write_pid(4321)
    assert store.read_pid() == 4321

    store.clear_pid()
    assert store.read_pid() is None


def test_resolve_log_path_creates_expected_location(tmp_path) -> None:
    store = GatewayStateStore(data_dir=tmp_path)

    log_path = store.resolve_log_path()

    assert log_path == tmp_path / "logs" / "gateway.log"
    assert log_path.parent.exists()


def test_read_pid_returns_none_for_invalid_content(tmp_path) -> None:
    store = GatewayStateStore(data_dir=tmp_path)
    store.pid_path.parent.mkdir(parents=True, exist_ok=True)
    store.pid_path.write_text("not-a-number", encoding="utf-8")

    assert store.read_pid() is None


def test_write_state_uses_atomic_replace(tmp_path, monkeypatch) -> None:
    store = GatewayStateStore(data_dir=tmp_path)
    old_state = {"mode": "foreground_legacy", "reason": "rollout_off"}
    new_state = {"mode": "foreground_legacy", "reason": "cli_override_foreground"}
    store.write_state(old_state)

    replace_reached = threading.Event()
    allow_replace = threading.Event()
    original_replace = Path.replace

    def slow_replace(self: Path, target: Path):  # type: ignore[override]
        replace_reached.set()
        allow_replace.wait(timeout=2)
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", slow_replace)

    thread = threading.Thread(target=store.write_state, args=(new_state,))
    thread.start()

    assert replace_reached.wait(timeout=2)
    # While writer is blocked before replace, readers should still see old state.
    assert store.read_state() == old_state

    allow_replace.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

    assert store.read_state() == new_state


def test_build_instance_key_is_deterministic_and_input_sensitive() -> None:
    key_a1 = build_gateway_instance_key(
        workspace="/tmp/work-a",
        config_path="/tmp/cfg-a.json",
    )
    key_a2 = build_gateway_instance_key(
        workspace="/tmp/work-a",
        config_path="/tmp/cfg-a.json",
    )
    key_b = build_gateway_instance_key(
        workspace="/tmp/work-b",
        config_path="/tmp/cfg-a.json",
    )

    assert key_a1 is not None
    assert key_a1 == key_a2
    assert key_a1 != key_b
    assert build_gateway_instance_key() is None


def test_instance_scoped_runtime_files_do_not_collide(tmp_path) -> None:
    key_a = build_gateway_instance_key(
        workspace="/tmp/work-a",
        config_path="/tmp/cfg-a.json",
    )
    key_b = build_gateway_instance_key(
        workspace="/tmp/work-b",
        config_path="/tmp/cfg-b.json",
    )
    assert key_a is not None
    assert key_b is not None

    store_a = GatewayStateStore(data_dir=tmp_path, instance_key=key_a)
    store_b = GatewayStateStore(data_dir=tmp_path, instance_key=key_b)

    store_a.write_pid(1111)
    store_b.write_pid(2222)
    store_a.write_state({"instance": "a"})
    store_b.write_state({"instance": "b"})

    assert store_a.read_pid() == 1111
    assert store_b.read_pid() == 2222
    assert store_a.read_state() == {"instance": "a"}
    assert store_b.read_state() == {"instance": "b"}
    assert store_a.pid_path != store_b.pid_path
    assert store_a.state_path != store_b.state_path
    assert store_a.resolve_log_path() != store_b.resolve_log_path()
