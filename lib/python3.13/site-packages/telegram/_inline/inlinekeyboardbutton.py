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
"""This module contains an object that represents a Telegram InlineKeyboardButton."""

from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._copytextbutton import CopyTextButton
from telegram._games.callbackgame import CallbackGame
from telegram._loginurl import LoginUrl
from telegram._switchinlinequerychosenchat import SwitchInlineQueryChosenChat
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict
from telegram._webappinfo import WebAppInfo

if TYPE_CHECKING:
    from telegram import Bot


class InlineKeyboardButton(TelegramObject):
    """This object represents one button of an inline keyboard.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`text`, :attr:`url`, :attr:`login_url`, :attr:`callback_data`,
    :attr:`switch_inline_query`, :attr:`switch_inline_query_current_chat`, :attr:`callback_game`,
    :attr:`web_app` and :attr:`pay` are equal.

    Note:
        * Exactly one of the optional fields must be used to specify type of the button.
        * Mind that :attr:`callback_game` is not
          working as expected. Putting a game short name in it might, but is not guaranteed to
          work.
        * If your bot allows for arbitrary callback data, in keyboards returned in a response
          from telegram, :attr:`callback_data` may be an instance of
          :class:`telegram.ext.InvalidCallbackData`. This will be the case, if the data
          associated with the button was already deleted.

          .. versionadded:: 13.6

        * Since Bot API 5.5, it's now allowed to mention users by their ID in inline keyboards.
          This will only work in Telegram versions released after December 7, 2021.
          Older clients will display *unsupported message*.

    Warning:
        * If your bot allows your arbitrary callback data, buttons whose callback data is a
          non-hashable object will become unhashable. Trying to evaluate ``hash(button)`` will
          result in a :class:`TypeError`.

          .. versionchanged:: 13.6

        * After Bot API 6.1, only ``HTTPS`` links will be allowed in :paramref:`login_url`.

    Examples:
        * :any:`Inline Keyboard 1 <examples.inlinekeyboard>`
        * :any:`Inline Keyboard 2 <examples.inlinekeyboard2>`

    .. seealso:: :class:`telegram.InlineKeyboardMarkup`

    .. versionchanged:: 20.0
       :attr:`web_app` is considered as well when comparing objects of this type in terms of
       equality.

    Args:
        text (:obj:`str`): Label text on the button.
        url (:obj:`str`, optional): HTTP or tg:// url to be opened when the button is pressed.
            Links ``tg://user?id=<user_id>`` can be used to mention a user by
            their ID without using a username, if this is allowed by their privacy settings.

            .. versionchanged:: 13.9
               You can now mention a user using ``tg://user?id=<user_id>``.
        login_url (:class:`telegram.LoginUrl`, optional): An ``HTTPS`` URL used to automatically
            authorize the user. Can be used as a replacement for the Telegram Login Widget.

            Caution:
                Only ``HTTPS`` links are allowed after Bot API 6.1.
        callback_data (:obj:`str` | :obj:`object`, optional): Data to be sent in a callback query
            to the bot when the button is pressed, UTF-8
            :tg-const:`telegram.InlineKeyboardButton.MIN_CALLBACK_DATA`-
            :tg-const:`telegram.InlineKeyboardButton.MAX_CALLBACK_DATA` bytes.
            If the bot instance allows arbitrary callback data, anything can be passed.

            Tip:
                The value entered here will be available in :attr:`telegram.CallbackQuery.data`.

            .. seealso:: :wiki:`Arbitrary callback_data <Arbitrary-callback_data>`

        web_app (:class:`telegram.WebAppInfo`, optional): Description of the `Web App
            <https://core.telegram.org/bots/webapps>`_  that will be launched when the user presses
            the button. The Web App will be able to send an arbitrary message on behalf of the user
            using the method :meth:`~telegram.Bot.answer_web_app_query`. Available only in
            private chats between a user and the bot. Not supported for messages sent on behalf of
            a Telegram Business account.

            .. versionadded:: 20.0
        switch_inline_query (:obj:`str`, optional): If set, pressing the button will prompt the
            user to select one of their chats, open that chat and insert the bot's username and the
            specified inline query in the input field. May be empty, in which case just the bot's
            username will be inserted. Not supported for messages sent on behalf of a Telegram
            Business account.

            Tip:
                This is similar to the parameter :paramref:`switch_inline_query_chosen_chat`,
                but gives no control over which chats can be selected.
        switch_inline_query_current_chat (:obj:`str`, optional): If set, pressing the button will
            insert the bot's username and the specified inline query in the current chat's input
            field. May be empty, in which case only the bot's username will be inserted.

            This offers a quick way for the user to open your bot in inline mode in the same chat
            - good for selecting something from multiple options. Not supported in channels and for
            messages sent on behalf of a Telegram Business account.
        copy_text (:class:`telegram.CopyTextButton`, optional): Description of the button that
            copies the specified text to the clipboard.

            .. versionadded:: 21.7
        callback_game (:class:`telegram.CallbackGame`, optional): Description of the game that will
            be launched when the user presses the button

            Note:
                This type of button **must** always be the first button in the first row.
        pay (:obj:`bool`, optional): Specify :obj:`True`, to send a Pay button.
            Substrings ``“⭐️”`` and ``“XTR”`` in the buttons's text will be replaced with a
            Telegram Star icon.

            Note:
                This type of button **must** always be the first button in the first row and can
                only be used in invoice messages.
        switch_inline_query_chosen_chat (:class:`telegram.SwitchInlineQueryChosenChat`, optional):
            If set, pressing the button will prompt the user to select one of their chats of the
            specified type, open that chat and insert the bot's username and the specified inline
            query in the input field. Not supported for messages sent on behalf of a Telegram
            Business account.

            .. versionadded:: 20.3

            Tip:
                This is similar to :paramref:`switch_inline_query`, but gives more control on
                which chats can be selected.

            Caution:
                The PTB team has discovered that this field works correctly only if your Telegram
                client is released after April 20th 2023.

    Attributes:
        text (:obj:`str`): Label text on the button.
        url (:obj:`str`): Optional. HTTP or tg:// url to be opened when the button is pressed.
            Links ``tg://user?id=<user_id>`` can be used to mention a user by
            their ID without using a username, if this is allowed by their privacy settings.

            .. versionchanged:: 13.9
               You can now mention a user using ``tg://user?id=<user_id>``.
        login_url (:class:`telegram.LoginUrl`): Optional. An ``HTTPS`` URL used to automatically
            authorize the user. Can be used as a replacement for the Telegram Login Widget.

            Caution:
                Only ``HTTPS`` links are allowed after Bot API 6.1.
        callback_data (:obj:`str` | :obj:`object`): Optional. Data to be sent in a callback query
            to the bot when the button is pressed, UTF-8
            :tg-const:`telegram.InlineKeyboardButton.MIN_CALLBACK_DATA`-
            :tg-const:`telegram.InlineKeyboardButton.MAX_CALLBACK_DATA` bytes.
        web_app (:class:`telegram.WebAppInfo`): Optional. Description of the `Web App
            <https://core.telegram.org/bots/webapps>`_  that will be launched when the user presses
            the button. The Web App will be able to send an arbitrary message on behalf of the user
            using the method :meth:`~telegram.Bot.answer_web_app_query`. Available only in
            private chats between a user and the bot. Not supported for messages sent on behalf of
            a Telegram Business account.

            .. versionadded:: 20.0
        switch_inline_query (:obj:`str`): Optional. If set, pressing the button will prompt the
            user to select one of their chats, open that chat and insert the bot's username and the
            specified inline query in the input field. May be empty, in which case just the bot's
            username will be inserted. Not supported for messages sent on behalf of a Telegram
            Business account.

            Tip:
                This is similar to the parameter :paramref:`switch_inline_query_chosen_chat`,
                but gives no control over which chats can be selected.
        switch_inline_query_current_chat (:obj:`str`): Optional. If set, pressing the button will
            insert the bot's username and the specified inline query in the current chat's input
            field. May be empty, in which case only the bot's username will be inserted.

            This offers a quick way for the user to open your bot in inline mode in the same chat
            - good for selecting something from multiple options. Not supported in channels and for
            messages sent on behalf of a Telegram Business account.
        copy_text (:class:`telegram.CopyTextButton`): Optional. Description of the button that
            copies the specified text to the clipboard.

            .. versionadded:: 21.7
        callback_game (:class:`telegram.CallbackGame`): Optional. Description of the game that will
            be launched when the user presses the button.

            Note:
                This type of button **must** always be the first button in the first row.
        pay (:obj:`bool`): Optional. Specify :obj:`True`, to send a Pay button.
            Substrings ``“⭐️”`` and ``“XTR”`` in the buttons's text will be replaced with a
            Telegram Star icon.

            Note:
                This type of button **must** always be the first button in the first row and can
                only be used in invoice messages.
        switch_inline_query_chosen_chat (:class:`telegram.SwitchInlineQueryChosenChat`): Optional.
            If set, pressing the button will prompt the user to select one of their chats of the
            specified type, open that chat and insert the bot's username and the specified inline
            query in the input field. Not supported for messages sent on behalf of a Telegram
            Business account.

            .. versionadded:: 20.3

            Tip:
                This is similar to :attr:`switch_inline_query`, but gives more control on
                which chats can be selected.

            Caution:
                The PTB team has discovered that this field works correctly only if your Telegram
                client is released after April 20th 2023.
    """

    __slots__ = (
        "callback_data",
        "callback_game",
        "copy_text",
        "login_url",
        "pay",
        "switch_inline_query",
        "switch_inline_query_chosen_chat",
        "switch_inline_query_current_chat",
        "text",
        "url",
        "web_app",
    )

    def __init__(
        self,
        text: str,
        url: str | None = None,
        callback_data: str | object | None = None,
        switch_inline_query: str | None = None,
        switch_inline_query_current_chat: str | None = None,
        callback_game: CallbackGame | None = None,
        pay: bool | None = None,
        login_url: LoginUrl | None = None,
        web_app: WebAppInfo | None = None,
        switch_inline_query_chosen_chat: SwitchInlineQueryChosenChat | None = None,
        copy_text: CopyTextButton | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.text: str = text

        # Optionals
        self.url: str | None = url
        self.login_url: LoginUrl | None = login_url
        self.callback_data: str | object | None = callback_data
        self.switch_inline_query: str | None = switch_inline_query
        self.switch_inline_query_current_chat: str | None = switch_inline_query_current_chat
        self.callback_game: CallbackGame | None = callback_game
        self.pay: bool | None = pay
        self.web_app: WebAppInfo | None = web_app
        self.switch_inline_query_chosen_chat: SwitchInlineQueryChosenChat | None = (
            switch_inline_query_chosen_chat
        )
        self.copy_text: CopyTextButton | None = copy_text
        self._id_attrs = ()
        self._set_id_attrs()

        self._freeze()

    def _set_id_attrs(self) -> None:
        self._id_attrs = (
            self.text,
            self.url,
            self.login_url,
            self.callback_data,
            self.web_app,
            self.switch_inline_query,
            self.switch_inline_query_current_chat,
            self.callback_game,
            self.pay,
        )

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "InlineKeyboardButton":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["login_url"] = de_json_optional(data.get("login_url"), LoginUrl, bot)
        data["web_app"] = de_json_optional(data.get("web_app"), WebAppInfo, bot)
        data["callback_game"] = de_json_optional(data.get("callback_game"), CallbackGame, bot)
        data["switch_inline_query_chosen_chat"] = de_json_optional(
            data.get("switch_inline_query_chosen_chat"), SwitchInlineQueryChosenChat, bot
        )
        data["copy_text"] = de_json_optional(data.get("copy_text"), CopyTextButton, bot)

        return super().de_json(data=data, bot=bot)

    def update_callback_data(self, callback_data: str | object) -> None:
        """
        Sets :attr:`callback_data` to the passed object. Intended to be used by
        :class:`telegram.ext.CallbackDataCache`.

        .. versionadded:: 13.6

        Args:
            callback_data (:class:`object`): The new callback data.
        """
        with self._unfrozen():
            self.callback_data = callback_data
            self._set_id_attrs()

    MIN_CALLBACK_DATA: Final[int] = constants.InlineKeyboardButtonLimit.MIN_CALLBACK_DATA
    """:const:`telegram.constants.InlineKeyboardButtonLimit.MIN_CALLBACK_DATA`

    .. versionadded:: 20.0
    """
    MAX_CALLBACK_DATA: Final[int] = constants.InlineKeyboardButtonLimit.MAX_CALLBACK_DATA
    """:const:`telegram.constants.InlineKeyboardButtonLimit.MAX_CALLBACK_DATA`

    .. versionadded:: 20.0
    """
