"""Strict, dependency-free TOML configuration loader."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class RuleConfig:
    name: str
    destination: str
    sender_globs: tuple[str, ...] = ()
    subject_contains: tuple[str, ...] = ()
    header_contains: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AccountConfig:
    source_mailboxes: tuple[str, ...]
    allowed_folders: frozenset[str]
    unmatched_destination: str | None
    rules: tuple[RuleConfig, ...]


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    database: Path
    himalaya_binary: str
    himalaya_config: Path | None
    dry_run: bool
    command_timeout_seconds: float
    max_message_bytes: int
    max_attempts: int
    retry_base_seconds: float
    stale_after_seconds: float
    poll_seconds: float
    reconcile_interval_seconds: float = 180.0
    reconcile_max_messages: int = 5_000
    reconcile_max_response_bytes: int = 2_000_000


@dataclass(frozen=True, slots=True)
class MailAutomationConfig:
    path: Path
    worker: WorkerConfig
    accounts: dict[str, AccountConfig]


def default_config_path() -> Path:
    configured = os.environ.get("NANOBOT_MAIL_CONFIG")
    return Path(configured).expanduser() if configured else Path.home() / ".nanobot" / "mail.toml"


def load_config(path: Path | None = None) -> MailAutomationConfig:
    config_path = (path or default_config_path()).expanduser().resolve()
    try:
        with config_path.open("rb") as handle:
            document = cast(dict[str, Any], tomllib.load(handle))
    except FileNotFoundError as exc:
        raise ValueError(f"mail config not found: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML in {config_path}: {exc}") from exc

    _only_keys(document, {"worker", "accounts"}, "root")
    worker = _parse_worker(_table(document.get("worker", {}), "worker"), config_path.parent)
    accounts_raw = _table(document.get("accounts"), "accounts")
    if not accounts_raw:
        raise ValueError("accounts must define at least one account")
    accounts: dict[str, AccountConfig] = {}
    for raw_name, raw_account in accounts_raw.items():
        name = _text(raw_name, "account name", maximum=128)
        accounts[name] = _parse_account(_table(raw_account, f"accounts.{name}"), name)
    return MailAutomationConfig(path=config_path, worker=worker, accounts=accounts)


def _parse_worker(raw: dict[str, Any], base: Path) -> WorkerConfig:
    allowed = {
        "database",
        "himalaya_binary",
        "himalaya_config",
        "dry_run",
        "command_timeout_seconds",
        "max_message_bytes",
        "max_attempts",
        "retry_base_seconds",
        "stale_after_seconds",
        "poll_seconds",
        "reconcile_interval_seconds",
        "reconcile_max_messages",
        "reconcile_max_response_bytes",
    }
    _only_keys(raw, allowed, "worker")
    database = _path(raw.get("database", "mail/events.sqlite3"), "worker.database", base)
    himalaya_config_raw = raw.get("himalaya_config")
    himalaya_config = (
        _path(himalaya_config_raw, "worker.himalaya_config", base)
        if himalaya_config_raw is not None
        else None
    )
    binary = Path(_text(raw.get("himalaya_binary", "/usr/bin/himalaya"), "himalaya_binary"))
    if not binary.is_absolute():
        raise ValueError("worker.himalaya_binary must be an absolute path")
    command_timeout = _number(
        raw.get("command_timeout_seconds", 30), "command_timeout_seconds", 1, 300
    )
    stale_after = _number(
        raw.get("stale_after_seconds", 300), "stale_after_seconds", 10, 86400
    )
    if stale_after < command_timeout * 2 + 10:
        raise ValueError(
            "worker.stale_after_seconds must be at least twice command_timeout_seconds plus 10"
        )
    return WorkerConfig(
        database=database,
        himalaya_binary=str(binary),
        himalaya_config=himalaya_config,
        dry_run=_boolean(raw.get("dry_run", True), "dry_run"),
        command_timeout_seconds=command_timeout,
        max_message_bytes=_integer(
            raw.get("max_message_bytes", 2_000_000), "max_message_bytes", 1024, 50_000_000
        ),
        max_attempts=_integer(raw.get("max_attempts", 8), "max_attempts", 1, 100),
        retry_base_seconds=_number(
            raw.get("retry_base_seconds", 5), "retry_base_seconds", 0.1, 3600
        ),
        stale_after_seconds=stale_after,
        poll_seconds=_number(raw.get("poll_seconds", 2), "poll_seconds", 0.1, 300),
        reconcile_interval_seconds=_number(
            raw.get("reconcile_interval_seconds", 180),
            "reconcile_interval_seconds",
            120,
            300,
        ),
        reconcile_max_messages=_integer(
            raw.get("reconcile_max_messages", 5_000),
            "reconcile_max_messages",
            1,
            50_000,
        ),
        reconcile_max_response_bytes=_integer(
            raw.get("reconcile_max_response_bytes", 2_000_000),
            "reconcile_max_response_bytes",
            1_024,
            20_000_000,
        ),
    )


def _parse_account(raw: dict[str, Any], account: str) -> AccountConfig:
    _only_keys(
        raw,
        {"source_mailboxes", "allowed_folders", "unmatched_destination", "rules"},
        f"accounts.{account}",
    )
    sources = tuple(
        _text(item, f"accounts.{account}.source_mailboxes[]", maximum=1024)
        for item in _list(raw.get("source_mailboxes", ["INBOX"]), "source_mailboxes")
    )
    if not sources or len(sources) != len(set(sources)):
        raise ValueError(f"accounts.{account}.source_mailboxes must be non-empty and unique")
    for mailbox in sources:
        _safe_mailbox(mailbox)
    allowed = frozenset(
        _text(item, f"accounts.{account}.allowed_folders[]", maximum=1024)
        for item in _list(raw.get("allowed_folders", []), "allowed_folders")
    )
    for mailbox in allowed:
        _safe_mailbox(mailbox)
    unmatched_raw = raw.get("unmatched_destination")
    unmatched = (
        _text(unmatched_raw, f"accounts.{account}.unmatched_destination", maximum=1024)
        if unmatched_raw is not None
        else None
    )
    rules_raw = _list(raw.get("rules", []), f"accounts.{account}.rules")
    rules = tuple(
        _parse_rule(_table(value, f"accounts.{account}.rules[{index}]"), account, index)
        for index, value in enumerate(rules_raw)
    )
    destinations = {rule.destination for rule in rules}
    if unmatched:
        destinations.add(unmatched)
    missing = sorted(destinations - allowed)
    if missing:
        raise ValueError(
            f"accounts.{account} destinations are not in allowed_folders: {missing}"
        )
    return AccountConfig(sources, allowed, unmatched, rules)


def _parse_rule(raw: dict[str, Any], account: str, index: int) -> RuleConfig:
    where = f"accounts.{account}.rules[{index}]"
    _only_keys(
        raw,
        {"name", "destination", "sender_globs", "subject_contains", "header_contains"},
        where,
    )
    sender_globs = _text_tuple(raw.get("sender_globs", []), f"{where}.sender_globs")
    subject_contains = _text_tuple(
        raw.get("subject_contains", []), f"{where}.subject_contains"
    )
    header_raw = _table(raw.get("header_contains", {}), f"{where}.header_contains")
    header_contains = {
        _text(name, f"{where}.header name", maximum=256).lower(): _text_tuple(
            values, f"{where}.header_contains.{name}"
        )
        for name, values in header_raw.items()
    }
    if not (sender_globs or subject_contains or header_contains):
        raise ValueError(f"{where} needs at least one condition")
    return RuleConfig(
        name=_text(raw.get("name"), f"{where}.name"),
        destination=_text(raw.get("destination"), f"{where}.destination", maximum=1024),
        sender_globs=sender_globs,
        subject_contains=subject_contains,
        header_contains=header_contains,
    )


def _table(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a TOML table")
    return cast(dict[str, Any], value)


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a TOML array")
    return cast(list[Any], value)


def _text(value: object, name: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{name} must be a non-empty string up to {maximum} characters")
    if "\x00" in value:
        raise ValueError(f"{name} contains a forbidden NUL character")
    return value.strip()


def _text_tuple(value: object, name: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{name}[]", maximum=1024) for item in _list(value, name))


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"worker.{name} must be true or false")
    return value


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"worker.{name} must be between {minimum} and {maximum}")
    return value


def _number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"worker.{name} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"worker.{name} must be between {minimum} and {maximum}")
    return result


def _path(value: object, name: str, base: Path) -> Path:
    path = Path(_text(value, name, maximum=4096)).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _safe_mailbox(mailbox: str) -> None:
    if mailbox.startswith("-") or any(ch in mailbox for ch in "\r\n\x00"):
        raise ValueError(f"unsupported or unsafe mailbox name: {mailbox!r}")


def _only_keys(raw: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown keys in {where}: {unknown}")
