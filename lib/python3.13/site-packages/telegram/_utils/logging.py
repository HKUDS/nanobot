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
"""This module contains helper functions related to logging.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

import logging


def get_logger(file_name: str, class_name: str | None = None) -> logging.Logger:
    """Returns a logger with an appropriate name.
    Use as follows::

        logger = get_logger(__name__)

    If for example `__name__` is `telegram.ext._updater`, the logger will be named
    `telegram.ext.Updater`. If `class_name` is passed, this will result in
    `telegram.ext.<class_name>`. Useful e.g. for CamelCase class names.

    If the file name points to a utils module, the logger name will simply be `telegram(.ext)`.

    Returns:
        :class:`logging.Logger`: The logger.
    """
    parts = file_name.split("_")
    if parts[1].startswith("utils") and class_name is None:
        name = parts[0].rstrip(".")
    else:
        name = f"{parts[0]}{class_name or parts[1].capitalize()}"
    return logging.getLogger(name)
