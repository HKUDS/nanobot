import slack_sdk.version as slack_version  # noqa
from slack import deprecation
from slack_sdk.web.async_client import AsyncSlackResponse  # noqa
from slack_sdk.web.async_client import AsyncWebClient  # noqa
from slack_sdk.web.internal_utils import _to_0_or_1_if_bool  # noqa
from slack_sdk.web.internal_utils import convert_bool_to_0_or_1  # noqa
from slack_sdk.web.internal_utils import get_user_agent  # noqa
from slack_sdk.web.legacy_client import LegacyWebClient as WebClient  # noqa
from slack_sdk.web.slack_response import SlackResponse  # noqa

deprecation.show_message(__name__, "slack_sdk.web")
