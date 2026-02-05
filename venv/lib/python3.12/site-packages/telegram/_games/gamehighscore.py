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
"""This module contains an object that represents a Telegram GameHighScore."""

from typing import TYPE_CHECKING

from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class GameHighScore(TelegramObject):
    """This object represents one row of the high scores table for a game.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`position`, :attr:`user` and :attr:`score` are equal.

    Args:
        position (:obj:`int`): Position in high score table for the game.
        user (:class:`telegram.User`): User.
        score (:obj:`int`): Score.

    Attributes:
        position (:obj:`int`): Position in high score table for the game.
        user (:class:`telegram.User`): User.
        score (:obj:`int`): Score.

    """

    __slots__ = ("position", "score", "user")

    def __init__(
        self, position: int, user: User, score: int, *, api_kwargs: JSONDict | None = None
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.position: int = position
        self.user: User = user
        self.score: int = score

        self._id_attrs = (self.position, self.user, self.score)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "GameHighScore":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["user"] = de_json_optional(data.get("user"), User, bot)

        return super().de_json(data=data, bot=bot)
