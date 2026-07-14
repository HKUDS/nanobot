import json
import os
import socket
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.config.loader import load_config
from nanobot.config.repository import ConfigConflictError, FileConfigRepository
from nanobot.security.network import configure_ssrf_whitelist, validate_url_target


def _fake_resolve(host: str, results: list[str]):
    def _resolver(hostname, port, family=0, type_=0):
        if hostname == host:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))
                for ip in results
            ]
        raise socket.gaierror(f"cannot resolve {hostname}")

    return _resolver


def test_raw_and_effective_snapshots_keep_secret_templates_separate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"providers": {"groq": {"apiKey": "${GROQ_TOKEN}"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_TOKEN", "resolved-secret")
    repository = FileConfigRepository(path)

    raw = repository.load_raw()
    effective = repository.load_effective()

    assert raw.config.providers.groq.api_key == "${GROQ_TOKEN}"
    assert effective.config.providers.groq.api_key == "resolved-secret"
    assert effective.config is not raw.config
    assert effective.revision == raw.revision


def test_update_uses_latest_raw_config_and_reports_changed_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"providers": {"groq": {"apiKey": "${GROQ_TOKEN}"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_TOKEN", "resolved-secret")
    repository = FileConfigRepository(path)

    commit = repository.update(
        lambda config: setattr(config.agents.defaults, "timezone", "Asia/Shanghai")
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["providers"]["groq"]["apiKey"] == "${GROQ_TOKEN}"
    assert saved["agents"]["defaults"]["timezone"] == "Asia/Shanghai"
    assert commit.before.revision != commit.after.revision
    assert commit.changed_paths == frozenset({"agents.defaults.timezone"})


def test_update_rejects_stale_expected_revision(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    repository = FileConfigRepository(path)
    initial = repository.load_raw()
    repository.update(lambda config: setattr(config.api, "port", 9001))

    with pytest.raises(ConfigConflictError, match="Config changed"):
        repository.update(
            lambda config: setattr(config.api, "port", 9002),
            expected_revision=initial.revision,
        )

    assert repository.load_raw().config.api.port == 9001


def test_repositories_for_same_path_serialize_threaded_updates(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    first = FileConfigRepository(path)
    second = FileConfigRepository(path)
    first_mutator_entered = threading.Event()
    release_first = threading.Event()
    second_mutator_entered = threading.Event()

    def update_first() -> None:
        def mutate(config):
            first_mutator_entered.set()
            assert release_first.wait(timeout=5)
            config.api.port = 9001

        first.update(mutate)

    def update_second() -> None:
        def mutate(config):
            second_mutator_entered.set()
            config.agents.defaults.timezone = "Asia/Shanghai"

        second.update(mutate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(update_first)
        assert first_mutator_entered.wait(timeout=5)
        second_future = pool.submit(update_second)
        assert not second_mutator_entered.wait(timeout=0.1)
        release_first.set()
        first_future.result(timeout=5)
        second_future.result(timeout=5)

    config = first.load_raw().config
    assert config.api.port == 9001
    assert config.agents.defaults.timezone == "Asia/Shanghai"


def test_repositories_for_different_paths_are_isolated(tmp_path: Path) -> None:
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first = FileConfigRepository(first_path)
    second = FileConfigRepository(second_path)

    first.update(lambda config: setattr(config.api, "port", 9001))
    second.update(lambda config: setattr(config.api, "port", 9002))

    assert first.load_raw().config.api.port == 9001
    assert second.load_raw().config.api.port == 9002
    assert json.loads(first_path.read_text(encoding="utf-8"))["api"]["port"] == 9001
    assert json.loads(second_path.read_text(encoding="utf-8"))["api"]["port"] == 9002


def test_noop_update_keeps_revision_and_does_not_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    repository = FileConfigRepository(path)
    repository.update(lambda config: setattr(config.api, "port", 9001))
    before = repository.load_raw()

    commit = repository.update(lambda config: setattr(config.api, "port", 9001))

    assert commit.changed_paths == frozenset()
    assert commit.before.revision == before.revision
    assert commit.after.revision == before.revision


def test_atomic_save_keeps_previous_file_when_replace_fails(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"api": {"port": 9000}}', encoding="utf-8")
    repository = FileConfigRepository(path)

    with patch("nanobot.config.repository.os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            repository.update(lambda config: setattr(config.api, "port", 9001))

    assert json.loads(path.read_text(encoding="utf-8"))["api"]["port"] == 9000
    assert list(tmp_path.glob(".config.json.*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX file modes")
def test_atomic_save_preserves_existing_file_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"api": {"port": 9000}}', encoding="utf-8")
    path.chmod(0o600)

    FileConfigRepository(path).update(lambda config: setattr(config.api, "port", 9001))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_atomic_save_restores_mode_before_writing(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"api": {"port": 9000}}', encoding="utf-8")
    path.chmod(0o600)
    observed_sizes: list[int] = []
    real_chmod = os.chmod

    def capture_size_before_chmod(target: str | bytes | Path, mode: int) -> None:
        observed_sizes.append(Path(target).stat().st_size)
        real_chmod(target, mode)

    monkeypatch.setattr("nanobot.config.repository.os.chmod", capture_size_before_chmod)

    FileConfigRepository(path).update(lambda config: setattr(config.api, "port", 9001))

    assert observed_sizes == [0]


@pytest.mark.skipif(os.name == "nt", reason="Windows handles chmod differently")
def test_atomic_save_keeps_previous_file_when_mode_restore_fails(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"api": {"port": 9000}}', encoding="utf-8")
    path.chmod(0o600)

    with patch("nanobot.config.repository.os.chmod", side_effect=OSError("chmod failed")):
        with pytest.raises(OSError, match="chmod failed"):
            FileConfigRepository(path).update(
                lambda config: setattr(config.api, "port", 9001)
            )

    assert json.loads(path.read_text(encoding="utf-8"))["api"]["port"] == 9000
    assert list(tmp_path.glob(".config.json.*.tmp")) == []


def test_loading_config_does_not_change_process_network_policy(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tools": {"ssrfWhitelist": []}}), encoding="utf-8")
    configure_ssrf_whitelist(["100.64.0.0/10"])
    try:
        load_config(path)

        with patch(
            "nanobot.security.network.socket.getaddrinfo",
            _fake_resolve("ts.local", ["100.100.1.1"]),
        ):
            ok, error = validate_url_target("http://ts.local/api")
            assert ok, error
    finally:
        configure_ssrf_whitelist([])
