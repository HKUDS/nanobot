from slack_sdk.models import BaseObject  # noqa
from slack_sdk.models import JsonObject  # noqa
from slack_sdk.models import JsonValidator  # noqa
from slack_sdk.models import EnumValidator  # noqa
from slack_sdk.models import extract_json  # noqa
from slack_sdk.models import show_unknown_key_warning  # noqa

from slack import deprecation

deprecation.show_message(__name__, "slack_sdk.models")
