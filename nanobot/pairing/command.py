"""User-facing results of the /pairing command."""

import time
from collections.abc import Callable

from nanobot.bus.outbound_events import CommandLine
from nanobot.command.results import line
from nanobot.pairing import store


def pairing_command_lines(
    channel: str, args: str, *, on_change: Callable[[], object] | None = None,
) -> list[CommandLine]:
    parts = args.split()
    sub = parts[0] if parts else "list"
    if sub == "list":
        pending = store.list_pending()
        if not pending:
            return [line("pairing.empty")]
        result = [line("pairing.pending")]
        now = time.time()
        for item in pending:
            remaining = int(item["expires_at"] - now)
            values = {"code": item["code"], "channel": item["channel"], "sender": str(item["sender_id"])}
            result.append(
                line("pairing.entry", **values, seconds=remaining) if remaining > 0
                else line("pairing.expired_entry", **values)
            )
        return result

    # A store failure is not an invalid code, nor a successful mutation.
    try:
        if sub == "approve":
            if len(parts) < 2:
                return [line("pairing.usage", syntax="/pairing approve <code>")]
            code = parts[1]
            approved = store.approve_code(code, on_change=on_change)
            if approved is None:
                return [line("pairing.invalid", code=code)]
            target, sender = approved
            return [line("pairing.approved", code=code, sender=sender, channel=target)]

        if sub == "deny":
            if len(parts) < 2:
                return [line("pairing.usage", syntax="/pairing deny <code>")]
            code = parts[1]
            if store.deny_code(code, on_change=on_change):
                return [line("pairing.denied", code=code)]
            return [line("pairing.not_found", code=code)]

        if sub == "revoke":
            if len(parts) not in (2, 3):
                return [line("pairing.revoke_usage")]
            target = parts[1] if len(parts) == 3 else channel
            sender = parts[-1]
            if store.revoke(target, sender, on_change=on_change):
                return [line("pairing.revoked", sender=sender, channel=target)]
            return [line("pairing.not_approved", sender=sender, channel=target)]

        syntax = "/pairing [list|approve <code>|deny <code>|revoke <user_id>|revoke <channel> <user_id>]"
        return [line("pairing.unknown", syntax=syntax)]
    except OSError:
        return [line("pairing.unavailable")]
