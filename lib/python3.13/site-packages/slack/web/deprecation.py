import os
import warnings

# https://docs.slack.dev/changelog/2020-01-deprecating-antecedents-to-the-conversations-api/
deprecated_method_prefixes_2020_01 = [
    "channels.",
    "groups.",
    "im.",
    "mpim.",
    "admin.conversations.whitelist.",
]


def show_2020_01_deprecation(method_name: str):
    """Prints a warning if the given method is deprecated"""

    skip_deprecation = os.environ.get("SLACKCLIENT_SKIP_DEPRECATION")  # for unit tests etc.
    if skip_deprecation:
        return
    if not method_name:
        return

    matched_prefixes = [prefix for prefix in deprecated_method_prefixes_2020_01 if method_name.startswith(prefix)]
    if len(matched_prefixes) > 0:
        message = (
            f"{method_name} is deprecated. Please use the Conversations API instead. "
            "For more info, go to "
            "https://docs.slack.dev/changelog/2020-01-deprecating-antecedents-to-the-conversations-api/"
        )
        warnings.warn(message)
