"""Exercise the exact wheel's TUI without Bun/Node or a user's gateway.

Reuses the real terminal interaction smoke. Records fresh-process first-frame
and cold/warm worker samples, not cold OS-cache or connected-model latency.
Worker termination/restart is a process-boundary check; UI cancellation remains
covered by the DiagramJobs integration tests, not inferred from this probe.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from zipfile import ZipFile

REPLY_LIMIT = 16_000_000
REQUEST = {"kind": "render", "input": {
    "source": 'C4Container\n Person(user, "用户")\n Container(api, "API 服务", "TypeScript")\n Rel(user, api, "调用", "HTTPS")',
    "width": 800, "scale": 2,
    "colors": {"foreground": "#202020", "muted": "#666666", "surface": "#eeeeee",
               "border": "#888888", "accent": "#3366cc"},
}}


class Worker:
    def __init__(self, binary: Path, directory: Path):
        self.process = subprocess.Popen(
            [str(binary), "--render-mermaid"], cwd=directory, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.replies: queue.Queue[bytes] = queue.Queue()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self) -> None:
        assert self.process.stdout is not None
        while record := self.process.stdout.readline(REPLY_LIMIT + 1):
            self.replies.put(record)
            if len(record) > REPLY_LIMIT:
                break
        self.replies.put(b"")

    def send(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(REQUEST).encode() + b"\n")
        self.process.stdin.flush()

    def render(self) -> float:
        started = time.perf_counter()
        self.send()
        record = self.replies.get(timeout=15)
        if not record or len(record) > REPLY_LIMIT or not record.endswith(b"\n"):
            raise AssertionError("Native worker did not return a bounded reply")
        reply = json.loads(record)
        if "error" in reply:
            raise AssertionError(f"Native rendering failed: {reply['error']}")
        image = reply["image"]
        png = base64.b64decode(image["png"], validate=True)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert 0 < image["width"] * image["height"] <= 8_000_000
        assert "<text" not in image["layout"]["svg"], "Font outlines were not resolved"
        return (time.perf_counter() - started) * 1000

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            raise AssertionError("Native worker required forced cleanup") from None
        finally:
            self.reader.join(timeout=5)
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe:
                    pipe.close()
        assert not self.reader.is_alive(), "Worker output collector survived shutdown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    report_path = args.report.resolve()
    if report_path.exists():
        raise ValueError("Do not overwrite prior native evidence")
    with tempfile.TemporaryDirectory(prefix="nanobot-native-tui-") as temporary:
        root = Path(temporary)
        with ZipFile(wheel) as archive:
            members = [name for name in archive.namelist()
                       if name.startswith("nanobot/tui/bin/nanobot-tui-")
                       and "/" not in name.removeprefix("nanobot/tui/bin/")
                       and not name.endswith((".tar.gz", ".json", ".txt"))]
            if len(members) != 1:
                raise ValueError("Expected one packaged native executable")
            binary = root / Path(members[0]).name
            binary.write_bytes(archive.read(members[0]))
            binary.chmod(0o700)
            commit = archive.read("nanobot/_build_commit.txt").decode().strip()
        # Keep only platform identity. Never inherit daily gateway credentials,
        # desktop attachment variables, config or the frontend toolchain PATH.
        host = {key: value for key, value in os.environ.items()
                if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
        os.environ.clear()
        os.environ.update(host)
        os.environ.update({"HOME": temporary, "USERPROFILE": temporary,
                           "TMPDIR": temporary, "TEMP": temporary, "TMP": temporary,
                           "XDG_CONFIG_HOME": temporary, "XDG_CACHE_HOME": temporary,
                           "PATH": "", "TERM": "xterm-256color", "LANG": "en_US.UTF-8"})
        if os.name == "nt":
            from conpty_smoke import smoke
        else:
            from pty_smoke import smoke
        frames = [smoke(binary, cwd=root) for _ in range(5)]
        worker = Worker(binary, root)
        try:
            renders = [worker.render() for _ in range(5)]
            worker.send()
        finally:
            worker.close()
        worker = Worker(binary, root)
        try:
            restarted = worker.render()
        finally:
            worker.close()
        report = {"candidate_commit": commit, "platform": platform.system(),
                  "machine": platform.machine(), "wheel": wheel.name,
                  "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                  "wheel_bytes": wheel.stat().st_size, "executable_bytes": binary.stat().st_size,
                  "executable_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                  "first_screen_ms": frames, "render_ms_cold_then_warm": renders,
                  "render_after_restart_ms": restarted, "unicode_input_resize_exit": True,
                  "render_fixture": "C4Container: Chinese labels and Latin stereotypes",
                  "default_system_font_resolution": True, "worker_termination_restart": True,
                  "connected_gateway_or_model": False, "os_cache_controlled": False}
    report["temporary_directory_removed"] = not root.exists()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
