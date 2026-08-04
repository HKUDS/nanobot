"""Vite development-server lifecycle for the WebUI source checkout."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from nanobot.webui.build import default_webui_source_dir, pick_webui_build_runner

WEBUI_DEV_HOST = "127.0.0.1"
WEBUI_DEV_PORT = 5173


class WebUIDevError(RuntimeError):
    """Raised when the local Vite development server cannot be started."""


@dataclass
class WebUIDevServer:
    """A running Vite development server owned by the foreground CLI."""

    process: subprocess.Popen[Any]

    def ensure_running(self) -> None:
        """Raise when Vite exits while the foreground command still owns it."""
        if (returncode := self.process.poll()) is not None:
            raise WebUIDevError(
                f"WebUI development server exited unexpectedly (code {returncode})"
            )

    def stop(self, *, timeout_s: float = 5.0) -> None:
        """Stop and reap the direct Vite process."""
        if self.process.poll() is not None:
            return

        self.process.terminate()
        try:
            self.process.wait(timeout=timeout_s)
            return
        except subprocess.TimeoutExpired:
            pass

        self.process.kill()
        with suppress(subprocess.TimeoutExpired):
            self.process.wait(timeout=2)


def webui_dev_browser_url(webui_url: str) -> str:
    """Move a configured WebUI URL to Vite while preserving its auth fragment."""
    parsed = urlsplit(webui_url)
    return urlunsplit(("http", f"{WEBUI_DEV_HOST}:{WEBUI_DEV_PORT}", parsed.path, "", parsed.fragment))


def webui_dev_proxy_target(webui_url: str) -> str:
    """Return the backend origin Vite should use for HTTP proxy requests."""
    parsed = urlsplit(webui_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _endpoint_reachable(host: str, port: int, *, timeout_s: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _runner_name(runner: str) -> str:
    return Path(runner).stem.casefold()


def _ensure_vite_cli(
    source_dir: Path,
    *,
    runner: str,
    subprocess_run: Callable[..., subprocess.CompletedProcess[Any]],
    output: Callable[[str], None] | None,
) -> Path:
    vite_cli = source_dir / "node_modules" / "vite" / "bin" / "vite.js"
    if vite_cli.is_file():
        return vite_cli

    if output is not None:
        output(f"Installing WebUI development dependencies with `{runner}`...")
    if _runner_name(runner) == "bun" and (source_dir / "bun.lock").is_file():
        command = [runner, "install", "--frozen-lockfile"]
    elif _runner_name(runner) == "npm" and (source_dir / "package-lock.json").is_file():
        command = [runner, "ci"]
    else:
        command = [runner, "install"]
    try:
        subprocess_run(command, cwd=source_dir, check=True)
    except subprocess.CalledProcessError as exc:
        raise WebUIDevError(
            f"frontend dependency install failed ({exc.returncode}): {' '.join(command)}"
        ) from exc
    except OSError as exc:
        raise WebUIDevError(f"frontend dependency install failed: {exc}") from exc

    if not vite_cli.is_file():
        raise WebUIDevError(
            f"Vite was not installed under {source_dir}; run `cd webui && {runner} install`"
        )
    return vite_cli


def _vite_command(runner: str, vite_cli: Path) -> list[str]:
    if node := shutil.which("node"):
        return [node, str(vite_cli)]
    if _runner_name(runner) == "bun":
        return [runner, str(vite_cli)]
    raise WebUIDevError("Node.js is required to run the WebUI development server")


def start_webui_dev_server(
    *,
    target_url: str,
    browser_url: str,
    source_dir: Path | None = None,
    runner: str | None = None,
    environ: Mapping[str, str] | None = None,
    output: Callable[[str], None] | None = None,
    timeout_s: float = 15.0,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    subprocess_run: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    endpoint_reachable: Callable[..., bool] = _endpoint_reachable,
    sleep: Callable[[float], None] = time.sleep,
) -> WebUIDevServer:
    """Start Vite from a source checkout and wait until its listener is ready."""
    resolved_source = source_dir or default_webui_source_dir()
    if not (resolved_source / "package.json").is_file():
        raise WebUIDevError(
            "`nanobot webui --dev` requires a source checkout containing webui/package.json"
        )
    if endpoint_reachable(WEBUI_DEV_HOST, WEBUI_DEV_PORT):
        raise WebUIDevError(
            f"WebUI development port {WEBUI_DEV_PORT} is already in use; stop that process first"
        )

    command_runner = runner or pick_webui_build_runner()
    if command_runner is None:
        raise WebUIDevError(
            "neither `bun` nor `npm` is available on PATH; install one to use WebUI dev mode"
        )
    vite_cli = _ensure_vite_cli(
        resolved_source,
        runner=command_runner,
        subprocess_run=subprocess_run,
        output=output,
    )
    command = _vite_command(command_runner, vite_cli)
    child_env = dict(environ or os.environ)
    child_env["NANOBOT_API_URL"] = target_url

    try:
        # Keep Vite in the foreground console group so Ctrl+C reaches both it
        # and the gateway. Directly invoking Vite avoids a package-manager child.
        process = popen(command, cwd=resolved_source, env=child_env)
    except OSError as exc:
        raise WebUIDevError(f"could not start the WebUI development server: {exc}") from exc
    server = WebUIDevServer(process=process)

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise WebUIDevError(
                f"WebUI development server exited before it was ready (code {process.returncode})"
            )
        if endpoint_reachable(WEBUI_DEV_HOST, WEBUI_DEV_PORT):
            if output is not None:
                parsed_url = urlsplit(browser_url)
                display_url = urlunsplit(
                    (parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", "")
                )
                output(f"WebUI dev server: {display_url}")
            return server
        sleep(0.1)

    server.stop()
    raise WebUIDevError(
        f"WebUI development server did not listen on {WEBUI_DEV_HOST}:{WEBUI_DEV_PORT} "
        f"within {timeout_s:g}s"
    )


@contextmanager
def run_webui_dev_server(
    *,
    target_url: str,
    browser_url: str,
    output: Callable[[str], None] | None = None,
) -> Generator[WebUIDevServer, None, None]:
    """Run a Vite sidecar for the duration of a foreground WebUI command."""
    server = start_webui_dev_server(
        target_url=target_url,
        browser_url=browser_url,
        output=output,
    )
    try:
        yield server
    finally:
        server.stop()
