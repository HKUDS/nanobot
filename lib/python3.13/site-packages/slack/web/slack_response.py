from slack import deprecation
from slack_sdk.web.legacy_slack_response import (  # noqa
    LegacySlackResponse as SlackResponse,
)

deprecation.show_message(__name__, "slack_sdk.web.slack_response")
