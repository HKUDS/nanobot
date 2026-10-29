"""Restart launch contracts, with process replacement always intercepted."""

import os
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nanobot.gateway.restart import GatewayRestartPlan, claim_restarted_background
from nanobot.gateway.runtime import (
    GatewayAlreadyRunningError,
    GatewayClientLease,
    GatewayRuntime,
    GatewayRuntimePaths,
    GatewayStartOptions,
    build_gateway_command,
)
from nanobot.utils.restart import replace_process
from nanobot.utils.rotating_output import BACKGROUND_LOG_PATH_ENV


@pytest.fixture
def plan(tmp_path):
    return GatewayRestartPlan(
        options=GatewayStartOptions(
            home=str(tmp_path / "home"), config_path=str(tmp_path / "profile" / "config.json"),
            workspace=str(tmp_path / "workspace"), port=19321, verbose=True,
        ),
        paths=GatewayRuntimePaths.for_instance(data_dir=tmp_path / "profile"),
        cwd=tmp_path, launch_mode="foreground", lifetime="explicit", mode="exec",
    )


@pytest.mark.parametrize("mode", ["exec", "spawn"])
def test_foreground_restart_uses_gateway_selectors_not_update_argv(monkeypatch, plan, mode):
    monkeypatch.setattr(sys, "argv", ["worker.pyz", "--gateway", "one-use-job", "participant"])
    monkeypatch.setenv("NANOBOT_UPDATE_STARTUP_TOKEN", "one-use-grant")
    monkeypatch.setenv("EXISTING_CONFIG_ENV", "retained")
    launch = Mock()
    monkeypatch.setattr("nanobot.gateway.restart.replace_process", launch)

    replace(plan, mode=mode).execute()

    argv, = launch.call_args.args
    assert argv == build_gateway_command(sys.executable, plan.options)
    assert launch.call_args.kwargs["cwd"] == plan.cwd
    assert launch.call_args.kwargs["mode"] == mode
    environment = launch.call_args.kwargs["env"]
    assert environment["EXISTING_CONFIG_ENV"] == "retained"
    assert "NANOBOT_UPDATE_STARTUP_TOKEN" not in environment


@pytest.mark.parametrize(
    ("platform", "mode", "action"),
    [("win32", "auto", "spawn"), ("linux", "auto", "exec"),
     ("win32", "exec", "exec"), ("linux", "spawn", "spawn"),
     ("win32", "exit", "exit")],
)
def test_restart_modes_replace_only_at_the_explicit_execution_boundary(
    monkeypatch, tmp_path, platform, mode, action,
):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    spawn, execute, chdir = Mock(), Mock(), Mock()
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(os, "execve", execute)
    monkeypatch.setattr(os, "chdir", chdir)
    argv = [sys.executable, "-m", "nanobot", "gateway", "--foreground"]

    replace_process(argv, mode=mode, cwd=tmp_path, env={"ENV": "value"})

    if action == "spawn":
        expected = {"creationflags": 512} if platform == "win32" else {}
        spawn.assert_called_once_with(argv, cwd=tmp_path, env={"ENV": "value"}, **expected)
        execute.assert_not_called()
    elif action == "exec":
        chdir.assert_called_once_with(tmp_path)
        execute.assert_called_once_with(argv[0], argv, {"ENV": "value"})
        spawn.assert_not_called()
    else:
        spawn.assert_not_called()
        execute.assert_not_called()
        chdir.assert_not_called()


def _runtime_with_fake_processes(monkeypatch, plan):
    monkeypatch.setattr(GatewayRuntime, "_is_pid_running", lambda _self, _pid: True)
    monkeypatch.setattr(GatewayRuntime, "_process_identity", lambda _self, pid: f"identity-{pid}")
    runtime = GatewayRuntime(paths=plan.paths, sleep=lambda _seconds: None)
    factory = GatewayRuntime
    monkeypatch.setattr(
        "nanobot.gateway.restart.GatewayRuntime",
        lambda **kwargs: factory(**kwargs, sleep=lambda _seconds: None),
    )
    return runtime


@pytest.mark.parametrize("lifetime", ["explicit", "on_demand"])
def test_background_spawn_retains_launch_mode_and_client_leases(monkeypatch, plan, lifetime):
    runtime = _runtime_with_fake_processes(monkeypatch, plan)
    client = GatewayClientLease(runtime, kind="tui", pid=1234, token="existing-client")
    client.acquire()
    if lifetime == "on_demand":
        client.mark_ephemeral()
    spawn = Mock(return_value=SimpleNamespace(pid=5678))
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setenv("NANOBOT_UPDATE_STARTUP_TOKEN", "one-use-grant")

    replace(plan, launch_mode="background", lifetime=lifetime, mode="spawn").execute()

    status = runtime.status()
    assert status.pid == 5678
    assert status.launch_mode == "background"
    assert status.lifetime == lifetime
    assert status.clients == 1
    assert status.port == plan.options.port
    assert spawn.call_args.args == (build_gateway_command(sys.executable, plan.options),)
    assert spawn.call_args.kwargs["cwd"] == plan.cwd
    assert spawn.call_args.kwargs["env"][BACKGROUND_LOG_PATH_ENV] == str(plan.paths.log_path)
    assert "NANOBOT_UPDATE_STARTUP_TOKEN" not in spawn.call_args.kwargs["env"]
    assert client.snapshot().auto_stop is (lifetime == "on_demand")


def test_background_exec_reclaims_same_instance_without_promoting_its_lifetime(monkeypatch, plan):
    runtime = _runtime_with_fake_processes(monkeypatch, plan)
    client = GatewayClientLease(runtime, kind="tui", pid=1234, token="existing-client")
    client.acquire()
    client.mark_ephemeral()
    launch = Mock()
    monkeypatch.setattr("nanobot.gateway.restart.replace_process", launch)

    replace(plan, launch_mode="background", lifetime="on_demand").execute()
    environment = launch.call_args.kwargs["env"]
    assert environment[BACKGROUND_LOG_PATH_ENV] == str(plan.paths.log_path)
    monkeypatch.setenv("NANOBOT_GATEWAY_RESTART_BACKGROUND", environment["NANOBOT_GATEWAY_RESTART_BACKGROUND"])
    claim_restarted_background(runtime, plan.options)
    mode = runtime._claim_current_process(plan.options)

    assert mode == "background"
    assert runtime.status().lifetime == "on_demand"
    assert runtime.status().clients == 1
    assert runtime.status().port == plan.options.port
    assert "NANOBOT_GATEWAY_RESTART_BACKGROUND" not in os.environ
    runtime._release_current_process()


def test_replacement_does_not_stop_a_gateway_that_claimed_the_gap(monkeypatch, plan):
    runtime = _runtime_with_fake_processes(monkeypatch, plan)
    runtime._claim_current_process(plan.options)
    spawn = Mock()
    monkeypatch.setattr(subprocess, "Popen", spawn)

    with pytest.raises(GatewayAlreadyRunningError):
        replace(plan, launch_mode="background", mode="spawn").execute()

    assert runtime.status().pid == os.getpid()
    spawn.assert_not_called()
    runtime._release_current_process()
