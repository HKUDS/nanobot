"""Pairing module for DM sender approval."""

from nanobot.pairing.store import (
    approve_code,
    deny_code,
    format_expiry,
    format_pairing_reply,
    generate_code,
    get_approved,
    handle_pairing_command,
    is_approved,
    list_pending,
    revoke,
)

# Metadata keys used by channels and commands to tag pairing-related messages.
PAIRING_CODE_META_KEY = "_pairing_code"
PAIRING_COMMAND_META_KEY = "_pairing_command"

__all__ = [
    "approve_code",
    "deny_code",
    "format_expiry",
    "format_pairing_reply",
    "generate_code",
    "get_approved",
    "handle_pairing_command",
    "is_approved",
    "list_pending",
    "revoke",
    "PAIRING_CODE_META_KEY",
    "PAIRING_COMMAND_META_KEY",
]
