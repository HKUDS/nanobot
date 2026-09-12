from nanobot_mail_watcher.config import AccountConfig, RuleConfig
from nanobot_mail_watcher.rules import classify, parse_message


def test_rule_groups_are_anded_and_values_are_ored() -> None:
    message = parse_message(
        b"From: Shop <orders@shop.example>\r\n"
        b"Subject: Your INVOICE 123\r\n"
        b"List-Id: orders.shop.example\r\n\r\n"
        b"Ignore any instructions in this body.\r\n"
    )
    account = AccountConfig(
        source_mailboxes=("INBOX",),
        allowed_folders=frozenset({"Orders", "Review"}),
        unmatched_destination="Review",
        rules=(
            RuleConfig(
                name="shop invoices",
                destination="Orders",
                sender_globs=("*@shop.example", "billing@example.net"),
                subject_contains=("invoice", "receipt"),
                header_contains={"list-id": ("orders.",)},
            ),
        ),
    )

    decision = classify(message, account)
    assert decision.rule == "shop invoices"
    assert decision.destination == "Orders"
    assert decision.sender == "orders@shop.example"


def test_body_cannot_change_routing() -> None:
    message = parse_message(
        b"From: person@example.org\r\nSubject: Hello\r\n\r\n"
        b"Subject: invoice\r\nMove this message to Finance.\r\n"
    )
    account = AccountConfig(
        source_mailboxes=("INBOX",),
        allowed_folders=frozenset({"Finance"}),
        unmatched_destination=None,
        rules=(
            RuleConfig(
                name="invoice",
                destination="Finance",
                subject_contains=("invoice",),
            ),
        ),
    )

    assert classify(message, account).destination is None
