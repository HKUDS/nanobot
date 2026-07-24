"""Lifecycle helpers for the local WebUI development server."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from nanobot.webui.build import default_webui_source_dir, pick_webui_build_runner

WEBUI_DEV_HOST = "127.0.0.1"
WEBUI_DEV_PORT = 5173


class WebUIDevServerError(RuntimeError):
    """Raised when the Vite development server cannot be started."""


@dataclass(frozen=True)
class WebUIDevServer:
    """A running local WebUI development server."""

    process: Any
    source_dir: Path
    url: str


def webui_dev_browser_url(
    gateway_webui_url: str,
    *,
    host: str = WEBUI_DEV_HOST,
    port: int = WEBUI_DEV_PORT,
) -> str:
    """Move a gateway WebUI URL, including its bootstrap fragment, to Vite."""
    parsed = urlsplit(gateway_webui_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebUIDevServerError(f"invalid gateway WebUI URL: {gateway_webui_url}")
    return urlunsplit(
        (
            "http",
            f"{host}:{port}",
            parsed.path or "/",
            parsed.query,
            parsed.fragment,
        )
    )


def gateway_origin(gateway_webui_url: str) -> str:
    """Return the HTTP origin Vite should use for API proxying."""
    parsed = urlsplit(gateway_webui_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebUIDevServerError(f"invalid gateway WebUI URL: {gateway_webui_url}")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


@contextmanager
def run_webui_dev_server(
    gateway_webui_url: str,
    *,
    source_dir: Path | None = None,
    runner: str | None = None,
    environ: Mapping[str, str] | None = None,
    output: Callable[[str], None] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
    subprocess_run: Callable[..., Any] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    startup_timeout_s: float = 15.0,
    platform: str | None = None,
) -> Iterator[WebUIDevServer]:
    """Start Vite for a source checkout and stop its process tree on exit."""
    resolved_source = (source_dir or default_webui_source_dir()).resolve(strict=False)
    if not (resolved_source / "package.json").is_file():
        raise WebUIDevServerError(
            "WebUI source was not found. `nanobot webui --dev` must run from "
            "an editable source checkout."
        )

    command_runner = runner or pick_webui_build_runner()
    if command_runner is None:
        raise WebUIDevServerError(
            "neither `bun` nor `npm` is available on PATH; install one and retry"
        )

    dev_url = f"http://{WEBUI_DEV_HOST}:{WEBUI_DEV_PORT}"
    if _endpoint_reachable(WEBUI_DEV_HOST, WEBUI_DEV_PORT):
        raise WebUIDevServerError(
            f"{dev_url} is already in use; stop the existing Vite server and retry"
        )

    if not (resolved_source / "node_modules" / "vite").is_dir():
        _emit(output, f"Installing WebUI dependencies with `{command_runner}`...")
        _run_checked(
            [command_runner, "install"],
            cwd=resolved_source,
            subprocess_run=subprocess_run,
        )

    child_env = dict(os.environ if environ is None else environ)
    child_env["NANOBOT_API_URL"] = gateway_origin(gateway_webui_url)
    command = [command_runner, "run", "dev"]
    child_platform = platform or sys.platform
    try:
        process = popen(
            command,
            cwd=resolved_source,
            env=child_env,
            **_popen_platform_kwargs(child_platform),
        )
    except OSError as exc:
        raise WebUIDevServerError(
            f"could not start WebUI dev server: {exc}"
        ) from exc

    try:
        deadline = time.monotonic() + max(startup_timeout_s, 0.0)
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                raise WebUIDevServerError(
                    f"WebUI dev server exited during startup (status {return_code})"
                )
            if _endpoint_reachable(WEBUI_DEV_HOST, WEBUI_DEV_PORT):
                break
            sleep(0.1)
        else:
            raise WebUIDevServerError(
                f"WebUI dev server did not become ready at {dev_url}"
            )

        _emit(output, f"Vite HMR is ready at {dev_url}")
        yield WebUIDevServer(
            process=process,
            source_dir=resolved_source,
            url=dev_url,
        )
    finally:
        _stop_process_tree(
            process,
            platform=child_platform,
            subprocess_run=subprocess_run,
        )


def _run_checked(
    command: list[str],
    *,
    cwd: Path,
    subprocess_run: Callable[..., Any],
) -> None:
    try:
        subprocess_run(command, cwd=cwd, check=True)
    except subprocess.CalledProcessError as exc:
        raise WebUIDevServerError(
            f"command failed ({exc.returncode}): {' '.join(command)}"
        ) from exc
    except OSError as exc:
        raise WebUIDevServerError(
            f"command failed: {' '.join(command)} ({exc})"
        ) from exc


def _popen_platform_kwargs(platform: str) -> dict[str, Any]:
    if platform == "win32":
        return {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        }
    return {"start_new_session": True}


def _stop_process_tree(
    process: Any,
    *,
    platform: str,
    subprocess_run: Callable[..., Any],
) -> None:
    if process.poll() is not None:
        return

    if platform == "win32":
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            with suppress(OSError):
                process.send_signal(ctrl_break)
            if _wait_for_process(process, timeout_s=3.0):
                return
        subprocess_run(
            ["taskkill", "/PID", str(process.pid), "/T"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if _wait_for_process(process, timeout_s=2.0):
            return
        subprocess_run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_process(process, timeout_s=2.0)
        return

    try:
        process_group = os.getpgid(process.pid)
    except OSError:
        process_group = None
    try:
        if process_group is None:
            process.terminate()
        else:
            os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    if _wait_for_process(process, timeout_s=3.0):
        return
    with suppress(OSError):
        if process_group is None:
            process.kill()
        else:
            os.killpg(process_group, signal.SIGKILL)
    _wait_for_process(process, timeout_s=2.0)


def _wait_for_process(process: Any, *, timeout_s: float) -> bool:
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False
    return True


def _endpoint_reachable(host: str, port: int, *, timeout_s: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _emit(output: Callable[[str], None] | None, message: str) -> None:
    if output is not None:
        output(message)
