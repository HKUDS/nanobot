#!/usr/bin/env python
#
# A library that provides a Python interface to the Telegram Bot API
# Copyright (C) 2015-2026
# Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
"""This module contains functionality used for transition warnings issued by this library.

It was created to prevent circular imports that would be caused by creating the warnings
inside warnings.py.

.. versionadded:: 20.2
"""

from collections.abc import Callable
from typing import Any

from telegram._utils.warnings import warn
from telegram.warnings import PTBDeprecationWarning, PTBUserWarning


def build_deprecation_warning_message(
    deprecated_name: str,
    new_name: str,
    object_type: str,
    bot_api_version: str,
) -> str:
    """Builds a warning message for the transition in API when an object is renamed/replaced.

    Returns a warning message that can be used in `warn` function.
    """
    return (
        f"The {object_type} '{deprecated_name}' was replaced by '{new_name}' in Bot API "
        f"{bot_api_version}. We recommend using '{new_name}' instead of "
        f"'{deprecated_name}'."
    )


# Narrower type hints will cause linting errors and/or circular imports.
# We'll use `Any` here and put type hints in the calling code.
def warn_about_deprecated_arg_return_new_arg(
    deprecated_arg: Any,
    new_arg: Any,
    deprecated_arg_name: str,
    new_arg_name: str,
    bot_api_version: str,
    ptb_version: str,
    stacklevel: int = 2,
    warn_callback: Callable[[str | PTBUserWarning, type[Warning], int], None] = warn,
) -> Any:
    """A helper function for the transition in API when argument is renamed.

    Checks the `deprecated_arg` and `new_arg` objects; warns if non-None `deprecated_arg` object
    was passed. Returns `new_arg` object (either the one originally passed by the user or the one
    that user passed as `deprecated_arg`).

    Raises `ValueError` if both `deprecated_arg` and `new_arg` objects were passed, and they are
    different.
    """
    if deprecated_arg and new_arg and deprecated_arg != new_arg:
        base_message = build_deprecation_warning_message(
            deprecated_name=deprecated_arg_name,
            new_name=new_arg_name,
            object_type="parameter",
            bot_api_version=bot_api_version,
        )
        raise ValueError(
            f"You passed different entities as '{deprecated_arg_name}' and '{new_arg_name}'. "
            f"{base_message}"
        )

    if deprecated_arg:
        warn_callback(
            PTBDeprecationWarning(
                ptb_version,
                f"Bot API {bot_api_version} renamed the argument '{deprecated_arg_name}' to "
                f"'{new_arg_name}'.",
            ),
            stacklevel=stacklevel + 1,  # type: ignore[call-arg]
        )
        return deprecated_arg

    return new_arg


def warn_about_deprecated_attr_in_property(
    deprecated_attr_name: str,
    new_attr_name: str,
    bot_api_version: str,
    ptb_version: str,
    stacklevel: int = 2,
) -> None:
    """A helper function for the transition in API when attribute is renamed. Call from properties.

    The properties replace deprecated attributes in classes and issue these deprecation warnings.
    """
    warn(
        PTBDeprecationWarning(
            ptb_version,
            f"Bot API {bot_api_version} renamed the attribute '{deprecated_attr_name}' to "
            f"'{new_attr_name}'.",
        ),
        stacklevel=stacklevel + 1,
    )
