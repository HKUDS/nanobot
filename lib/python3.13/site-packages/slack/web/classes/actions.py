from slack_sdk.models.attachments import AbstractActionSelector  # noqa
from slack_sdk.models.attachments import Action  # noqa
from slack_sdk.models.attachments import ActionButton  # noqa
from slack_sdk.models.attachments import ActionChannelSelector  # noqa
from slack_sdk.models.attachments import ActionConversationSelector  # noqa
from slack_sdk.models.attachments import ActionExternalSelector  # noqa
from slack_sdk.models.attachments import ActionLinkButton  # noqa
from slack_sdk.models.attachments import ActionUserSelector  # noqa
from slack_sdk.models.dialogs import ActionStaticSelector  # noqa

from slack import deprecation

deprecation.show_message(__name__, "slack_sdk.models.attachments/dialogs")
