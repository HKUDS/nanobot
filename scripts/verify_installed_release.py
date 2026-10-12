"""Probe a wheel installed in a disposable venv, without a frontend toolchain.

Run with that venv's ``python -I`` and exact expected version/commit. This checks
installed identity, real loopback asset responses and native TUI protocol startup.
Optionally start a loopback-only gateway with a disposable, unconfigured profile.
Neither mode uses a model or claims interactive UI, migration or updater coverage.
"""

from __future__ import annotations

import argparse
import asyncio
import http.client
import importlib.metadata
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath


def webui_assets(directory: Path) -> set[str]:
    """Check Vite's complete manifest, including lazy chunks, before HTTP probing."""
    manifest = json.loads((directory / "asset-manifest.json").read_text(encoding="utf-8"))
    files: set[str] = set()
    for key, record in manifest.items():
        for dependency in [*record.get("imports", []), *record.get("dynamicImports", [])]:
            if dependency not in manifest:
                raise ValueError(f"Missing WebUI manifest dependency: {key} -> {dependency}")
        for filename in [record["file"], *record.get("css", []), *record.get("assets", [])]:
            relative = PurePosixPath(filename)
            if (relative.is_absolute() or ".." in relative.parts or "\\" in filename
                    or not (directory / filename).resolve().is_relative_to(directory.resolve())):
                raise ValueError(f"Invalid WebUI asset path: {filename}")
            if not (directory / filename).is_file() or not (directory / filename).stat().st_size:
                raise ValueError(f"Missing or empty WebUI asset: {filename}")
            files.add(filename)
    html = (directory / "index.html").read_text(encoding="utf-8")
    entries = set(re.findall(r'(?:src|href)="/(assets/[^"?#]+\.(?:js|css))"', html))
    if not entries or not entries <= files:
        raise ValueError("WebUI HTML entrypoints are absent from the compiled manifest")
    return files


def gateway_probe(version: str, directory: Path) -> dict[str, object]:
    """Probe the installed CLI, actual readiness and WebUI, then stop only our child."""
    directory.mkdir(mode=0o700)
    config = directory / "config.json"
    token = secrets.token_urlsafe(32)
    # If another process wins the bind race, the child must fail; its unique
    # bootstrap secret prevents accepting that other server's identity response.
    with socket.socket() as health_socket, socket.socket() as web_socket:
        health_socket.bind(("127.0.0.1", 0))
        web_socket.bind(("127.0.0.1", 0))
        health_port, web_port = health_socket.getsockname()[1], web_socket.getsockname()[1]
        config.write_text(json.dumps({
            "agents": {"defaults": {"workspace": str(directory / "workspace")}},
            "gateway": {"host": "127.0.0.1", "port": health_port, "heartbeat": {"enabled": False}},
            "channels": {"websocket": {"enabled": True, "host": "127.0.0.1", "port": web_port,
                                        "tokenIssueSecret": token, "websocketRequiresToken": True}},
            "tools": {"mcpServers": {}},
        }), encoding="utf-8")
        config.chmod(0o600)

    def get(port: int, path: str) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", path, headers={"X-Nanobot-Auth": token})
            response = connection.getresponse()
            return response.status, response.read(2 * 1024 * 1024)
        finally:
            connection.close()

    command = [sys.executable, "-I", "-m", "nanobot", "gateway", "--foreground", "--config", str(config)]
    # A file avoids pipe backpressure; print only a bounded, redacted tail on failure.
    with (directory / "gateway.log").open("w+b") as log:
        process = subprocess.Popen(command, cwd=directory, stdout=log, stderr=log)
        try:
            try:
                deadline = time.monotonic() + 45
                while True:
                    if process.poll() is not None:
                        raise ValueError(f"Installed gateway exited before readiness: {process.returncode}")
                    try:
                        code, body = get(health_port, "/health")
                        if code == 200 and json.loads(body).get("ready") is True:
                            break
                    except (OSError, ValueError, http.client.HTTPException):
                        pass
                    if time.monotonic() >= deadline:
                        raise ValueError("Installed gateway did not become ready within 45 seconds")
                    time.sleep(0.2)
                code, body = get(web_port, "/webui/terminal")
                if code != 200 or json.loads(body).get("webui", {}).get("version") != version:
                    raise ValueError("Running gateway did not report the installed candidate version")
                code, body = get(web_port, "/")
                if code != 200 or b"<html" not in body.lower() or b"/assets/" not in body:
                    raise ValueError("Running gateway did not serve the built WebUI")
            finally:
                if process.poll() is None:
                    # Windows termination is cleanup, not graceful-shutdown proof.
                    if os.name == "nt":
                        process.terminate()
                    else:
                        process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        raise ValueError("Installed gateway required forced cleanup") from None
            if os.name != "nt" and process.returncode != 0:
                raise ValueError(f"Installed gateway did not exit cleanly: {process.returncode}")
            for port in (health_port, web_port):
                with socket.socket() as connection:
                    connection.settimeout(1)
                    if connection.connect_ex(("127.0.0.1", port)) == 0:
                        raise ValueError("A probe listener remained reachable after stopping its gateway")
        except Exception:
            log.flush()
            log.seek(max(0, os.fstat(log.fileno()).st_size - 8192))
            print(log.read().decode("utf-8", errors="replace").replace(token, "[redacted]"), file=sys.stderr)
            raise
    return {"gateway_ready": True, "gateway_webui_served": True,
            "gateway_process_stopped": True, "gateway_graceful_shutdown": os.name != "nt"}


