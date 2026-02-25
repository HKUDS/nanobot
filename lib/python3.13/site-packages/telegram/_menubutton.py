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
"""This module contains objects related to Telegram menu buttons."""

from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict
from telegram._webappinfo import WebAppInfo

if TYPE_CHECKING:
    from telegram import Bot


class MenuButton(TelegramObject):
    """This object describes the bot's menu button in a private chat. It should be one of

    * :class:`telegram.MenuButtonCommands`
    * :class:`telegram.MenuButtonWebApp`
    * :class:`telegram.MenuButtonDefault`

    If a menu button other than :class:`telegram.MenuButtonDefault` is set for a private chat,
    then it is applied in the chat. Otherwise the default menu button is applied. By default, the
    menu button opens the list of bot commands.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal. For subclasses with additional attributes,
    the notion of equality is overridden.

    .. versionadded:: 20.0

    Args:
        type (:obj:`str`): Type of menu button that the instance represents.

    Attributes:
        type (:obj:`str`): Type of menu button that the instance represents.
    """

    __slots__ = ("type",)

    def __init__(
        self,
        type: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):  # pylint: disable=redefined-builtin
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.MenuButtonType, type, type)

        self._id_attrs = (self.type,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "MenuButton":
        """Converts JSON data to the appropriate :class:`MenuButton` object, i.e. takes
        care of selecting the correct subclass.

        Args:
            data (dict[:obj:`str`, ...]): The JSON data.
            bot (:class:`telegram.Bot`, optional): The bot associated with this object. Defaults to
                :obj:`None`, in which case shortcut methods will not be available.

                .. versionchanged:: 21.4
                   :paramref:`bot` is now optional and defaults to :obj:`None`

        Returns:
            The Telegram object.

        """
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[MenuButton]] = {
            cls.COMMANDS: MenuButtonCommands,
            cls.WEB_APP: MenuButtonWebApp,
            cls.DEFAULT: MenuButtonDefault,
        }

        if cls is MenuButton and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data, bot=bot)
        return super().de_json(data=data, bot=bot)

    COMMANDS: Final[str] = constants.MenuButtonType.COMMANDS
    """:const:`telegram.constants.MenuButtonType.COMMANDS`"""
    WEB_APP: Final[str] = constants.MenuButtonType.WEB_APP
    """:const:`telegram.constants.MenuButtonType.WEB_APP`"""
    DEFAULT: Final[str] = constants.MenuButtonType.DEFAULT
    """:const:`telegram.constants.MenuButtonType.DEFAULT`"""


class MenuButtonCommands(MenuButton):
    """Represents a menu button, which opens the bot's list of commands.

    .. include:: inclusions/menu_button_command_video.rst

    .. versionadded:: 20.0
    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.MenuButtonType.COMMANDS`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=constants.MenuButtonType.COMMANDS, api_kwargs=api_kwargs)
        self._freeze()


class MenuButtonWebApp(MenuButton):
    """Represents a menu button, which launches a
    `Web App <https://core.telegram.org/bots/webapps>`_.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type`, :attr:`text` and :attr:`web_app`
    are equal.

    .. versionadded:: 20.0

    Args:
        text (:obj:`str`): Text of the button.
        web_app (:class:`telegram.WebAppInfo`): Description of the Web App that will be launched
            when the user presses the button. The Web App will be able to send an arbitrary
            message on behalf of the user using the method :meth:`~telegram.Bot.answerWebAppQuery`
            of :class:`~telegram.Bot`. Alternatively, a ``t.me`` link to a Web App of the bot can
            be specified in the object instead of the Web App's URL, in which case the Web App
            will be opened as if the user pressed the link.


    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.MenuButtonType.WEB_APP`.
        text (:obj:`str`): Text of the button.
        web_app (:class:`telegram.WebAppInfo`): Description of the Web App that will be launched
            when the user presses the button. The Web App will be able to send an arbitrary
            message on behalf of the user using the method :meth:`~telegram.Bot.answerWebAppQuery`
            of :class:`~telegram.Bot`. Alternatively, a ``t.me`` link to a Web App of the bot can
            be specified in the object instead of the Web App's URL, in which case the Web App
            will be opened as if the user pressed the link.
    """

    __slots__ = ("text", "web_app")

    def __init__(self, text: str, web_app: WebAppInfo, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=constants.MenuButtonType.WEB_APP, api_kwargs=api_kwargs)
        with self._unfrozen():
            self.text: str = text
            self.web_app: WebAppInfo = web_app

            self._id_attrs = (self.type, self.text, self.web_app)

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "MenuButtonWebApp":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["web_app"] = de_json_optional(data.get("web_app"), WebAppInfo, bot)

        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]


class MenuButtonDefault(MenuButton):
    """Describes that no specific value for the menu button was set.

    .. versionadded:: 20.0
    Attributes:
        type (:obj:`str`): :tg-const:`telegram.constants.MenuButtonType.DEFAULT`.
    """

    __slots__ = ()

    def __init__(self, *, api_kwargs: JSONDict | None = None):
        super().__init__(type=constants.MenuButtonType.DEFAULT, api_kwargs=api_kwargs)
        self._freeze()
