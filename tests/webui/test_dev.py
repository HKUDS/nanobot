from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nanobot.webui.dev import (
    WebUIDevError,
    WebUIDevServer,
    run_webui_dev_server,
    start_webui_dev_server,
    webui_dev_browser_url,
    webui_dev_proxy_target,
)


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 123
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, *, timeout: float) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("vite", timeout)
        return self.returncode


def _write_webui_source(source: Path, *, with_vite: bool = True) -> Path:
    source.mkdir(parents=True)
    (source / "package.json").write_text("{}", encoding="utf-8")
    (source / "bun.lock").write_text("", encoding="utf-8")
    vite_cli = source / "node_modules" / "vite" / "bin" / "vite.js"
    if with_vite:
        vite_cli.parent.mkdir(parents=True)
        vite_cli.write_text("", encoding="utf-8")
    return vite_cli


def test_dev_urls_preserve_secret_and_target_only_the_backend_origin() -> None:
    webui_url = "http://127.0.0.1:8899/#/?bootstrapSecret=secret"

    assert webui_dev_browser_url(webui_url) == (
        "http://127.0.0.1:5173/#/?bootstrapSecret=secret"
    )
    assert webui_dev_proxy_target(webui_url) == "http://127.0.0.1:8899"


def test_start_webui_dev_server_uses_vite_directly_and_sets_proxy_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "webui"
    vite_cli = _write_webui_source(source)
    process = _FakeProcess()
    popen_calls: list[tuple[list[str], dict[str, object]]] = []
    reachability = iter((False, True))
    output: list[str] = []

    def fake_popen(command: list[str], **kwargs):
        popen_calls.append((command, kwargs))
        return process

    monkeypatch.setattr(
        "nanobot.webui.dev.shutil.which",
        lambda name: "node" if name == "node" else None,
    )

    server = start_webui_dev_server(
        target_url="http://127.0.0.1:8899",
        browser_url="http://127.0.0.1:5173/#/?bootstrapSecret=secret",
        source_dir=source,
        runner="bun",
        environ={"EXISTING": "value"},
        output=output.append,
        popen=fake_popen,
        endpoint_reachable=lambda *_args, **_kwargs: next(reachability),
        sleep=lambda _seconds: None,
    )

    assert server.process is process
    command, kwargs = popen_calls[0]
    assert command == ["node", str(vite_cli)]
    assert kwargs["cwd"] == source
    assert kwargs["env"] == {
        "EXISTING": "value",
        "NANOBOT_API_URL": "http://127.0.0.1:8899",
    }
    assert output == ["WebUI dev server: http://127.0.0.1:5173/"]
    assert "secret" not in output[0]


def test_dev_server_installs_locked_dependencies_when_vite_is_missing(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    vite_cli = _write_webui_source(source, with_vite=False)
    commands: list[list[str]] = []
    process = _FakeProcess()
    reachability = iter((False, True))

    def fake_run(command: list[str], *, cwd: Path, check: bool):
        commands.append(command)
        assert cwd == source
        assert check is True
        vite_cli.parent.mkdir(parents=True)
        vite_cli.write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    start_webui_dev_server(
        target_url="http://127.0.0.1:8765",
        browser_url="http://127.0.0.1:5173",
        source_dir=source,
        runner="bun",
        popen=lambda *_args, **_kwargs: process,
        subprocess_run=fake_run,
        endpoint_reachable=lambda *_args, **_kwargs: next(reachability),
        sleep=lambda _seconds: None,
    )

    assert commands == [["bun", "install", "--frozen-lockfile"]]


def test_dev_server_requires_a_source_checkout(tmp_path: Path) -> None:
    with pytest.raises(WebUIDevError, match="source checkout"):
        start_webui_dev_server(
            target_url="http://127.0.0.1:8765",
            browser_url="http://127.0.0.1:5173",
            source_dir=tmp_path / "missing",
        )


def test_dev_server_stop_terminates_and_reaps_the_direct_process() -> None:
    process = _FakeProcess()
    server = WebUIDevServer(process=process)

    server.stop()

    assert process.terminated is True
    assert process.killed is False
    assert process.returncode == 0


def test_dev_server_reports_an_unexpected_exit() -> None:
    process = _FakeProcess()
    process.returncode = 23
    server = WebUIDevServer(process=process)

    with pytest.raises(WebUIDevError, match=r"exited unexpectedly \(code 23\)"):
        server.ensure_running()


def test_dev_server_context_stops_the_child(monkeypatch) -> None:
    process = _FakeProcess()
    process.returncode = 0
    server = type("Server", (), {"process": process})()
    stopped: list[bool] = []
    server.stop = lambda: stopped.append(True)
    monkeypatch.setattr("nanobot.webui.dev.start_webui_dev_server", lambda **_kwargs: server)

    with run_webui_dev_server(target_url="unused", browser_url="unused") as running:
        assert running is server

    assert stopped == [True]
