from __future__ import annotations

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter


def _router() -> CommandRouter:
    router = CommandRouter()
    register_builtin_commands(router)
    return router


def _ctx(raw: str, channel: str = "dingtalk") -> CommandContext:
    msg = InboundMessage(
        channel=channel,
        sender_id="synthetic-user",
        chat_id="group:synthetic-chat",
        content=raw,
        metadata={"synthetic": True},
    )
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, loop=None)


def test_crm_daily_command_is_dispatchable() -> None:
    assert _router().is_dispatchable_command("/crm-daily 2026-01-15")


async def test_crm_daily_command_returns_report_with_evidence_marker() -> None:
    result = await _router().dispatch(_ctx("/crm-daily 2026-01-15"))

    assert result is not None
    assert result.channel == "dingtalk"
    assert result.chat_id == "group:synthetic-chat"
    assert "Sales Daily Report" in result.content
    assert "pipeline_total_amount" in result.content
    assert "trace-pipeline-total-amount-v1" in result.content


async def test_crm_weekly_command_returns_report() -> None:
    result = await _router().dispatch(_ctx("/crm-weekly 2026-01-10 2026-01-16"))

    assert result is not None
    assert "Sales Weekly Report" in result.content
    assert "status_count.won" in result.content


async def test_crm_dashboard_command_returns_report() -> None:
    result = await _router().dispatch(_ctx("/crm-dashboard 2026-01-10 2026-01-16"))

    assert result is not None
    assert "Opportunity Dashboard Summary" in result.content
    assert "owner_count.owner-alpha" in result.content


async def test_crm_commands_reject_mutation_or_ad_hoc_actions() -> None:
    router = _router()

    assert not router.is_dispatchable_command("/crm-write anything")
    assert not router.is_dispatchable_command("/crm-task anything")
    assert not router.is_dispatchable_command("/crm-contact anything")
    assert not router.is_dispatchable_command("/crm-query select anything")
