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
"""This module contains helper functions related to parsing updates and their contents.

.. versionadded:: 20.8

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from telegram._utils.types import SCT


def parse_chat_id(chat_id: SCT[int] | None) -> frozenset[int]:
    """Accepts a chat id or collection of chat ids and returns a frozenset of chat ids."""
    if chat_id is None:
        return frozenset()
    if isinstance(chat_id, int):
        return frozenset({chat_id})
    return frozenset(chat_id)


def parse_username(username: SCT[str] | None) -> frozenset[str]:
    """Accepts a username or collection of usernames and returns a frozenset of usernames.
    Strips the leading ``@`` if present.
    """
    if username is None:
        return frozenset()
    if isinstance(username, str):
        return frozenset({username.removeprefix("@")})
    return frozenset(usr.removeprefix("@") for usr in username)
