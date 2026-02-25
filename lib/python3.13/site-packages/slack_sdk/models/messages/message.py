import logging
import os
import warnings
from typing import Optional, Sequence

from slack_sdk.models import extract_json
from slack_sdk.models.attachments import Attachment
from slack_sdk.models.basic_objects import (
    JsonObject,
    JsonValidator,
)
from slack_sdk.models.blocks import Block

LOGGER = logging.getLogger(__name__)

skip_warn = os.environ.get("SLACKCLIENT_SKIP_DEPRECATION")  # for unit tests etc.
if not skip_warn:
    message = "This class is no longer actively maintained. " "Please use a dict object for building message data instead."
    warnings.warn(message)


class Message(JsonObject):
    attributes = {"text"}

    attachments_max_length = 100

    def __init__(
        self,
        *,
        text: str,
        attachments: Optional[Sequence[Attachment]] = None,
        blocks: Optional[Sequence[Block]] = None,
        markdown: bool = True,
    ):
        """
        Create a message.

        https://docs.slack.dev/messaging/#message-structure

        Args:
            text: Plain or Slack Markdown-like text to display in the message.
            attachments: A list of Attachment objects to display after the rest of
                the message's content. More than 20 is not recommended, but the actual
                limit is 100
            blocks: A list of Block objects to attach to this message. If
                specified, the 'text' property is ignored (more specifically, it's used
                as a fallback on clients that can't render blocks)
            markdown: Whether to parse markdown into formatting such as
                bold/italics, or leave text completely unmodified.
        """
        self.text = text
        self.attachments = attachments or []
        self.blocks = blocks or []
        self.markdown = markdown

    @JsonValidator(f"attachments attribute cannot exceed {attachments_max_length} items")
    def attachments_length(self):
        return self.attachments is None or len(self.attachments) <= self.attachments_max_length

    def to_dict(self) -> dict:
        json = super().to_dict()
        if len(self.text) > 40000:
            LOGGER.error("Messages over 40,000 characters are automatically truncated by Slack")
        # The following limitation used to be true in the past.
        # As of Feb 2021, having both is recommended
        # -----------------
        # if self.text and self.blocks:
        #     #  Slack doesn't render the text property if there are blocks, so:
        #     LOGGER.info(q
        #         "text attribute is treated as fallback text if blocks are attached to "
        #         "a message - insert text as a new SectionBlock if you want it to be "
        #         "displayed "
        #     )
        json["attachments"] = extract_json(self.attachments)
        json["blocks"] = extract_json(self.blocks)
        json["mrkdwn"] = self.markdown
        return json
