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
"""This module contains the class that represent a Telegram InlineQueryResultsButton."""

from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict
from telegram._webappinfo import WebAppInfo

if TYPE_CHECKING:
    from telegram import Bot


class InlineQueryResultsButton(TelegramObject):
    """This object represents a button to be shown above inline query results. You **must** use
    exactly one of the optional fields.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`text`, :attr:`web_app` and :attr:`start_parameter` are equal.

    Args:
        text (:obj:`str`): Label text on the button.
        web_app (:class:`telegram.WebAppInfo`, optional): Description of the
            `Web App <https://core.telegram.org/bots/webapps>`_ that will be launched when the
            user presses the button. The Web App will be able to switch back to the inline mode
            using the method
            `switchInlineQuery <https://core.telegram.org/bots/webapps#initializing-mini-apps>`_
            inside the Web App.
        start_parameter (:obj:`str`, optional):  Deep-linking parameter for the
            :guilabel:`/start` message sent to the bot when user presses the switch button.
            :tg-const:`telegram.constants.InlineQueryResultsButtonLimit.MIN_START_PARAMETER_LENGTH`
            -
            :tg-const:`telegram.constants.InlineQueryResultsButtonLimit.MAX_START_PARAMETER_LENGTH`
            characters, only ``A-Z``, ``a-z``, ``0-9``, ``_`` and ``-`` are allowed.

            Example:
                An inline bot that sends YouTube videos can ask the user to connect the bot to
                their YouTube account to adapt search results accordingly. To do this, it displays
                a 'Connect your YouTube account' button above the results, or even before showing
                any. The user presses the button, switches to a private chat with the bot and, in
                doing so, passes a start parameter that instructs the bot to return an OAuth link.
                Once done, the bot can offer a switch_inline button so that the user can easily
                return to the chat where they wanted to use the bot's inline capabilities.

    Attributes:
        text (:obj:`str`): Label text on the button.
        web_app (:class:`telegram.WebAppInfo`): Optional. Description of the
            `Web App <https://core.telegram.org/bots/webapps>`_ that will be launched when the
            user presses the button. The Web App will be able to switch back to the inline mode
            using the method ``web_app_switch_inline_query`` inside the Web App.
        start_parameter (:obj:`str`): Optional. Deep-linking parameter for the
            :tg-const:`telegram.constants.InlineQueryResultsButtonLimit.MIN_START_PARAMETER_LENGTH`
            -
            :tg-const:`telegram.constants.InlineQueryResultsButtonLimit.MAX_START_PARAMETER_LENGTH`
            characters, only ``A-Z``, ``a-z``, ``0-9``, ``_`` and ``-`` are allowed.

    """

    __slots__ = ("start_parameter", "text", "web_app")

    def __init__(
        self,
        text: str,
        web_app: WebAppInfo | None = None,
        start_parameter: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        # Required
        self.text: str = text

        # Optional
        self.web_app: WebAppInfo | None = web_app
        self.start_parameter: str | None = start_parameter

        self._id_attrs = (self.text, self.web_app, self.start_parameter)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "InlineQueryResultsButton":
        """See :meth:`telegram.TelegramObject.de_json`."""

        data["web_app"] = de_json_optional(data.get("web_app"), WebAppInfo, bot)

        return super().de_json(data=data, bot=bot)

    MIN_START_PARAMETER_LENGTH: Final[int] = (
        constants.InlineQueryResultsButtonLimit.MIN_START_PARAMETER_LENGTH
    )
    """:const:`telegram.constants.InlineQueryResultsButtonLimit.MIN_START_PARAMETER_LENGTH`"""
    MAX_START_PARAMETER_LENGTH: Final[int] = (
        constants.InlineQueryResultsButtonLimit.MAX_START_PARAMETER_LENGTH
    )
    """:const:`telegram.constants.InlineQueryResultsButtonLimit.MAX_START_PARAMETER_LENGTH`"""
