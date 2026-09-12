"""Administrative CLI for the optional semantic-memory index."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.context import RequestContext
from nanobot.config.loader import load_config
from nanobot.semantic_memory.service import SemanticMemoryService


def _service(config_path: Path | None) -> SemanticMemoryService:
    config = load_config(config_path)
    semantic = config.agents.defaults.semantic_memory
    if not semantic.enabled:
        raise SystemExit("semantic memory is disabled in configuration")
    return SemanticMemoryService(semantic, MemoryStore(config.workspace_path), config.workspace_path)


async def _run(args: argparse.Namespace) -> None:
    service = _service(args.config)
    try:
        if args.action == "status":
            print(json.dumps(await service.status(), ensure_ascii=False, indent=2))
        elif args.action in {"reconcile", "reindex"}:
            count = await service.reconcile(force=args.action == "reindex")
            print(json.dumps({"indexed": count, **await service.status()}, ensure_ascii=False, indent=2))
        elif args.action == "search":
            request = RequestContext(
                channel="cli",
                chat_id="semantic-memory-admin",
                session_key=args.session,
                original_user_text=args.query,
            )
            hits = await service.retrieve(request)
            print(json.dumps([
                {
                    "source": hit.source_type,
                    "reference": hit.source_key,
                    "timestamp": hit.source_timestamp,
                    "score": hit.score,
                    "content": hit.content,
                }
                for hit in hits
            ], ensure_ascii=False, indent=2))
        elif args.action == "forget":
            if not args.yes:
                raise SystemExit("forget requires --yes")
            count = await service.repository.forget(
                service.namespace,
                args.source_type,
                args.source_key,
                reason=args.reason,
            )
            print(json.dumps({"forgotten": count, "source": args.source_type,
                              "reference": args.source_key}, indent=2))
        elif args.action == "purge":
            if not args.yes:
                raise SystemExit("purge requires --yes")
            count = await service.repository.purge(service.namespace)
            print(json.dumps({"purged": count, "namespace": service.namespace}, indent=2))
    finally:
        await service.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanobot-memory",
        description="Inspect and maintain Nanobot's derived semantic-memory index.",
    )
    parser.add_argument("--config", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("reconcile")
    subparsers.add_parser("reindex")
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--session", default=None)
    forget = subparsers.add_parser("forget")
    forget.add_argument("source_type")
    forget.add_argument("source_key")
    forget.add_argument("--reason", default="user request")
    forget.add_argument("--yes", action="store_true")
    purge = subparsers.add_parser("purge")
    purge.add_argument("--yes", action="store_true")
    return parser


def main() -> None:
    args: Any = _parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    main()
