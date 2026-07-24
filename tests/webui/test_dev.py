from __future__ import annotations

from pathlib import Path

from nanobot.webui import dev as webui_dev
from nanobot.webui.dev import (
    gateway_origin,
    run_webui_dev_server,
    webui_dev_browser_url,
)


def test_webui_dev_urls_preserve_bootstrap_fragment_and_strip_proxy_credentials() -> None:
    gateway_url = "http://127.0.0.1:8899/#/?bootstrapSecret=secret"

    assert webui_dev_browser_url(gateway_url) == (
        "http://127.0.0.1:5173/#/?bootstrapSecret=secret"
    )
    assert gateway_origin(gateway_url) == "http://127.0.0.1:8899"


def test_run_webui_dev_server_installs_starts_and_stops_vite(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "webui"
    source.mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")
    endpoint_results = iter((False, True))
    monkeypatch.setattr(
        webui_dev,
        "_endpoint_reachable",
        lambda *_args, **_kwargs: next(endpoint_results),
    )
    monkeypatch.setattr(webui_dev.signal, "CTRL_BREAK_EVENT", 1, raising=False)
    commands: list[tuple[list[str], dict[str, object]]] = []
    installs: list[tuple[list[str], Path, bool]] = []
    signals: list[int] = []
    messages: list[str] = []

    class _FakeProcess:
        pid = 123
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def send_signal(self, value: int) -> None:
            signals.append(value)
            self.stopped = True

        def wait(self, *, timeout: float) -> int:
            assert timeout == 3.0
            self.stopped = True
            return 0

    process = _FakeProcess()

    def _fake_popen(command, **kwargs):
        commands.append((command, kwargs))
        return process

    def _fake_run(command, *, cwd=None, check=False, **_kwargs):
        installs.append((command, cwd, check))

    with run_webui_dev_server(
        "http://127.0.0.1:8899/#/?bootstrapSecret=secret",
        source_dir=source,
        runner="bun",
        environ={"BASE": "value"},
        output=messages.append,
        popen=_fake_popen,
        subprocess_run=_fake_run,
        sleep=lambda _seconds: None,
        platform="win32",
    ) as server:
        assert server.url == "http://127.0.0.1:5173"
        assert server.source_dir == source
        assert process.stopped is False

    assert installs == [(["bun", "install"], source, True)]
    assert len(commands) == 1
    command, kwargs = commands[0]
    assert command == ["bun", "run", "dev"]
    assert kwargs["cwd"] == source
    assert kwargs["env"] == {
        "BASE": "value",
        "NANOBOT_API_URL": "http://127.0.0.1:8899",
    }
    assert "creationflags" in kwargs
    assert signals == [1]
    assert any("Installing WebUI dependencies" in message for message in messages)
    assert any("Vite HMR is ready" in message for message in messages)
