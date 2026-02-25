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

deprecated_method_prefixes_2023_07 = ["stars."]

deprecated_method_prefixes_2024_09 = ["workflows.stepCompleted", "workflows.updateStep", "workflows.stepFailed"]


def show_deprecation_warning_if_any(method_name: str):
    """Prints a warning if the given method is deprecated"""

    skip_deprecation = os.environ.get("SLACKCLIENT_SKIP_DEPRECATION")  # for unit tests etc.
    if skip_deprecation:
        return
    if not method_name:
        return

    # 2020/01 conversations API deprecation
    matched_prefixes = [prefix for prefix in deprecated_method_prefixes_2020_01 if method_name.startswith(prefix)]
    if len(matched_prefixes) > 0:
        message = (
            f"{method_name} is deprecated. Please use the Conversations API instead. "
            "For more info, go to "
            "https://docs.slack.dev/changelog/2020-01-deprecating-antecedents-to-the-conversations-api/"
        )
        warnings.warn(message)

    # 2023/07 stars API deprecation
    matched_prefixes = [prefix for prefix in deprecated_method_prefixes_2023_07 if method_name.startswith(prefix)]
    if len(matched_prefixes) > 0:
        message = (
            f"{method_name} is deprecated. For more info, go to "
            "https://docs.slack.dev/changelog/2023-07-its-later-already-for-stars-and-reminders/"
        )
        warnings.warn(message)

    # 2024/09 workflow steps API deprecation
    matched_prefixes = [prefix for prefix in deprecated_method_prefixes_2024_09 if method_name.startswith(prefix)]
    if len(matched_prefixes) > 0:
        message = (
            f"{method_name} is deprecated. For more info, go to "
            "https://docs.slack.dev/changelog/2023-08-workflow-steps-from-apps-step-back/"
        )
        warnings.warn(message)
