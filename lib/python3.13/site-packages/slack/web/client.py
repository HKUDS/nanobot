from slack import deprecation
from slack_sdk.web.legacy_client import LegacyWebClient as WebClient  # noqa

deprecation.show_message(__name__, "slack_sdk.web.client")
