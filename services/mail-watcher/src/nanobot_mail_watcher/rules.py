"""Deterministic classification of untrusted email headers."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from fnmatch import fnmatchcase

from nanobot_mail_watcher.config import AccountConfig, RuleConfig
from nanobot_mail_watcher.models import ParsedMessage, RoutingDecision


def parse_message(raw: bytes) -> ParsedMessage:
    """Parse only routing metadata; email content is data and is never executed."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender = parseaddr(str(message.get("From", "")))[1].strip().lower()
    subject = str(message.get("Subject", "")).strip()
    headers: dict[str, list[str]] = {}
    for name, value in message.raw_items():
        headers.setdefault(name.lower(), []).append(str(value))
    return ParsedMessage(sender=sender, subject=subject, headers=headers)


def classify(message: ParsedMessage, config: AccountConfig) -> RoutingDecision:
    for rule in config.rules:
        if _matches(rule, message):
            return RoutingDecision(rule.name, rule.destination, message.sender, message.subject)
    return RoutingDecision(None, config.unmatched_destination, message.sender, message.subject)


def _matches(rule: RuleConfig, message: ParsedMessage) -> bool:
    if rule.sender_globs:
        sender = message.sender.casefold()
        if not any(fnmatchcase(sender, pattern.casefold()) for pattern in rule.sender_globs):
            return False
    if rule.subject_contains:
        subject = message.subject.casefold()
        if not any(needle.casefold() in subject for needle in rule.subject_contains):
            return False
    for header, needles in rule.header_contains.items():
        values = "\n".join(message.headers.get(header.casefold(), ())).casefold()
        if not any(needle.casefold() in values for needle in needles):
            return False
    return True
