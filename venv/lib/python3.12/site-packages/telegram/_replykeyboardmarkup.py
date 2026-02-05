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
"""This module contains an object that represents a Telegram ReplyKeyboardMarkup."""

from collections.abc import Sequence
from typing import Final

from telegram import constants
from telegram._keyboardbutton import KeyboardButton
from telegram._telegramobject import TelegramObject
from telegram._utils.markup import check_keyboard_type
from telegram._utils.types import JSONDict


class ReplyKeyboardMarkup(TelegramObject):
    """This object represents a custom keyboard with reply options. Not supported in channels and
    for messages sent on behalf of a Telegram Business account.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their size of :attr:`keyboard` and all the buttons are equal.

    .. figure:: https://core.telegram.org/file/464001950/1191a/2RwpmgU-swU.123554/b5\
        0478c124d5914c23
        :align: center

        A reply keyboard with reply options.

    .. seealso::
        Another kind of keyboard would be the :class:`telegram.InlineKeyboardMarkup`.

    Examples:
        * Example usage: A user requests to change the bot's language, bot replies to the request
          with a keyboard to select the new language. Other users in the group don't see
          the keyboard.
        * :any:`Conversation Bot <examples.conversationbot>`
        * :any:`Conversation Bot 2 <examples.conversationbot2>`

    Args:
        keyboard (Sequence[Sequence[:obj:`str` | :class:`telegram.KeyboardButton`]]): Array of
            button rows, each represented by an Array of :class:`telegram.KeyboardButton` objects.
        resize_keyboard (:obj:`bool`, optional): Requests clients to resize the keyboard vertically
            for optimal fit (e.g., make the keyboard smaller if there are just two rows of
            buttons). Defaults to :obj:`False`, in which case the custom keyboard is always of the
            same height as the app's standard keyboard.
        one_time_keyboard (:obj:`bool`, optional): Requests clients to hide the keyboard as soon as
            it's been used. The keyboard will still be available, but clients will automatically
            display the usual letter-keyboard in the chat - the user can press a special button in
            the input field to see the custom keyboard again. Defaults to :obj:`False`.
        selective (:obj:`bool`, optional): Use this parameter if you want to show the keyboard to
            specific users only. Targets:

            1) Users that are @mentioned in the :attr:`~telegram.Message.text` of the
               :class:`telegram.Message` object.
            2) If the bot's message is a reply to a message in the same chat and forum topic,
                sender of the original message.

            Defaults to :obj:`False`.

        input_field_placeholder (:obj:`str`, optional): The placeholder to be shown in the input
            field when the keyboard is active;
            :tg-const:`telegram.ReplyKeyboardMarkup.MIN_INPUT_FIELD_PLACEHOLDER`-
            :tg-const:`telegram.ReplyKeyboardMarkup.MAX_INPUT_FIELD_PLACEHOLDER`
            characters.

            .. versionadded:: 13.7
        is_persistent (:obj:`bool`, optional): Requests clients to always show the keyboard when
            the regular keyboard is hidden. Defaults to :obj:`False`, in which case the custom
            keyboard can be hidden and opened with a keyboard icon.

            .. versionadded:: 20.0

    Attributes:
        keyboard (tuple[tuple[:class:`telegram.KeyboardButton`]]): Array of button rows,
            each represented by an Array of :class:`telegram.KeyboardButton` objects.
        resize_keyboard (:obj:`bool`): Optional. Requests clients to resize the keyboard vertically
            for optimal fit (e.g., make the keyboard smaller if there are just two rows of
            buttons). Defaults to :obj:`False`, in which case the custom keyboard is always of the
            same height as the app's standard keyboard.
        one_time_keyboard (:obj:`bool`): Optional. Requests clients to hide the keyboard as soon as
            it's been used. The keyboard will still be available, but clients will automatically
            display the usual letter-keyboard in the chat - the user can press a special button in
            the input field to see the custom keyboard again. Defaults to :obj:`False`.
        selective (:obj:`bool`): Optional. Show the keyboard to specific users only.
            Targets:

            1) Users that are @mentioned in the :attr:`~telegram.Message.text` of the
               :class:`telegram.Message` object.
            2) If the bot's message is a reply to a message in the same chat and forum topic,
                sender of the original message.

            Defaults to :obj:`False`.

        input_field_placeholder (:obj:`str`): Optional. The placeholder to be shown in the input
            field when the keyboard is active;
            :tg-const:`telegram.ReplyKeyboardMarkup.MIN_INPUT_FIELD_PLACEHOLDER`-
            :tg-const:`telegram.ReplyKeyboardMarkup.MAX_INPUT_FIELD_PLACEHOLDER`
            characters.

            .. versionadded:: 13.7
        is_persistent (:obj:`bool`): Optional. Requests clients to always show the keyboard when
            the regular keyboard is hidden. If :obj:`False`, the custom keyboard can be hidden and
            opened with a keyboard icon.

            .. versionadded:: 20.0

    """

    __slots__ = (
        "input_field_placeholder",
        "is_persistent",
        "keyboard",
        "one_time_keyboard",
        "resize_keyboard",
        "selective",
    )

    def __init__(
        self,
        keyboard: Sequence[Sequence[str | KeyboardButton]],
        resize_keyboard: bool | None = None,
        one_time_keyboard: bool | None = None,
        selective: bool | None = None,
        input_field_placeholder: str | None = None,
        is_persistent: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        if not check_keyboard_type(keyboard):
            raise ValueError(
                "The parameter `keyboard` should be a sequence of sequences of "
                "strings or KeyboardButtons"
            )

        # Required
        self.keyboard: tuple[tuple[KeyboardButton, ...], ...] = tuple(
            tuple(KeyboardButton(button) if isinstance(button, str) else button for button in row)
            for row in keyboard
        )

        # Optionals
        self.resize_keyboard: bool | None = resize_keyboard
        self.one_time_keyboard: bool | None = one_time_keyboard
        self.selective: bool | None = selective
        self.input_field_placeholder: str | None = input_field_placeholder
        self.is_persistent: bool | None = is_persistent

        self._id_attrs = (self.keyboard,)

        self._freeze()

    @classmethod
    def from_button(
        cls,
        button: KeyboardButton | str,
        resize_keyboard: bool = False,
        one_time_keyboard: bool = False,
        selective: bool = False,
        input_field_placeholder: str | None = None,
        is_persistent: bool | None = None,
        **kwargs: object,
    ) -> "ReplyKeyboardMarkup":
        """Shortcut for::

            ReplyKeyboardMarkup([[button]], **kwargs)

        Return a ReplyKeyboardMarkup from a single KeyboardButton.

        Args:
            button (:class:`telegram.KeyboardButton` | :obj:`str`): The button to use in
                the markup.
            resize_keyboard (:obj:`bool`, optional): Requests clients to resize the keyboard
                vertically for optimal fit (e.g., make the keyboard smaller if there are just two
                rows of buttons). Defaults to :obj:`False`, in which case the custom keyboard is
                always of the same height as the app's standard keyboard.
            one_time_keyboard (:obj:`bool`, optional): Requests clients to hide the keyboard as
                soon as it's been used. The keyboard will still be available, but clients will
                automatically display the usual letter-keyboard in the chat - the user can press
                a special button in the input field to see the custom keyboard again.
                Defaults to :obj:`False`.
            selective (:obj:`bool`, optional): Use this parameter if you want to show the keyboard
                to specific users only. Targets:

                1) Users that are @mentioned in the text of the Message object.
                2) If the bot's message is a reply to a message in the same chat and forum topic,
                    sender of the original message.

                Defaults to :obj:`False`.

            input_field_placeholder (:obj:`str`): Optional. The placeholder shown in the input
                field when the reply is active.

                .. versionadded:: 13.7
            is_persistent (:obj:`bool`): Optional. Requests clients to always show the keyboard
                when the regular keyboard is hidden. Defaults to :obj:`False`, in which case the
                custom keyboard can be hidden and opened with a keyboard icon.

                .. versionadded:: 20.0
        """
        return cls(
            [[button]],
            resize_keyboard=resize_keyboard,
            one_time_keyboard=one_time_keyboard,
            selective=selective,
            input_field_placeholder=input_field_placeholder,
            is_persistent=is_persistent,
            **kwargs,  # type: ignore[arg-type]
        )

    @classmethod
    def from_row(
        cls,
        button_row: Sequence[str | KeyboardButton],
        resize_keyboard: bool = False,
        one_time_keyboard: bool = False,
        selective: bool = False,
        input_field_placeholder: str | None = None,
        is_persistent: bool | None = None,
        **kwargs: object,
    ) -> "ReplyKeyboardMarkup":
        """Shortcut for::

            ReplyKeyboardMarkup([button_row], **kwargs)

        Return a ReplyKeyboardMarkup from a single row of KeyboardButtons.

        Args:
            button_row (Sequence[:class:`telegram.KeyboardButton` | :obj:`str`]): The button to
                use in the markup.

                .. versionchanged:: 20.0
                    |sequenceargs|
            resize_keyboard (:obj:`bool`, optional): Requests clients to resize the keyboard
                vertically for optimal fit (e.g., make the keyboard smaller if there are just two
                rows of buttons). Defaults to :obj:`False`, in which case the custom keyboard is
                always of the same height as the app's standard keyboard.
            one_time_keyboard (:obj:`bool`, optional): Requests clients to hide the keyboard as
                soon as it's been used. The keyboard will still be available, but clients will
                automatically display the usual letter-keyboard in the chat - the user can press
                a special button in the input field to see the custom keyboard again.
                Defaults to :obj:`False`.
            selective (:obj:`bool`, optional): Use this parameter if you want to show the keyboard
                to specific users only. Targets:

                1) Users that are @mentioned in the text of the Message object.
                2) If the bot's message is a reply to a message in the same chat and forum topic,
                    sender of the original message.

                Defaults to :obj:`False`.

            input_field_placeholder (:obj:`str`): Optional. The placeholder shown in the input
                field when the reply is active.

                .. versionadded:: 13.7
            is_persistent (:obj:`bool`): Optional. Requests clients to always show the keyboard
                when the regular keyboard is hidden. Defaults to :obj:`False`, in which case the
                custom keyboard can be hidden and opened with a keyboard icon.

                .. versionadded:: 20.0

        """
        return cls(
            [button_row],
            resize_keyboard=resize_keyboard,
            one_time_keyboard=one_time_keyboard,
            selective=selective,
            input_field_placeholder=input_field_placeholder,
            is_persistent=is_persistent,
            **kwargs,  # type: ignore[arg-type]
        )

    @classmethod
    def from_column(
        cls,
        button_column: Sequence[str | KeyboardButton],
        resize_keyboard: bool = False,
        one_time_keyboard: bool = False,
        selective: bool = False,
        input_field_placeholder: str | None = None,
        is_persistent: bool | None = None,
        **kwargs: object,
    ) -> "ReplyKeyboardMarkup":
        """Shortcut for::

            ReplyKeyboardMarkup([[button] for button in button_column], **kwargs)

        Return a ReplyKeyboardMarkup from a single column of KeyboardButtons.

        Args:
            button_column (Sequence[:class:`telegram.KeyboardButton` | :obj:`str`]): The button
                to use in the markup.

                .. versionchanged:: 20.0
                    |sequenceargs|
            resize_keyboard (:obj:`bool`, optional): Requests clients to resize the keyboard
                vertically for optimal fit (e.g., make the keyboard smaller if there are just two
                rows of buttons). Defaults to :obj:`False`, in which case the custom keyboard is
                always of the same height as the app's standard keyboard.
            one_time_keyboard (:obj:`bool`, optional): Requests clients to hide the keyboard as
                soon as it's been used. The keyboard will still be available, but clients will
                automatically display the usual letter-keyboard in the chat - the user can press
                a special button in the input field to see the custom keyboard again.
                Defaults to :obj:`False`.
            selective (:obj:`bool`, optional): Use this parameter if you want to show the keyboard
                to specific users only. Targets:

                1) Users that are @mentioned in the text of the Message object.
                2) If the bot's message is a reply to a message in the same chat and forum topic,
                    sender of the original message.

                Defaults to :obj:`False`.

            input_field_placeholder (:obj:`str`): Optional. The placeholder shown in the input
                field when the reply is active.

                .. versionadded:: 13.7
            is_persistent (:obj:`bool`): Optional. Requests clients to always show the keyboard
                when the regular keyboard is hidden. Defaults to :obj:`False`, in which case the
                custom keyboard can be hidden and opened with a keyboard icon.

                .. versionadded:: 20.0

        """
        button_grid = [[button] for button in button_column]
        return cls(
            button_grid,
            resize_keyboard=resize_keyboard,
            one_time_keyboard=one_time_keyboard,
            selective=selective,
            input_field_placeholder=input_field_placeholder,
            is_persistent=is_persistent,
            **kwargs,  # type: ignore[arg-type]
        )

    MIN_INPUT_FIELD_PLACEHOLDER: Final[int] = constants.ReplyLimit.MIN_INPUT_FIELD_PLACEHOLDER
    """:const:`telegram.constants.ReplyLimit.MIN_INPUT_FIELD_PLACEHOLDER`

    .. versionadded:: 20.0
    """
    MAX_INPUT_FIELD_PLACEHOLDER: Final[int] = constants.ReplyLimit.MAX_INPUT_FIELD_PLACEHOLDER
    """:const:`telegram.constants.ReplyLimit.MAX_INPUT_FIELD_PLACEHOLDER`

    .. versionadded:: 20.0
    """
