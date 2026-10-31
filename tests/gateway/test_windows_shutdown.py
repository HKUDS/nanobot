import asyncio
import ctypes
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest

from nanobot.gateway import (
    GatewayInstance,
    GatewayRuntime,
    GatewayRuntimePaths,
    GatewayStartOptions,
)
from nanobot.gateway.windows_shutdown import WindowsShutdownEvent, request_windows_shutdown

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process lifecycle")


def test_windowless_gateway_stop_runs_application_cleanup(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "agents": {"defaults": {
            "workspace": str(tmp_path / "workspace"),
            "model": "openai/test-only",
            "dream": {"enabled": False},
        }},
        "providers": {"openai": {"apiKey": "test-only", "apiBase": "http://127.0.0.1:9/v1"}},
        "gateway": {"host": "127.0.0.1", "port": port, "heartbeat": {"enabled": False}},
        "channels": {"websocket": {"enabled": False}},
    }), encoding="utf-8")
    runtime = GatewayRuntime(paths=GatewayInstance.resolve(config_path=config_path).paths)
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONUTF8": "1"}
    log_path = tmp_path / "gateway.log"
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "nanobot", "gateway", "--foreground", "--config", str(config_path)],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                try:
                    connection.request("GET", "/health")
                    if connection.getresponse().status == 200:
                        break
                except (OSError, http.client.HTTPException):
                    pass
                finally:
                    connection.close()
                assert process.poll() is None, log_path.read_text(encoding="utf-8")
                assert time.monotonic() < deadline, log_path.read_text(encoding="utf-8")
                time.sleep(0.02)
            stopped = subprocess.run(
                [sys.executable, "-m", "nanobot", "gateway", "stop", "--config", str(config_path)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr
            assert "Gateway stopped" in stopped.stdout
            assert process.wait(timeout=5) == 0, log_path.read_text(encoding="utf-8")
            assert "Agent loop stopping" in log_path.read_text(encoding="utf-8")
            assert not runtime.paths.state_path.exists()
        finally:
            if process.poll() is None:
                runtime.stop(timeout_s=0)
                process.wait(timeout=5)


def _event_security(handle: int) -> str:
    """Verify the native owner identity and return the event's rendered security."""
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    security.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    security.EqualSid.restype = wintypes.BOOL
    security.GetSecurityInfo.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
        wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    security.GetSecurityInfo.restype = wintypes.DWORD
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), wintypes.LPVOID,
    ]
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID
    descriptor = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    text = wintypes.LPWSTR()
    token = wintypes.HANDLE()
    try:
        assert security.GetSecurityInfo(
            handle, 6, 5, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor),
        ) == 0
        assert security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token))
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        assert size.value > 0
        user = ctypes.create_string_buffer(size.value)
        assert security.GetTokenInformation(token, 1, user, len(user), ctypes.byref(size))
        current_user = ctypes.cast(user, ctypes.POINTER(wintypes.LPVOID))[0]
        # SDDL may abbreviate account SIDs (for example LA); compare their identities.
        assert security.EqualSid(owner, current_user)
        assert security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 5, ctypes.byref(text), None,
        )
        assert text.value is not None
        return text.value
    finally:
        if text:
            kernel.LocalFree(text)
        if descriptor:
            kernel.LocalFree(descriptor)
        if token:
            kernel.CloseHandle(token)


def test_shutdown_signal_is_private_process_bound_and_latched(tmp_path: Path) -> None:
    runtime = GatewayRuntime(paths=GatewayRuntimePaths.for_instance(data_dir=tmp_path))
    pid = os.getpid()
    identity = runtime.process_identity(pid)
    assert isinstance(identity, str)
    with runtime.foreground_instance(GatewayStartOptions(port=0)):
        state = json.loads(runtime.paths.state_path.read_text(encoding="utf-8"))
        token = state["shutdown_token"]
        signal = runtime._shutdown_signal
        assert signal is not None and signal._handle is not None
        owner, dacl = _event_security(signal._handle)[2:].split("D:", 1)
        assert dacl.startswith("P(A;;") and dacl.endswith(f";;;{owner})")
        assert dacl.count("(") == 1
        assert request_windows_shutdown(pid + 1, identity, token) is False
        assert request_windows_shutdown(pid, identity + "1", token) is False
        other = WindowsShutdownEvent(pid, identity)
        try:
            other_name = rf"Local\nanobot-gateway-stop-{pid}-{identity}-{other.token}"
            assert request_windows_shutdown(pid, identity, other_name) is False
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            assert kernel.WaitForSingleObject(other._handle, 0) == 258
        finally:
            other.close()
        assert request_windows_shutdown(pid, identity, token) is True
        shutdown = asyncio.Event()
        asyncio.run(runtime.wait_for_shutdown_request(shutdown))
        assert shutdown.is_set()
    assert request_windows_shutdown(pid, identity, token) is False


