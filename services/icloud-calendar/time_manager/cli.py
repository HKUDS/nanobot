from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import Config
from .service import Service


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Proaktywny menedżer czasu iCloud")
    root.add_argument("--config", default="data/config.toml")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    scan = commands.add_parser("scan")
    scan.add_argument("--dry-run", action="store_true")
    commands.add_parser("run")
    commands.add_parser("status")
    return root


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = parser().parse_args(argv)
    config_path = Path(args.config)
    try:
        config = Config.load(config_path)
        if args.command == "status":
            health = config.resolve_state_path(config_path).parent / "health.json"
            if not health.exists():
                raise RuntimeError("Brak health.json — usługa nie wykonała jeszcze poprawnego skanu")
            print(health.read_text(encoding="utf-8"))
            return 0
        service = Service(config, config_path)
        try:
            if args.command == "check":
                result = service.check()
            elif args.command == "scan":
                result = service.scan(dry_run=args.dry_run)
            else:
                service.run_forever()
                return 0
        finally:
            service.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # CalDAV/HTTP exceptions can embed URLs, response bodies or credentials.
        # Keep the public CLI failure deterministic; never echo provider text.
        print(json.dumps({"ok": False, "error": exc.__class__.__name__}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
