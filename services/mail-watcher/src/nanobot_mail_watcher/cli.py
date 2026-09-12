"""Administrative and Carillon-hook CLI."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from nanobot_mail_watcher.config import MailAutomationConfig, default_config_path, load_config
from nanobot_mail_watcher.himalaya import HimalayaClient
from nanobot_mail_watcher.models import MailEvent
from nanobot_mail_watcher.store import MailEventStore
from nanobot_mail_watcher.worker import MailWorker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanobot-mail",
        description="Durable Carillon-to-Himalaya mailbox automation",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=default_config_path(),
        help="mail automation TOML path",
    )
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser("init", help="validate config and initialize the SQLite queue")

    enqueue = subparsers.add_parser("enqueue", help="enqueue one Carillon message-added event")
    enqueue.add_argument("--account", required=True)
    enqueue.add_argument("--mailbox", required=True)
    enqueue.add_argument("--uid", required=True)
    enqueue.add_argument("--uid-validity", default="unknown")

    enqueue_env = subparsers.add_parser(
        "enqueue-env", help="enqueue one Carillon event from its id/mailbox environment"
    )
    enqueue_env.add_argument("--account", required=True)

    work = subparsers.add_parser("work", help="process queued events")
    work.add_argument("--once", action="store_true", help="process one batch and exit")
    work.add_argument("--batch-size", type=int, default=20)

    subparsers.add_parser("reconcile", help="scan every approved source mailbox for missed UIDs")

    subparsers.add_parser("status", help="show queue counts")

    audit = subparsers.add_parser("audit", help="show the audit trail for one event")
    audit.add_argument("event_id", type=int)

    subparsers.add_parser("check", help="check Himalaya and every configured account")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
        store = MailEventStore(config.worker.database)
        if args.action == "init":
            print(json.dumps(_status(config, store), indent=2))
            return 0
        if args.action == "enqueue":
            return _enqueue(config, store, args.account, args.mailbox, args.uid, args.uid_validity)
        if args.action == "enqueue-env":
            return _enqueue_from_env(config, store, args.account)
        if args.action == "work":
            if args.batch_size < 1 or args.batch_size > 1000:
                raise ValueError("batch-size must be between 1 and 1000")
            worker = MailWorker(config, store=store)
            if args.once:
                worker.recover()
                processed = worker.run_batch(limit=args.batch_size)
                print(json.dumps({"processed": processed, **store.counts()}))
                return 0
            worker.run_forever()
            return 0
        if args.action == "reconcile":
            report = MailWorker(config, store=store).reconcile()
            print(json.dumps(report, ensure_ascii=False))
            return 1 if report["failed"] else 0
        if args.action == "status":
            print(json.dumps(_status(config, store), indent=2))
            return 0
        if args.action == "audit":
            print(json.dumps(store.audit(args.event_id), ensure_ascii=False, indent=2))
            return 0
        if args.action == "check":
            return _check(config)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1


def _enqueue(
    config: MailAutomationConfig,
    store: MailEventStore,
    account: str,
    mailbox: str,
    uid: str,
    uid_validity: str,
) -> int:
    policy = config.accounts.get(account)
    if policy is None:
        raise ValueError(f"unknown account: {account}")
    if mailbox not in policy.source_mailboxes:
        raise ValueError(f"mailbox {mailbox!r} is not approved for account {account!r}")
    event_id, created = store.enqueue(MailEvent(account, mailbox, uid, uid_validity))
    print(json.dumps({"event_id": event_id, "created": created}))
    return 0


def _enqueue_from_env(
    config: MailAutomationConfig, store: MailEventStore, account: str
) -> int:
    try:
        mailbox = os.environ["mailbox"]
        uid = os.environ["id"]
    except KeyError as exc:
        raise ValueError(f"Carillon environment variable is missing: {exc.args[0]}") from exc
    return _enqueue(config, store, account, mailbox, uid, "unknown")


def _check(config: MailAutomationConfig) -> int:
    client = HimalayaClient(config.worker)
    result: dict[str, object] = {"himalaya": client.check_version(), "accounts": {}}
    accounts_result: dict[str, object] = {}
    result["accounts"] = accounts_result
    for account, policy in config.accounts.items():
        mailbox_result: dict[str, str] = {}
        for mailbox in policy.source_mailboxes:
            mailbox_result[mailbox] = client.uid_validity(account, mailbox)
        accounts_result[account] = mailbox_result
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _status(config: MailAutomationConfig, store: MailEventStore) -> dict[str, object]:
    return {
        "config": str(config.path),
        "database": str(store.path),
        "dry_run": config.worker.dry_run,
        "accounts": sorted(config.accounts),
        "queue": store.counts(),
    }


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":  # pragma: no cover
    main()
