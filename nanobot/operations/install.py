"""Install the external supervisor from a verified source checkout."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def systemd_argument(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise ValueError("control characters are not allowed in service arguments")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def install_supervisor(
    *, source: Path, config: Path, python: Path, unit: str = "nanobot.service",
    directory: Path = Path("/etc/systemd/system"), activate: bool = True,
) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*\.service", unit) is None:
        raise ValueError("invalid gateway service name")
    # Keep the venv symlink path: resolving it would select the base interpreter
    # without nanobot's installed dependencies.
    python = python.expanduser().absolute()
    if not python.is_file():
        raise ValueError("Python interpreter does not exist")
    config = config.expanduser().resolve(strict=True)
    source = source.expanduser().resolve(strict=True)
    service = (source / "deploy/nanobot-supervisor.service.in").read_text(encoding="utf-8")
    for key, value in (("PYTHON", str(python)), ("CONFIG", str(config)), ("GATEWAY_UNIT", unit)):
        service = service.replace(f"@{key}@", systemd_argument(value))
    timer = (source / "deploy/nanobot-supervisor.timer").read_text(encoding="utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in (("nanobot-supervisor.service", service), ("nanobot-supervisor.timer", timer)):
        target = directory / name
        temporary = directory / f".{name}.new"
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o644)
        temporary.replace(target)
    if activate:
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
        subprocess.run(["systemctl", "enable", "--now", "nanobot-supervisor.timer"],
                       check=True, timeout=30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--unit", default="nanobot.service")
    args = parser.parse_args()
    install_supervisor(source=args.source, config=args.config, python=args.python, unit=args.unit)


if __name__ == "__main__":
    main()