def test_cancelling_shutdown_listener_drains_its_native_wait(tmp_path: Path) -> None:
    runtime = GatewayRuntime(paths=GatewayRuntimePaths.for_instance(data_dir=tmp_path))
    with runtime.foreground_instance(GatewayStartOptions(port=0)):
        async def cancel_listener() -> None:
            shutdown = asyncio.Event()
            listener = asyncio.create_task(runtime.wait_for_shutdown_request(shutdown))
            await asyncio.sleep(0)
            listener.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(listener, timeout=2)
            assert not shutdown.is_set()

        asyncio.run(cancel_listener())
    assert runtime._shutdown_signal is None


def test_failed_foreground_publication_closes_shutdown_signal(tmp_path: Path, monkeypatch) -> None:
    runtime = GatewayRuntime(paths=GatewayRuntimePaths.for_instance(data_dir=tmp_path))
    signals = []

    def create_signal(pid, identity):
        signal = WindowsShutdownEvent(pid, identity)
        signals.append(signal)
        return signal

    def fail_write(_state):
        raise OSError("cannot publish state")

    monkeypatch.setattr("nanobot.gateway.runtime.WindowsShutdownEvent", create_signal)
    monkeypatch.setattr(runtime, "_write_state", fail_write)
    with pytest.raises(OSError, match="cannot publish state"):
        with runtime.foreground_instance(GatewayStartOptions(port=0)):
            pytest.fail("failed publication must not enter the foreground runtime")
    assert len(signals) == 1 and signals[0]._handle is None
    assert runtime._shutdown_signal is None


_STALLED_GATEWAY = r"""
import json, subprocess, sys, time
from pathlib import Path
from nanobot.gateway import GatewayInstance, GatewayRuntime, GatewayStartOptions

root = Path(sys.argv[1])
runtime = GatewayRuntime(paths=GatewayInstance.resolve(config_path=root / 'config.json').paths)
with runtime.foreground_instance(GatewayStartOptions(port=0)):
    child = subprocess.Popen([sys._base_executable, '-c', 'import time; time.sleep(60)'])
    ready = root / 'ready.tmp'
    ready.write_text(json.dumps({'child': child.pid}), encoding='utf-8')
    ready.replace(root / 'ready.json')
    time.sleep(60)  # Models a blocked event loop that cannot service the kernel event.
"""


@pytest.mark.parametrize("published", [True, False], ids=["stalled", "no-signal"])
def test_windows_stop_forces_only_its_stalled_tree(tmp_path: Path, published: bool) -> None:
    runtime = GatewayRuntime(paths=GatewayInstance.resolve(config_path=tmp_path / "config.json").paths)
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(root)}
    process = subprocess.Popen(
        [sys.executable, "-c", _STALLED_GATEWAY, str(tmp_path)], env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    ready = tmp_path / "ready.json"
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        child_pid = json.loads(ready.read_text(encoding="utf-8"))["child"]
        state = json.loads(runtime.paths.state_path.read_text(encoding="utf-8"))
        if not published:
            state.pop("shutdown_token")
            runtime._write_state(state)
        started = time.monotonic()
        result = runtime.stop(timeout_s=1 if published else 20)
        elapsed = time.monotonic() - started
        assert result.ok
        assert process.wait(timeout=5) != 0
        assert not runtime.process_is_running(child_pid)
        assert not runtime.paths.state_path.exists()
        assert elapsed < 5
        if published:
            assert elapsed >= 1
    finally:
        if process.poll() is None:
            runtime.stop(timeout_s=0)
            process.wait(timeout=5)
