import os
import warnings


def show_message(old: str, new: str) -> None:
    skip_deprecation = os.environ.get("SLACKCLIENT_SKIP_DEPRECATION")  # for unit tests etc.
    if skip_deprecation:
        return

    message = (
        f"{old} package is deprecated. Please use {new} package instead. "
        "For more info, go to https://docs.slack.dev/tools/python-slack-sdk/v3-migration/"
    )
    warnings.warn(message)
