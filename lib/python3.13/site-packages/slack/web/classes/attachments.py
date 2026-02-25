from slack_sdk.models.attachments import Attachment  # noqa
from slack_sdk.models.attachments import AttachmentField  # noqa
from slack_sdk.models.attachments import BlockAttachment  # noqa
from slack_sdk.models.attachments import InteractiveAttachment  # noqa
from slack_sdk.models.attachments import SeededColors  # noqa

from slack import deprecation

deprecation.show_message(__name__, "slack_sdk.models.attachments")