async def verify_installed_release(
    version: str, commit: str, data_dir: Path, *, gateway: bool = False,
) -> dict[str, object]:
    # Imports deliberately happen only after main has isolated HOME, PATH and cwd.
    from aiohttp import ClientTimeout, web
    from aiohttp.test_utils import TestClient, TestServer

    import nanobot
    from nanobot.build_info import COMMIT
    from nanobot.cli.tui_launcher import resolve_tui_command
    from nanobot.webui.build import inspect_webui_bundle
    from nanobot.webui.local_client_assets import LocalClientAssets

    prefix = Path(sys.prefix).resolve()
    package = Path(nanobot.__file__).resolve()
    distribution = importlib.metadata.distribution("nanobot-ai")
    if (not package.is_relative_to(prefix)
            or package != Path(str(distribution.locate_file("nanobot/__init__.py"))).resolve()):
        raise ValueError("Probe imported a checkout or another environment, not the installed wheel")
    if nanobot.__version__ != version or distribution.version != version or COMMIT != commit:
        raise ValueError("Installed package version/commit differs from the expected candidate")
    if any(shutil.which(tool) for tool in ("bun", "node", "npm", "git")):
        raise ValueError("Frontend development tools must not be on the probe PATH")
    if os.environ.get("NANOBOT_TUI_NO_DOWNLOAD") != "1":
        raise ValueError("The installed TUI probe must disable fallback downloads")

    bundle = inspect_webui_bundle()
    if not bundle.dist_available or bundle.needs_build or bundle.source_available:
        raise ValueError("Installed wheel must contain a usable WebUI without a source build")
    assets = LocalClientAssets()
    if not assets.directory.is_relative_to(package.parent):
        raise ValueError("WebUI assets do not belong to the installed package")
    files = webui_assets(assets.directory)
    app = web.Application()

    async def serve(request: web.Request) -> web.FileResponse:
        return assets.response(request)

    app.router.add_get("/{path:.*}", serve)
    async with asyncio.timeout(40), TestClient(
        TestServer(app, host="127.0.0.1"), timeout=ClientTimeout(total=5),
        headers={"Accept-Encoding": "identity"},
    ) as client:
        for filename in ["index.html", "asset-manifest.json", *sorted(files)]:
            response = await client.get("/" if filename == "index.html" else f"/{filename}")
            if response.status != 200 or response.headers.get("X-Nanobot-UI") != "local":
                raise ValueError(f"Installed WebUI asset was not served: {filename}")
            if await response.read() != (assets.directory / filename).read_bytes():
                raise ValueError(f"Installed WebUI response differs from its file: {filename}")
            if filename.endswith((".js", ".css")) and response.content_type == "text/html":
                raise ValueError(f"WebUI asset unexpectedly served the HTML shell: {filename}")

    command = resolve_tui_command(data_dir=data_dir)
    executable = Path(command[0]).resolve()
    if len(command) != 1 or not executable.is_relative_to(package.parent / "tui" / "bin"):
        raise ValueError("TUI command must use the installed native bundle, not source or cache")
    if not os.access(executable, os.X_OK):
        raise ValueError("Installed TUI is not executable")
    native = subprocess.run(
        [str(executable), "--desktop-protocol"], check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=15,
    )
    if native.stdout.strip() != "1":
        raise ValueError("Installed TUI returned an unsupported desktop protocol")
    runtime = await asyncio.to_thread(gateway_probe, version, data_dir.parent / "gateway") if gateway else {}
    return {
        "version": version, "candidate_commit": commit, "package": str(package),
        "platform": platform.system(), "machine": platform.machine(),
        "python": platform.python_version(), "webui_assets_served": len(files),
        "frontend_build_tools_on_path": False, "tui_download_enabled": False,
        "native_tui": str(executable), "native_protocol_probe": native.stdout.strip(),
        "gateway_started": gateway, "interactive_ui_e2e": False, **runtime,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--gateway", action="store_true",
                        help="Also start a disposable loopback gateway; no model calls or user config")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not sys.flags.isolated or sys.prefix == sys.base_prefix:
        parser.error("Run the disposable installation's python -I, not the build/source interpreter")
    report = args.report.resolve() if args.report else None
    if report is not None and report.exists():
        parser.error("Use a new report path; prior evidence must not be overwritten")
    original_env, original_cwd = dict(os.environ), Path.cwd()
    with tempfile.TemporaryDirectory(prefix="nanobot-installed-probe-") as temporary:
        root = Path(temporary).resolve()
        empty_path = root / "empty-path"
        empty_path.mkdir()
        env = {key: original_env[key] for key in ("SYSTEMROOT", "WINDIR") if key in original_env}
        env.update({
            "PATH": str(empty_path), "HOME": str(root), "USERPROFILE": str(root),
            "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_DATA_HOME": str(root / "data"), "TMPDIR": str(root), "TMP": str(root),
            "TEMP": str(root), "NANOBOT_TUI_NO_DOWNLOAD": "1", "NO_COLOR": "1",
        })
        os.environ.clear()
        os.environ.update(env)
        os.chdir(root)
        try:
            result = asyncio.run(verify_installed_release(
                args.version, args.commit, root / "tui", gateway=args.gateway,
            ))
        finally:
            os.chdir(original_cwd)
            os.environ.clear()
            os.environ.update(original_env)
    payload = json.dumps(result, indent=2) + "\n"
    if report is not None:
        with report.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
