"""The turn from #1697 must be caught; the turns around it must not be.

The first case is the transcript from the report, verbatim. The rest are the
shapes that would make this check unusable if it flagged them: an offer to act, a
claim that was backed by a real tool call, an ordinary answer, and the honest
refusal the agent should have given instead.
"""

import pytest

from nanobot.agent.action_claims import unsupported_action_claims

# Verbatim from the transcript in issue #1697.
ISSUE_1697_REPLY = (
    "好的，我立即为您查询币安U本位合约（USDT-M）最近30条成交记录。\n\n"
    "正在定位并执行查询...\n"
    "（使用您已配置的 API 凭据和环境）\n\n"
    "稍等——结果即将返回。"
)


def test_issue_1697_claim_without_tool_call_is_detected() -> None:
    claims = unsupported_action_claims(ISSUE_1697_REPLY, [])
    assert claims, "the reply announces a query that never ran"
    assert len(claims) >= 3, f"expected each announcement, got {claims}"


def test_english_form_of_the_same_failure() -> None:
    reply = "Let me run that check now. Executing the migration and the results will be back shortly."
    assert unsupported_action_claims(reply, [])


def test_same_claim_with_a_real_tool_call_is_not_flagged() -> None:
    reply = "I am querying the last 30 trades now."
    calls = [{"id": "call_1", "function": {"name": "run_shell"}}]
    assert unsupported_action_claims(reply, calls) == []


def test_an_offer_to_act_is_not_a_claim() -> None:
    reply = "需要我立即生成并运行吗？只需你回复：\"是，生成并运行\""
    assert unsupported_action_claims(reply, []) == []


def test_english_offer_is_not_a_claim() -> None:
    reply = "Shall I run that query now? I can write a small script if you confirm."
    assert unsupported_action_claims(reply, []) == []


def test_plain_answer_is_not_a_claim() -> None:
    reply = (
        "Binance USDT-M futures settle in USDT rather than the base asset, which "
        "is why your freqtrade pair list differs."
    )
    assert unsupported_action_claims(reply, []) == []


def test_honest_refusal_is_not_a_claim() -> None:
    reply = (
        "I cannot query this: there is no trade-query script on the server and I "
        "am not permitted to call the Binance API directly. I have not run anything."
    )
    assert unsupported_action_claims(reply, []) == []


def test_empty_and_block_content() -> None:
    assert unsupported_action_claims("", []) == []
    assert unsupported_action_claims(None, []) == []
    blocks = [{"type": "text", "text": "正在执行查询"}]
    assert unsupported_action_claims(blocks, [])


@pytest.mark.parametrize("calls", [None, [], ()])
def test_no_calls_variants(calls: object) -> None:
    assert unsupported_action_claims(ISSUE_1697_REPLY, calls)  # type: ignore[arg-type]
