"""Internal module for checking aiohttp compatibility of async modules"""

import logging
from typing import Callable


def _print_warning_log(message: str) -> None:
    logging.getLogger(__name__).warning(message)


def validate_aiohttp_version(
    aiohttp_version: str,
    print_warning: Callable[[str], None] = _print_warning_log,
):
    if aiohttp_version is not None:
        elements = aiohttp_version.split(".")
        if len(elements) >= 3:
            # patch version can be a non-numeric value
            major, minor, patch = int(elements[0]), int(elements[1]), elements[2]
            if major <= 2 or (major == 3 and (minor == 6 or (minor == 7 and patch == "0"))):
                print_warning(
                    "We highly recommend upgrading aiohttp to 3.7.3 or higher versions."
                    "An older version of the library may not work with the Slack server-side in the future."
                )
