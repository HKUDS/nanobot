from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from nanobot.channels.email.runtime import EmailChannel


def test_attached_email_is_not_included_in_message_body():
    message = EmailMessage()
    message.set_content("Please review the attached email.")
    attachment = EmailMessage()
    attachment["Subject"] = "Forwarded conversation"
    attachment.set_content("This belongs to the attached conversation.")
    message.add_attachment(attachment, filename="forwarded.eml")
    parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())

    assert EmailChannel._extract_text_body(parsed) == "Please review the attached email."


def test_multipart_alternative_still_prefers_plain_text():
    message = EmailMessage()
    message.set_content("Plain body.")
    message.add_alternative("<p>HTML body.</p>", subtype="html")
    parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())

    assert EmailChannel._extract_text_body(parsed) == "Plain body."
