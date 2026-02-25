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
"""This module contains the class Defaults, which allows passing default values to Application."""

import datetime as dtm
from typing import TYPE_CHECKING, Any, NoReturn, final

from telegram._utils.datetime import UTC
from telegram._utils.warnings import warn
from telegram.warnings import PTBDeprecationWarning

if TYPE_CHECKING:
    from telegram import LinkPreviewOptions


@final
class Defaults:
    """Convenience Class to gather all parameters with a (user defined) default value

    .. seealso:: :wiki:`Architecture Overview <Architecture>`,
        :wiki:`Adding Defaults to Your Bot <Adding-defaults-to-your-bot>`

    .. versionchanged:: 20.0
        Removed the argument and attribute ``timeout``. Specify default timeout behavior for the
        networking backend directly via :class:`telegram.ext.ApplicationBuilder` instead.

    .. versionchanged:: 22.0
        Removed deprecated arguments and properties ``disable_web_page_preview`` and ``quote``.
        Use :paramref:`link_preview_options` and :paramref:`do_quote` instead.

    Parameters:
        parse_mode (:obj:`str`, optional): |parse_mode|
        disable_notification (:obj:`bool`, optional): |disable_notification|
        allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|.
            Will be used for :attr:`telegram.ReplyParameters.allow_sending_without_reply`.
        tzinfo (:class:`datetime.tzinfo`, optional): A timezone to be used for all date(time)
            inputs appearing throughout PTB, i.e. if a timezone naive date(time) object is passed
            somewhere, it will be assumed to be in :paramref:`tzinfo`. Defaults to
            :attr:`datetime.timezone.utc` otherwise.

            .. deprecated:: 21.10
                Support for ``pytz`` timezones is deprecated and will be removed in future
                versions.

        block (:obj:`bool`, optional): Default setting for the :paramref:`BaseHandler.block`
            parameter
            of handlers and error handlers registered through :meth:`Application.add_handler` and
            :meth:`Application.add_error_handler`. Defaults to :obj:`True`.
        protect_content (:obj:`bool`, optional): |protect_content|

            .. versionadded:: 20.0
        link_preview_options (:class:`telegram.LinkPreviewOptions`, optional):
            Link preview generation options for all outgoing messages. Mutually exclusive with
            :paramref:`disable_web_page_preview`.
            This object is used for the corresponding parameter of
            :meth:`telegram.Bot.send_message`, :meth:`telegram.Bot.edit_message_text`,
            and :class:`telegram.InputTextMessageContent` if not specified. If a value is specified
            for the corresponding parameter, only those parameters of
            :class:`telegram.LinkPreviewOptions` will be overridden that are not
            explicitly set.

            Example:

                .. code-block:: python

                    from telegram import LinkPreviewOptions
                    from telegram.ext import Defaults, ExtBot

                    defaults = Defaults(
                        link_preview_options=LinkPreviewOptions(show_above_text=True)
                    )
                    chat_id = 123

                    async def main():
                        async with ExtBot("Token", defaults=defaults) as bot:
                            # The link preview will be shown above the text.
                            await bot.send_message(chat_id, "https://python-telegram-bot.org")

                            # The link preview will be shown below the text.
                            await bot.send_message(
                                chat_id,
                                "https://python-telegram-bot.org",
                                link_preview_options=LinkPreviewOptions(show_above_text=False)
                            )

                            # The link preview will be shown above the text, but the preview will
                            # show Telegram.
                            await bot.send_message(
                                chat_id,
                                "https://python-telegram-bot.org",
                                link_preview_options=LinkPreviewOptions(url="https://telegram.org")
                            )

            .. versionadded:: 20.8
        do_quote(:obj:`bool`, optional): |reply_quote|

            .. versionadded:: 20.8
    """

    __slots__ = (
        "_allow_sending_without_reply",
        "_api_defaults",
        "_block",
        "_disable_notification",
        "_do_quote",
        "_link_preview_options",
        "_parse_mode",
        "_protect_content",
        "_tzinfo",
    )

    def __init__(
        self,
        parse_mode: str | None = None,
        disable_notification: bool | None = None,
        tzinfo: dtm.tzinfo = UTC,
        block: bool = True,
        allow_sending_without_reply: bool | None = None,
        protect_content: bool | None = None,
        link_preview_options: "LinkPreviewOptions | None" = None,
        do_quote: bool | None = None,
    ):
        self._parse_mode: str | None = parse_mode
        self._disable_notification: bool | None = disable_notification
        self._allow_sending_without_reply: bool | None = allow_sending_without_reply
        self._tzinfo: dtm.tzinfo = tzinfo
        self._block: bool = block
        self._protect_content: bool | None = protect_content

        if "pytz" in str(self._tzinfo.__class__):
            # TODO: When dropping support, make sure to update _utils.datetime accordingly
            warn(
                message=PTBDeprecationWarning(
                    version="21.10",
                    message=(
                        "Support for pytz timezones is deprecated and will be removed in "
                        "future versions."
                    ),
                ),
                stacklevel=2,
            )

        self._link_preview_options = link_preview_options
        self._do_quote = do_quote

        # Gather all defaults that actually have a default value
        self._api_defaults = {}
        for kwarg in (
            "allow_sending_without_reply",
            "disable_notification",
            "do_quote",
            "explanation_parse_mode",
            "link_preview_options",
            "parse_mode",
            "text_parse_mode",
            "protect_content",
            "question_parse_mode",
        ):
            value = getattr(self, kwarg)
            if value is not None:
                self._api_defaults[kwarg] = value

    def __hash__(self) -> int:
        """Builds a hash value for this object such that the hash of two objects is equal if and
        only if the objects are equal in terms of :meth:`__eq__`.

        Returns:
            :obj:`int` The hash value of the object.
        """
        return hash(
            (
                self._parse_mode,
                self._disable_notification,
                self._link_preview_options,
                self._allow_sending_without_reply,
                self._do_quote,
                self._tzinfo,
                self._block,
                self._protect_content,
            )
        )

    def __eq__(self, other: object) -> bool:
        """Defines equality condition for the :class:`Defaults` object.
        Two objects of this class are considered to be equal if all their parameters
        are identical.

        Returns:
            :obj:`True` if both objects have all parameters identical. :obj:`False` otherwise.
        """
        if isinstance(other, Defaults):
            return all(getattr(self, attr) == getattr(other, attr) for attr in self.__slots__)
        return False

    @property
    def api_defaults(self) -> dict[str, Any]:  # skip-cq: PY-D0003
        return self._api_defaults

    @property
    def parse_mode(self) -> str | None:
        """:obj:`str`: Optional. Send Markdown or HTML, if you want Telegram apps to show
        bold, italic, fixed-width text or URLs in your bot's message.
        """
        return self._parse_mode

    @parse_mode.setter
    def parse_mode(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to parse_mode after initialization.")

    @property
    def explanation_parse_mode(self) -> str | None:
        """:obj:`str`: Optional. Alias for :attr:`parse_mode`, used for
        the corresponding parameter of :meth:`telegram.Bot.send_poll`.
        """
        return self._parse_mode

    @explanation_parse_mode.setter
    def explanation_parse_mode(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to explanation_parse_mode after initialization."
        )

    @property
    def quote_parse_mode(self) -> str | None:
        """:obj:`str`: Optional. Alias for :attr:`parse_mode`, used for
        the corresponding parameter of :meth:`telegram.ReplyParameters`.
        """
        return self._parse_mode

    @quote_parse_mode.setter
    def quote_parse_mode(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to quote_parse_mode after initialization."
        )

    @property
    def text_parse_mode(self) -> str | None:
        """:obj:`str`: Optional. Alias for :attr:`parse_mode`, used for
        the corresponding parameter of :class:`telegram.InputPollOption` and
        :meth:`telegram.Bot.send_gift`.

        .. versionadded:: 21.2
        """
        return self._parse_mode

    @text_parse_mode.setter
    def text_parse_mode(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to text_parse_mode after initialization."
        )

    @property
    def question_parse_mode(self) -> str | None:
        """:obj:`str`: Optional. Alias for :attr:`parse_mode`, used for
        the corresponding parameter of :meth:`telegram.Bot.send_poll`.

        .. versionadded:: 21.2
        """
        return self._parse_mode

    @question_parse_mode.setter
    def question_parse_mode(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to question_parse_mode after initialization."
        )

    @property
    def disable_notification(self) -> bool | None:
        """:obj:`bool`: Optional. Sends the message silently. Users will
        receive a notification with no sound.
        """
        return self._disable_notification

    @disable_notification.setter
    def disable_notification(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to disable_notification after initialization."
        )

    @property
    def allow_sending_without_reply(self) -> bool | None:
        """:obj:`bool`: Optional. Pass :obj:`True`, if the message
        should be sent even if the specified replied-to message is not found.
        """
        return self._allow_sending_without_reply

    @allow_sending_without_reply.setter
    def allow_sending_without_reply(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to allow_sending_without_reply after initialization."
        )

    @property
    def tzinfo(self) -> dtm.tzinfo:
        """:obj:`tzinfo`: A timezone to be used for all date(time) objects appearing
        throughout PTB.
        """
        return self._tzinfo

    @tzinfo.setter
    def tzinfo(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to tzinfo after initialization.")

    @property
    def block(self) -> bool:
        """:obj:`bool`: Optional. Default setting for the :paramref:`BaseHandler.block` parameter
        of handlers and error handlers registered through :meth:`Application.add_handler` and
        :meth:`Application.add_error_handler`.
        """
        return self._block

    @block.setter
    def block(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to block after initialization.")

    @property
    def protect_content(self) -> bool | None:
        """:obj:`bool`: Optional. Protects the contents of the sent message from forwarding and
        saving.

        .. versionadded:: 20.0
        """
        return self._protect_content

    @protect_content.setter
    def protect_content(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can't assign a new value to protect_content after initialization."
        )

    @property
    def link_preview_options(self) -> "LinkPreviewOptions | None":
        """:class:`telegram.LinkPreviewOptions`: Optional. Link preview generation options for all
        outgoing messages.

        .. versionadded:: 20.8
        """
        return self._link_preview_options

    @property
    def do_quote(self) -> bool | None:
        """:obj:`bool`: Optional. |reply_quote|

        .. versionadded:: 20.8
        """
        return self._do_quote
