"""Pure lease-scope checks for protected gateway startup; no updater is executed."""

import sys
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace

import pytest

from nanobot import update_process
from nanobot.utils.restart import ProcessRestart


def test_protected_runtime_restart_releases_child_leases_before_replacement(monkeypatch):
    events = []
    leases = ExitStack()
    monkeypatch.setattr(update_process, "child_leases", leases)

    @contextmanager
    def lease(name):
        try:
            yield
        finally:
            events.append(name + " released")

    leases.enter_context(lease("installation"))
    leases.enter_context(lease("data"))
    with update_process.runtime_restart_scope():
        try:
            raise ProcessRestart(lambda: events.append("replacement"))
        finally:
            events.append("runtime closed")

    assert events == ["runtime closed", "data released", "installation released", "replacement"]


@pytest.mark.parametrize("error", [None, SystemExit(0), RuntimeError("startup failed")])
def test_ordinary_protected_exit_keeps_child_leases_for_exit_callbacks(monkeypatch, error):
    events = []
    leases = ExitStack()
    leases.callback(lambda: events.append("lease released"))
    monkeypatch.setattr(update_process, "child_leases", leases)

    def run():
        with update_process.runtime_restart_scope():
            if error is not None:
                raise error

    try:
        if error is None:
            run()
        else:
            with pytest.raises(type(error)) as result:
                run()
            assert result.value is error
        assert events == []
    finally:
        leases.close()
    assert events == ["lease released"]


def test_protected_gateway_entrypoint_releases_its_child_lease_before_restart(monkeypatch, tmp_path):
    from nanobot import update_worker

    events = []
    leases = ExitStack()
    monkeypatch.setattr(update_process, "child_leases", leases)
    monkeypatch.setattr(update_worker, "child_leases", leases)
    spec = SimpleNamespace(restart_profiles=("profile",),
                           baseline=SimpleNamespace(python="python", environment="environment"))
    monkeypatch.setattr(update_worker.WorkerSpec, "read", lambda _path: spec)
    monkeypatch.setattr(update_worker, "require_pending_owner", lambda _spec: None)
    monkeypatch.setattr(update_worker, "initialize_runtime", lambda *_args: events.append("runtime initialized"))

    @contextmanager
    def installation(**_kwargs):
        events.append("installation acquired")
        try:
            yield
        finally:
            events.append("installation released")

    def run_gateway(directory, participant):
        assert (directory, participant) == (tmp_path, "profile")
        events.append("runtime closed")
        raise ProcessRestart(lambda: events.append("replacement"))

    monkeypatch.setattr(update_worker, "installation_access", installation)
    monkeypatch.setitem(sys.modules, "nanobot.update_restart", SimpleNamespace(
        run_gateway=run_gateway, run_restarts=lambda _path: pytest.fail("Not the gateway path"),
    ))

    try:
        update_worker._runtime_child(tmp_path, "profile")
        assert events == ["installation acquired", "runtime initialized", "runtime closed",
                          "installation released", "replacement"]
    finally:
        leases.close()
