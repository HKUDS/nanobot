from slack_sdk.errors import BotUserAccessError  # noqa
from slack_sdk.errors import SlackApiError  # noqa
from slack_sdk.errors import SlackClientError  # noqa
from slack_sdk.errors import SlackClientNotConnectedError  # noqa
from slack_sdk.errors import SlackObjectFormationError  # noqa
from slack_sdk.errors import SlackRequestError  # noqa

from slack import deprecation

deprecation.show_message(__name__, "slack_sdk.errors")
