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
"""This module contains helper functions related to inspecting the program stack.

.. versionadded:: 20.0

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from pathlib import Path
from types import FrameType

from telegram._utils.logging import get_logger

_LOGGER = get_logger(__name__)


def was_called_by(frame: FrameType | None, caller: Path) -> bool:
    """Checks if the passed frame was called by the specified file.

    Example:
        .. code:: pycon

            >>> was_called_by(inspect.currentframe(), Path(__file__))
            True

    Arguments:
        frame (:obj:`FrameType`): The frame - usually the return value of
            ``inspect.currentframe()``. If :obj:`None` is passed, the return value will be
            :obj:`False`.
        caller (:obj:`pathlib.Path`): File that should be the caller.

    Returns:
        :obj:`bool`: Whether the frame was called by the specified file.
    """
    if frame is None:
        return False

    try:
        return _was_called_by(frame, caller)
    except Exception as exc:
        _LOGGER.debug(
            "Failed to check if frame was called by `caller`. Assuming that it was not.",
            exc_info=exc,
        )
        return False


def _was_called_by(frame: FrameType, caller: Path) -> bool:
    # https://stackoverflow.com/a/57712700/10606962
    if Path(frame.f_code.co_filename).resolve() == caller:
        return True
    while frame.f_back:
        frame = frame.f_back
        if Path(frame.f_code.co_filename).resolve() == caller:
            return True
    return False
