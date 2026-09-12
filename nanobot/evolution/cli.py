"""Command-line inspection and operation of the evolution engine."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence, cast

from nanobot.config.loader import load_config
from nanobot.evolution.service import EvolutionService


def _service() -> EvolutionService:
    config = load_config()
    evolution = config.agents.defaults.evolution
    return EvolutionService(evolution, config.workspace_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nanobot-evolution")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show privacy, mode, and record counts")
    commands.add_parser("reflect", help="run deterministic evidence-based reflection")
    report = commands.add_parser("report", help="render a bounded evolution report")
    report.add_argument(
        "--write", action="store_true", help="save the report under evolution/reports"
    )
    evaluate = commands.add_parser("evaluate", help="evaluate a JSON experiment manifest")
    evaluate.add_argument("manifest", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = _service()
    if args.command == "status":
        print(json.dumps(service.status(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "reflect":
        proposals = service.reflection.reflect()
        print(
            json.dumps([proposal.to_dict() for proposal in proposals], ensure_ascii=False, indent=2)
        )
        return 0
    if args.command == "report":
        report = service.render_report()
        if args.write:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            service.store.write_record("reports", stamp, {"markdown": report})
        print(report, end="")
        return 0
    if args.command == "evaluate":
        value = cast(object, json.loads(args.manifest.read_text(encoding="utf-8")))
        if not isinstance(value, dict):
            raise ValueError("experiment manifest must be a JSON object")
        manifest = cast(dict[str, Any], value)
        print(
            json.dumps(
                service.evaluate_and_promote(manifest),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
