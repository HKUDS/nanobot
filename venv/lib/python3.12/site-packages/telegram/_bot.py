#!/usr/bin/env python
# pylint: disable=too-many-arguments
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
"""This module contains an object that represents a Telegram Bot."""

import asyncio
import contextlib
import copy
import datetime as dtm
import pickle
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    NoReturn,
    TypeVar,
    cast,
    no_type_check,
)

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization

    CRYPTO_INSTALLED = True
except ImportError:
    default_backend = None  # type: ignore[assignment]
    serialization = None  # type: ignore[assignment]
    CRYPTO_INSTALLED = False

from telegram._botcommand import BotCommand
from telegram._botcommandscope import BotCommandScope
from telegram._botdescription import BotDescription, BotShortDescription
from telegram._botname import BotName
from telegram._business import BusinessConnection
from telegram._chatadministratorrights import ChatAdministratorRights
from telegram._chatboost import UserChatBoosts
from telegram._chatfullinfo import ChatFullInfo
from telegram._chatinvitelink import ChatInviteLink
from telegram._chatmember import ChatMember
from telegram._chatpermissions import ChatPermissions
from telegram._files.animation import Animation
from telegram._files.audio import Audio
from telegram._files.chatphoto import ChatPhoto
from telegram._files.contact import Contact
from telegram._files.document import Document
from telegram._files.file import File
from telegram._files.inputmedia import InputMedia, InputPaidMedia
from telegram._files.location import Location
from telegram._files.photosize import PhotoSize
from telegram._files.sticker import MaskPosition, Sticker, StickerSet
from telegram._files.venue import Venue
from telegram._files.video import Video
from telegram._files.videonote import VideoNote
from telegram._files.voice import Voice
from telegram._forumtopic import ForumTopic
from telegram._games.gamehighscore import GameHighScore
from telegram._gifts import AcceptedGiftTypes, Gift, Gifts
from telegram._inline.inlinequeryresultsbutton import InlineQueryResultsButton
from telegram._inline.preparedinlinemessage import PreparedInlineMessage
from telegram._inputchecklist import InputChecklist
from telegram._menubutton import MenuButton
from telegram._message import Message
from telegram._messageid import MessageId
from telegram._ownedgift import OwnedGifts
from telegram._payment.stars.staramount import StarAmount
from telegram._payment.stars.startransactions import StarTransactions
from telegram._poll import InputPollOption, Poll
from telegram._reaction import ReactionType, ReactionTypeCustomEmoji, ReactionTypeEmoji
from telegram._reply import ReplyParameters
from telegram._sentwebappmessage import SentWebAppMessage
from telegram._story import Story
from telegram._telegramobject import TelegramObject
from telegram._update import Update
from telegram._user import User
from telegram._userprofilephotos import UserProfilePhotos
from telegram._utils.argumentparsing import parse_lpo_and_dwpp, parse_sequence_arg
from telegram._utils.defaultvalue import DEFAULT_NONE, DefaultValue
from telegram._utils.files import is_local_file, parse_file_input
from telegram._utils.logging import get_logger
from telegram._utils.repr import build_repr_with_selected_attrs
from telegram._utils.strings import to_camel_case
from telegram._utils.types import (
    BaseUrl,
    CorrectOptionID,
    FileInput,
    JSONDict,
    ODVInput,
    TimePeriod,
)
from telegram._utils.warnings import warn
from telegram._utils.warnings_transition import build_deprecation_warning_message
from telegram._webhookinfo import WebhookInfo
from telegram.constants import InlineQueryLimit, ReactionEmoji
from telegram.error import EndPointNotFound, InvalidToken
from telegram.request import BaseRequest, RequestData
from telegram.request._httpxrequest import HTTPXRequest
from telegram.request._requestparameter import RequestParameter
from telegram.warnings import PTBDeprecationWarning, PTBUserWarning

if TYPE_CHECKING:
    from telegram import (
        InlineKeyboardMarkup,
        InlineQueryResult,
        InputFile,
        InputMediaAudio,
        InputMediaDocument,
        InputMediaPhoto,
        InputMediaVideo,
        InputProfilePhoto,
        InputSticker,
        InputStoryContent,
        LabeledPrice,
        LinkPreviewOptions,
        MessageEntity,
        PassportElementError,
        ShippingOption,
        StoryArea,
        SuggestedPostParameters,
    )
    from telegram._utils.types import ReplyMarkup

BT = TypeVar("BT", bound="Bot")


# Even though we document only {token} as supported insertion, we are a bit more flexible
# internally and support additional variants. At the very least, we don't want the insertion
# to be case sensitive.
_SUPPORTED_INSERTIONS = {"token", "TOKEN", "bot_token", "BOT_TOKEN", "bot-token", "BOT-TOKEN"}
_INSERTION_STRINGS = {f"{{{insertion}}}" for insertion in _SUPPORTED_INSERTIONS}


class _TokenDict(dict):
    __slots__ = ("token",)

    # small helper to make .format_map work without knowing which exact insertion name is used
    def __init__(self, token: str):
        self.token = token
        super().__init__()

    def __missing__(self, key: str) -> str:
        if key in _SUPPORTED_INSERTIONS:
            return self.token
        raise KeyError(f"Base URL string contains unsupported insertion: {key}")


def _parse_base_url(value: BaseUrl, token: str) -> str:
    if callable(value):
        return value(token)
    if any(insertion in value for insertion in _INSERTION_STRINGS):
        return value.format_map(_TokenDict(token))
    return value + token


class Bot(TelegramObject, contextlib.AbstractAsyncContextManager["Bot"]):
    """This object represents a Telegram Bot.

    Instances of this class can be used as asyncio context managers, where

    .. code:: python

        async with bot:
            # code

    is roughly equivalent to

    .. code:: python

        try:
            await bot.initialize()
            # code
        finally:
            await bot.shutdown()

    .. seealso:: :meth:`__aenter__` and :meth:`__aexit__`.

    Note:
        * Most bot methods have the argument ``api_kwargs`` which allows passing arbitrary keywords
          to the Telegram API. This can be used to access new features of the API before they are
          incorporated into PTB. The limitations to this argument are the same as the ones
          described in :meth:`do_api_request`.
        * Bots should not be serialized since if you for e.g. change the bots token, then your
          serialized instance will not reflect that change. Trying to pickle a bot instance will
          raise :exc:`pickle.PicklingError`. Trying to deepcopy a bot instance will raise
          :exc:`TypeError`.

    Examples:
        :any:`Raw API Bot <examples.rawapibot>`

    .. seealso:: :wiki:`Your First Bot <Extensions---Your-first-Bot>`,
        :wiki:`Builder Pattern <Builder-Pattern>`

    .. versionadded:: 13.2
        Objects of this class are comparable in terms of equality. Two objects of this class are
        considered equal, if their :attr:`bot` is equal.

    .. versionchanged:: 20.0

        * Removed the deprecated methods ``kick_chat_member``, ``kickChatMember``,
          ``get_chat_members_count`` and ``getChatMembersCount``.
        * Removed the deprecated property ``commands``.
        * Removed the deprecated ``defaults`` parameter. If you want to use
          :class:`telegram.ext.Defaults`, please use the subclass :class:`telegram.ext.ExtBot`
          instead.
        * Attempting to pickle a bot instance will now raise :exc:`pickle.PicklingError`.
        * Attempting to deepcopy a bot instance will now raise :exc:`TypeError`.
        * The following are now keyword-only arguments in Bot methods:
          ``location``, ``filename``, ``venue``, ``contact``,
          ``{read, write, connect, pool}_timeout``, ``api_kwargs``. Use a named argument for those,
          and notice that some positional arguments changed position as a result.
        * For uploading files, file paths are now always accepted. If :paramref:`local_mode` is
          :obj:`False`, the file contents will be read in binary mode and uploaded. Otherwise,
          the file path will be passed in the
          `file URI scheme <https://en.wikipedia.org/wiki/File_URI_scheme>`_.

    .. versionchanged:: 20.5
        Removed deprecated methods ``set_sticker_set_thumb`` and ``setStickerSetThumb``.
        Use :meth:`set_sticker_set_thumbnail` and :meth:`setStickerSetThumbnail` instead.

    Args:
        token (:obj:`str`): Bot's unique authentication token.
        base_url (:obj:`str` | Callable[[:obj:`str`], :obj:`str`], optional): Telegram Bot API
            service URL. If the string contains ``{token}``, it will be replaced with the bot's
            token. If a callable is passed, it will be called with the bot's token as the only
            argument and must return the base URL. Otherwise, the token will be appended to the
            string. Defaults to ``"https://api.telegram.org/bot"``.

            Tip:
                Customizing the base URL can be used to run a bot against
                :wiki:`Local Bot API Server <Local-Bot-API-Server>` or using Telegrams
                `test environment \
                <https://core.telegram.org/bots/features#dedicated-test-environment>`_.

                Example:
                    ``"https://api.telegram.org/bot{token}/test"``

            .. versionchanged:: 21.11
               Supports callable input and string formatting.
        base_file_url (:obj:`str`, optional): Telegram Bot API file URL.
            If the string contains ``{token}``, it will be replaced with the bot's
            token. If a callable is passed, it will be called with the bot's token as the only
            argument and must return the base URL. Otherwise, the token will be appended to the
            string. Defaults to ``"https://api.telegram.org/bot"``.

            Tip:
                Customizing the base URL can be used to run a bot against
                :wiki:`Local Bot API Server <Local-Bot-API-Server>` or using Telegrams
                `test environment \
                <https://core.telegram.org/bots/features#dedicated-test-environment>`_.

                Example:
                    ``"https://api.telegram.org/file/bot{token}/test"``

            .. versionchanged:: 21.11
               Supports callable input and string formatting.
        request (:class:`telegram.request.BaseRequest`, optional): Pre initialized
            :class:`telegram.request.BaseRequest` instances. Will be used for all bot methods
            *except* for :meth:`get_updates`. If not passed, an instance of
            :class:`telegram.request.HTTPXRequest` will be used.
        get_updates_request (:class:`telegram.request.BaseRequest`, optional): Pre initialized
            :class:`telegram.request.BaseRequest` instances. Will be used exclusively for
            :meth:`get_updates`. If not passed, an instance of
            :class:`telegram.request.HTTPXRequest` will be used.
        private_key (:obj:`bytes`, optional): Private key for decryption of telegram passport data.
        private_key_password (:obj:`bytes`, optional): Password for above private key.
        local_mode (:obj:`bool`, optional): Set to :obj:`True`, if the :paramref:`base_url` is
            the URI of a `Local Bot API Server <https://core.telegram.org/bots/api#using-a-local\
            -bot-api-server>`_ that runs with the ``--local`` flag. Currently, the only effect of
            this is that files are uploaded using their local path in the
            `file URI scheme <https://en.wikipedia.org/wiki/File_URI_scheme>`_.
            Defaults to :obj:`False`.

            .. versionadded:: 20.0.

    .. include:: inclusions/bot_methods.rst

    .. |removed_thumb_arg| replace:: Removed deprecated argument ``thumb``. Use
        ``thumbnail`` instead.

    """

    # This is a class variable since we want to override the logger name in ExtBot
    # without having to change all places where this is used
    _LOGGER = get_logger(__name__)

    __slots__ = (
        "_base_file_url",
        "_base_url",
        "_bot_initialized",
        "_bot_user",
        "_local_mode",
        "_private_key",
        "_request",
        "_requests_initialized",
        "_token",
    )

    def __init__(
        self,
        token: str,
        base_url: BaseUrl = "https://api.telegram.org/bot",
        base_file_url: BaseUrl = "https://api.telegram.org/file/bot",
        request: BaseRequest | None = None,
        get_updates_request: BaseRequest | None = None,
        private_key: bytes | None = None,
        private_key_password: bytes | None = None,
        local_mode: bool = False,
    ):
        super().__init__(api_kwargs=None)
        if not token:
            raise InvalidToken("You must pass the token you received from https://t.me/Botfather!")
        self._token: str = token

        self._base_url: str = _parse_base_url(base_url, self._token)
        self._base_file_url: str = _parse_base_url(base_file_url, self._token)
        self._LOGGER.debug("Set Bot API URL: %s", self._base_url)
        self._LOGGER.debug("Set Bot API File URL: %s", self._base_file_url)

        self._local_mode: bool = local_mode
        self._bot_user: User | None = None
        self._private_key: bytes | None = None
        self._requests_initialized: bool = False
        self._bot_initialized: bool = False

        self._request: tuple[BaseRequest, BaseRequest] = (
            (
                HTTPXRequest(connection_pool_size=1)
                if get_updates_request is None
                else get_updates_request
            ),
            HTTPXRequest() if request is None else request,
        )

        # this section is about issuing a warning when using HTTP/2 and connect to a self-hosted
        # bot api instance, which currently only supports HTTP/1.1. Checking if a custom base url
        # is set is the best way to do that.

        warning_string = ""

        if (
            isinstance(self._request[0], HTTPXRequest)
            and self._request[0].http_version == "2"
            and not self.base_url.startswith("https://api.telegram.org/bot")
        ):
            warning_string = "get_updates_request"

        if (
            isinstance(self._request[1], HTTPXRequest)
            and self._request[1].http_version == "2"
            and not self.base_url.startswith("https://api.telegram.org/bot")
        ):
            if warning_string:
                warning_string += " and request"
            else:
                warning_string = "request"

        if warning_string:
            self._warn(
                f"You set the HTTP version for the {warning_string} HTTPXRequest instance to "
                "HTTP/2. The self hosted bot api instances only support HTTP/1.1. You should "
                "either run a HTTP proxy in front of it which supports HTTP/2 or use HTTP/1.1.",
                PTBUserWarning,
                stacklevel=2,
            )

        if private_key:
            if not CRYPTO_INSTALLED:
                raise RuntimeError(
                    "To use Telegram Passports, PTB must be installed via `pip install "
                    '"python-telegram-bot[passport]"`.'
                )
            self._private_key = serialization.load_pem_private_key(
                private_key, password=private_key_password, backend=default_backend()
            )

        self._freeze()

    async def __aenter__(self: BT) -> BT:
        """
        |async_context_manager| :meth:`initializes <initialize>` the Bot.

        Returns:
            The initialized Bot instance.

        Raises:
            :exc:`Exception`: If an exception is raised during initialization, :meth:`shutdown`
                is called in this case.
        """
        try:
            await self.initialize()
        except Exception:
            await self.shutdown()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """|async_context_manager| :meth:`shuts down <shutdown>` the Bot."""
        # Make sure not to return `True` so that exceptions are not suppressed
        # https://docs.python.org/3/reference/datamodel.html?#object.__aexit__
        await self.shutdown()

    def __reduce__(self) -> NoReturn:
        """Customizes how :func:`copy.deepcopy` processes objects of this type. Bots can not
        be pickled and this method will always raise an exception.

        .. versionadded:: 20.0

        Raises:
            :exc:`pickle.PicklingError`
        """
        raise pickle.PicklingError("Bot objects cannot be pickled!")

    def __deepcopy__(self, memodict: dict[int, object]) -> NoReturn:
        """Customizes how :func:`copy.deepcopy` processes objects of this type. Bots can not
        be deepcopied and this method will always raise an exception.

        .. versionadded:: 20.0

        Raises:
            :exc:`TypeError`
        """
        raise TypeError("Bot objects cannot be deepcopied!")

    def __eq__(self, other: object) -> bool:
        """Defines equality condition for the :class:`telegram.Bot` object.
        Two objects of this class are considered to be equal if their attributes
        :attr:`bot` are equal.

        Returns:
            :obj:`True` if both attributes :attr:`bot` are equal. :obj:`False` otherwise.
        """
        if isinstance(other, Bot):
            return self.bot == other.bot
        return super().__eq__(other)

    def __hash__(self) -> int:
        """See :meth:`telegram.TelegramObject.__hash__`"""
        if self._bot_user is None:
            return super().__hash__()
        return hash((self.bot, Bot))

    def __repr__(self) -> str:
        """Give a string representation of the bot in the form ``Bot[token=...]``.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        return build_repr_with_selected_attrs(self, token=self.token)

    @property
    def token(self) -> str:
        """:obj:`str`: Bot's unique authentication token.

        .. versionadded:: 20.0
        """
        return self._token

    @property
    def base_url(self) -> str:
        """:obj:`str`: Telegram Bot API service URL, built from :paramref:`Bot.base_url` and
        :paramref:`Bot.token`.

        .. versionadded:: 20.0
        """
        return self._base_url

    @property
    def base_file_url(self) -> str:
        """:obj:`str`: Telegram Bot API file URL, built from :paramref:`Bot.base_file_url` and
        :paramref:`Bot.token`.

        .. versionadded:: 20.0
        """
        return self._base_file_url

    @property
    def local_mode(self) -> bool:
        """:obj:`bool`: Whether this bot is running in local mode.

        .. versionadded:: 20.0
        """
        return self._local_mode

    # Proper type hints are difficult because:
    # 1. cryptography doesn't have a nice base class, so it would get lengthy
    # 2. we can't import cryptography if it's not installed
    @property
    def private_key(self) -> Any | None:
        """Deserialized private key for decryption of telegram passport data.

        .. versionadded:: 20.0
        """
        return self._private_key

    @property
    def request(self) -> BaseRequest:
        """The :class:`~telegram.request.BaseRequest` object used by this bot.

        Warning:
            Requests to the Bot API are made by the various methods of this class. This attribute
            should *not* be used manually.
        """
        return self._request[1]

    @property
    def bot(self) -> User:
        """:class:`telegram.User`: User instance for the bot as returned by :meth:`get_me`.

        Warning:
            This value is the cached return value of :meth:`get_me`. If the bots profile is
            changed during runtime, this value won't reflect the changes until :meth:`get_me` is
            called again.

        .. seealso:: :meth:`initialize`
        """
        if self._bot_user is None:
            raise RuntimeError(
                f"{self.__class__.__name__} is not properly initialized. Call "
                f"`{self.__class__.__name__}.initialize` before accessing this property."
            )
        return self._bot_user

    @property
    def id(self) -> int:
        """:obj:`int`: Unique identifier for this bot. Shortcut for the corresponding attribute of
        :attr:`bot`.
        """
        return self.bot.id

    @property
    def first_name(self) -> str:
        """:obj:`str`: Bot's first name. Shortcut for the corresponding attribute of
        :attr:`bot`.
        """
        return self.bot.first_name

    @property
    def last_name(self) -> str:
        """:obj:`str`: Optional. Bot's last name. Shortcut for the corresponding attribute of
        :attr:`bot`.
        """
        return self.bot.last_name  # type: ignore

    @property
    def username(self) -> str:
        """:obj:`str`: Bot's username. Shortcut for the corresponding attribute of
        :attr:`bot`.
        """
        return self.bot.username  # type: ignore

    @property
    def link(self) -> str:
        """:obj:`str`: Convenience property. Returns the t.me link of the bot."""
        return f"https://t.me/{self.username}"

    @property
    def can_join_groups(self) -> bool:
        """:obj:`bool`: Bot's :attr:`telegram.User.can_join_groups` attribute. Shortcut for the
        corresponding attribute of :attr:`bot`.
        """
        return self.bot.can_join_groups  # type: ignore

    @property
    def can_read_all_group_messages(self) -> bool:
        """:obj:`bool`: Bot's :attr:`telegram.User.can_read_all_group_messages` attribute.
        Shortcut for the corresponding attribute of :attr:`bot`.
        """
        return self.bot.can_read_all_group_messages  # type: ignore

    @property
    def supports_inline_queries(self) -> bool:
        """:obj:`bool`: Bot's :attr:`telegram.User.supports_inline_queries` attribute.
        Shortcut for the corresponding attribute of :attr:`bot`.
        """
        return self.bot.supports_inline_queries  # type: ignore

    @property
    def name(self) -> str:
        """:obj:`str`: Bot's @username. Shortcut for the corresponding attribute of :attr:`bot`."""
        return f"@{self.username}"

    @classmethod
    def _warn(
        cls,
        message: str | PTBUserWarning,
        category: type[Warning] = PTBUserWarning,
        stacklevel: int = 0,
    ) -> None:
        """Convenience method to issue a warning. This method is here mostly to make it easier
        for ExtBot to add 1 level to all warning calls.
        """
        warn(message=message, category=category, stacklevel=stacklevel + 1)

    def _parse_file_input(
        self,
        file_input: "FileInput| TelegramObject",
        tg_type: type["TelegramObject"] | None = None,
        filename: str | None = None,
        attach: bool = False,
    ) -> "str| InputFile| Any":
        return parse_file_input(
            file_input=file_input,
            tg_type=tg_type,
            filename=filename,
            attach=attach,
            local_mode=self._local_mode,
        )

    def _insert_defaults(self, data: dict[str, object]) -> None:
        """This method is here to make ext.Defaults work. Because we need to be able to tell
        e.g. `send_message(chat_id, text)` from `send_message(chat_id, text, parse_mode=None)`, the
        default values for `parse_mode` etc are not `None` but `DEFAULT_NONE`. While this *could*
        be done in ExtBot instead of Bot, shortcuts like `Message.reply_text` need to work for both
        Bot and ExtBot, so they also have the `DEFAULT_NONE` default values.

        This makes it necessary to convert `DefaultValue(obj)` to `obj` at some point between
        `Message.reply_text` and the request to TG. Doing this here in a centralized manner is a
        rather clean and minimally invasive solution, i.e. the link between tg and tg.ext is as
        small as possible.
        See also _insert_defaults_for_ilq
        ExtBot overrides this method to actually insert default values.

        If in the future we come up with a better way of making `Defaults` work, we can cut this
        link as well.
        """
        # We
        # 1) set the correct parse_mode for all InputMedia objects
        # 2) replace all DefaultValue instances with the corresponding normal value.
        for key, val in data.items():
            # 1)
            if isinstance(val, InputMedia):
                # Copy object as not to edit it in-place
                new = copy.copy(val)
                with new._unfrozen():
                    new.parse_mode = DefaultValue.get_value(new.parse_mode)
                data[key] = new
            elif (
                key == "media"
                and isinstance(val, Sequence)
                and not isinstance(val[0], InputPaidMedia)
            ):
                # Copy objects as not to edit them in-place
                copy_list = [copy.copy(media) for media in val]
                for media in copy_list:
                    with media._unfrozen():
                        media.parse_mode = DefaultValue.get_value(media.parse_mode)
                data[key] = copy_list
            # 2)
            else:
                data[key] = DefaultValue.get_value(val)

    async def _post(
        self,
        endpoint: str,
        data: JSONDict | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Any:
        # We know that the return type is Union[bool, JSONDict, list[JSONDict]], but it's hard
        # to tell mypy which methods expects which of these return values and `Any` saves us a
        # lot of `type: ignore` comments
        if data is None:
            data = {}

        if api_kwargs:
            data.update(api_kwargs)

        # Insert is in-place, so no return value for data
        self._insert_defaults(data)

        # Drop any None values because Telegram doesn't handle them well
        data = {key: value for key, value in data.items() if value is not None}

        return await self._do_post(
            endpoint=endpoint,
            data=data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
        )

    async def _do_post(
        self,
        endpoint: str,
        data: JSONDict,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> bool | JSONDict | list[JSONDict]:
        # This also converts datetimes into timestamps.
        # We don't do this earlier so that _insert_defaults (see above) has a chance to convert
        # to the default timezone in case this is called by ExtBot
        request_data = RequestData(
            parameters=[RequestParameter.from_input(key, value) for key, value in data.items()],
        )

        request = self._request[0] if endpoint == "getUpdates" else self._request[1]

        self._LOGGER.debug("Calling Bot API endpoint `%s` with parameters `%s`", endpoint, data)
        result = await request.post(
            url=f"{self._base_url}/{endpoint}",
            request_data=request_data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
        )
        self._LOGGER.debug(
            "Call to Bot API endpoint `%s` finished with return value `%s`", endpoint, result
        )

        return result

    async def _send_message(
        self,
        endpoint: str,
        data: JSONDict,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        link_preview_options: ODVInput["LinkPreviewOptions"] = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Any:
        """Protected method to send or edit messages of any type.

        It is here to reduce repetition of if-else closes in the different bot methods,
        i.e. this method takes care of adding its parameters to `data` if appropriate.

        Depending on the bot method, returns either `True` or the message.
        However, it's hard to tell mypy which methods expects which of these return values and
        using `Any` instead saves us a lot of `type: ignore` comments
        """
        # We don't check if (DEFAULT_)None here, so that _post is able to insert the defaults
        # correctly, if necessary:
        if allow_sending_without_reply is not DEFAULT_NONE and reply_parameters is not None:
            raise ValueError(
                "`allow_sending_without_reply` and `reply_parameters` are mutually exclusive."
            )

        if reply_to_message_id is not None and reply_parameters is not None:
            raise ValueError(
                "`reply_to_message_id` and `reply_parameters` are mutually exclusive."
            )

        if reply_to_message_id is not None:
            reply_parameters = ReplyParameters(
                message_id=reply_to_message_id,
                allow_sending_without_reply=allow_sending_without_reply,
            )

        data.update(
            {
                "allow_paid_broadcast": allow_paid_broadcast,
                "business_connection_id": business_connection_id,
                "caption": caption,
                "caption_entities": caption_entities,
                "direct_messages_topic_id": direct_messages_topic_id,
                "disable_notification": disable_notification,
                "link_preview_options": link_preview_options,
                "message_thread_id": message_thread_id,
                "message_effect_id": message_effect_id,
                "parse_mode": parse_mode,
                "protect_content": protect_content,
                "reply_markup": reply_markup,
                "reply_parameters": reply_parameters,
                "suggested_post_parameters": suggested_post_parameters,
            }
        )

        result = await self._post(
            endpoint,
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        if result is True:
            return result

        return Message.de_json(result, self)

    async def initialize(self) -> None:
        """Initialize resources used by this class. Currently calls :meth:`get_me` to
        cache :attr:`bot` and calls :meth:`telegram.request.BaseRequest.initialize` for
        the request objects used by this bot.

        .. seealso:: :meth:`shutdown`

        .. versionadded:: 20.0
        """
        if self._requests_initialized and self._bot_initialized:
            self._LOGGER.debug("This Bot is already initialized.")
            return

        # Initialize request objects if not already done
        if not self._requests_initialized:
            await asyncio.gather(self._request[0].initialize(), self._request[1].initialize())
            self._requests_initialized = True

        # Initialize bot user
        # Since the bot is to be initialized only once, we can also use it for
        # verifying the token passed and raising an exception if it's invalid.
        try:
            await self.get_me()
            self._bot_initialized = True
        except InvalidToken as exc:
            raise InvalidToken(f"The token `{self._token}` was rejected by the server.") from exc

    async def shutdown(self) -> None:
        """Stop & clear resources used by this class. Currently just calls
        :meth:`telegram.request.BaseRequest.shutdown` for the request objects used by this bot.

        .. seealso:: :meth:`initialize`

        .. versionadded:: 20.0
        """
        if not self._requests_initialized:
            self._LOGGER.debug("This Bot is already shut down. Returning.")
            return

        await asyncio.gather(self._request[0].shutdown(), self._request[1].shutdown())
        self._requests_initialized = False
        self._bot_initialized = False

    async def do_api_request(
        self,
        endpoint: str,
        api_kwargs: JSONDict | None = None,
        return_type: type[TelegramObject] | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> Any:
        """Do a request to the Telegram API.

        This method is here to make it easier to use new API methods that are not yet supported
        by this library.

        Hint:
            Since PTB does not know which arguments are passed to this method, some caution is
            necessary in terms of PTBs utility functionalities. In particular

            * passing objects of any class defined in the :mod:`telegram` module is supported
            * when uploading files, a :class:`telegram.InputFile` must be passed as the value for
              the corresponding argument. Passing a file path or file-like object will not work.
              File paths will work only in combination with :paramref:`~Bot.local_mode`.
            * when uploading files, PTB can still correctly determine that
              a special write timeout value should be used instead of the default
              :paramref:`telegram.request.HTTPXRequest.write_timeout`.
            * insertion of default values specified via :class:`telegram.ext.Defaults` will not
              work (only relevant for :class:`telegram.ext.ExtBot`).
            * The only exception is :class:`telegram.ext.Defaults.tzinfo`, which will be correctly
              applied to :class:`datetime.datetime` objects.

        .. versionadded:: 20.8

        Args:
            endpoint (:obj:`str`): The API endpoint to use, e.g. ``getMe`` or ``get_me``.
            api_kwargs (:obj:`dict`, optional): The keyword arguments to pass to the API call.
                If not specified, no arguments are passed.
            return_type (:class:`telegram.TelegramObject`, optional): If specified, the result of
                the API call will be deserialized into an instance of this class or tuple of
                instances of this class. If not specified, the raw result of the API call will be
                returned.

        Returns:
            The result of the API call. If :paramref:`return_type` is not specified, this is a
            :obj:`dict` or :obj:`bool`, otherwise an instance of :paramref:`return_type` or a
            tuple of :paramref:`return_type`.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        if hasattr(self, endpoint):
            self._warn(
                (
                    f"Please use 'Bot.{endpoint}' instead of "
                    f"'Bot.do_api_request(\"{endpoint}\", ...)'"
                ),
                stacklevel=2,
            )

        camel_case_endpoint = to_camel_case(endpoint)
        try:
            result = await self._post(
                camel_case_endpoint,
                api_kwargs=api_kwargs,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
            )
        except InvalidToken as exc:
            # TG returns 404 Not found for
            #   1) malformed tokens
            #   2) correct tokens but non-existing method, e.g. api.tg.org/botTOKEN/unkonwnMethod
            # 2) is relevant only for Bot.do_api_request, that's why we have special handling for
            # that here rather than in BaseRequest._request_wrapper
            if self._bot_initialized:
                raise EndPointNotFound(
                    f"Endpoint '{camel_case_endpoint}' not found in Bot API"
                ) from exc

            raise InvalidToken(
                "Either the bot token was rejected by Telegram or the endpoint "
                f"'{camel_case_endpoint}' does not exist."
            ) from exc

        if return_type is None or isinstance(result, bool):
            return result

        if isinstance(result, list):
            return return_type.de_list(result, self)
        return return_type.de_json(result, self)

    async def get_me(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> User:
        """A simple method for testing your bot's auth token. Requires no parameters.

        Returns:
            :class:`telegram.User`: A :class:`telegram.User` instance representing that bot if the
            credentials are valid, :obj:`None` otherwise.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        result = await self._post(
            "getMe",
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        self._bot_user = User.de_json(result, self)
        return self._bot_user

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        entities: Sequence["MessageEntity"] | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        message_thread_id: int | None = None,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        disable_web_page_preview: bool | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send text messages.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            text (:obj:`str`): Text of the message to be sent. Max
                :tg-const:`telegram.constants.MessageLimit.MAX_TEXT_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`): |parse_mode|
            entities (Sequence[:class:`telegram.MessageEntity`], optional): Sequence of special
                entities that appear in message text, which can be specified instead of
                :paramref:`parse_mode`.

                .. versionchanged:: 20.0
                    |sequenceargs|
            link_preview_options (:obj:`LinkPreviewOptions`, optional): Link preview generation
                options for the message. Mutually exclusive with
                :paramref:`disable_web_page_preview`.

                .. versionadded:: 20.8

            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            disable_web_page_preview (:obj:`bool`, optional): Disables link previews for links in
                this message. Convenience parameter for setting :paramref:`link_preview_options`.
                Mutually exclusive with :paramref:`link_preview_options`.

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`link_preview_options` replacing this
                    argument. PTB will automatically convert this argument to that one, but
                    for advanced options, please use :paramref:`link_preview_options` directly.

                .. versionchanged:: 21.0
                    |keyword_only_arg|

        Returns:
            :class:`telegram.Message`: On success, the sent message is returned.

        Raises:
            :exc:`ValueError`: If both :paramref:`disable_web_page_preview` and
                :paramref:`link_preview_options` are passed.
            :class:`telegram.error.TelegramError`: For other errors.

        """
        data: JSONDict = {"chat_id": chat_id, "text": text, "entities": entities}
        link_preview_options = parse_lpo_and_dwpp(disable_web_page_preview, link_preview_options)

        return await self._send_message(
            "sendMessage",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            parse_mode=parse_mode,
            link_preview_options=link_preview_options,
            reply_parameters=reply_parameters,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_message(
        self,
        chat_id: str | int,
        message_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to delete a message, including service messages, with the following
        limitations:

        - A message can only be deleted if it was sent less than 48 hours ago.
        - Service messages about a supergroup, channel, or forum topic creation can't be deleted.
        - A dice message in a private chat can only be deleted if it was sent more than 24
          hours ago.
        - Bots can delete outgoing messages in private chats, groups, and supergroups.
        - Bots can delete incoming messages in private chats.
        - Bots granted :attr:`~telegram.ChatMemberAdministrator.can_post_messages` permissions
          can delete outgoing messages in channels.
        - If the bot is an administrator of a group, it can delete any message there.
        - If the bot has :attr:`~telegram.ChatMemberAdministrator.can_delete_messages`
          permission in a supergroup or a channel, it can delete any message there.

        ..
            The method CallbackQuery.delete_message() will not be found when automatically
            generating "Shortcuts" admonitions for Bot methods because it has no calls
            to Bot methods in its return statement(s). So it is manually included in "See also".

        .. seealso::
            :meth:`telegram.CallbackQuery.delete_message` (calls :meth:`delete_message`
            indirectly, via :meth:`telegram.Message.delete`)

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            message_id (:obj:`int`): Identifier of the message to delete.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "message_id": message_id}
        return await self._post(
            "deleteMessage",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_message_draft(
        self,
        chat_id: int,
        draft_id: int,
        text: str,
        message_thread_id: int | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        entities: Sequence["MessageEntity"] | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to stream a partial message to a user while the message is being
        generated; supported only for bots with forum topic mode enabled.

        .. versionadded:: 22.6

        Args:
            chat_id (:obj:`int`): Unique identifier for the target private chat.
            draft_id (:obj:`int`): Unique identifier of the message draft; must be non-zero.
                Changes of drafts with the same identifier are animated.
            text (:obj:`str`): Text of the message to be sent,
                :tg-const:`telegram.constants.MessageLimit.MIN_TEXT_LENGTH`-
                :tg-const:`telegram.constants.MessageLimit.MAX_TEXT_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`): |parse_mode|
            entities (Sequence[:class:`telegram.MessageEntity`], optional): Sequence of special
                entities that appear in message text, which can be specified instead of
                :paramref:`parse_mode`.

                    |sequenceargs|
            message_thread_id (:obj:`int`, optional): Unique identifier for the target
                message thread.


        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "draft_id": draft_id,
            "text": text,
            "entities": entities,
        }
        return await self._send_message(
            "sendMessageDraft",
            data,
            message_thread_id=message_thread_id,
            parse_mode=parse_mode,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: Sequence[int],
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to delete multiple messages simultaneously. If some of the specified
        messages can't be found, they are skipped.

        .. versionadded:: 20.8

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            message_ids (Sequence[:obj:`int`]): A list of
                :tg-const:`telegram.constants.BulkRequestLimit.MIN_LIMIT`-
                :tg-const:`telegram.constants.BulkRequestLimit.MAX_LIMIT` identifiers of messages
                to delete. See :meth:`delete_message` for limitations on which messages can be
                deleted.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"chat_id": chat_id, "message_ids": message_ids}
        return await self._post(
            "deleteMessages",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def forward_message(
        self,
        chat_id: int | str,
        from_chat_id: str | int,
        message_id: int,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        video_start_timestamp: int | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_effect_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to forward messages of any kind. Service messages can't be forwarded.

        Note:
            Since the release of Bot API 5.5 it can be impossible to forward messages from
            some chats. Use the attributes :attr:`telegram.Message.has_protected_content` and
            :attr:`telegram.ChatFullInfo.has_protected_content` to check this.

            As a workaround, it is still possible to use :meth:`copy_message`. However, this
            behaviour is undocumented and might be changed by Telegram.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            from_chat_id (:obj:`int` | :obj:`str`): Unique identifier for the chat where the
                original message was sent (or channel username in the format ``@channelusername``).
            message_id (:obj:`int`): Message identifier in the chat specified in
                :paramref:`from_chat_id`.
            video_start_timestamp (:obj:`int`, optional): New start timestamp for the
                forwarded video in the message

                .. versionadded:: 21.11
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional): An
                object containing the parameters of the suggested post to send; for direct messages
                chats only.

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): Identifier of the direct messages
                topic to which the message will be forwarded; required if the message is
                forwarded to a direct messages chat.

                .. versionadded:: 22.4
            message_effect_id (:obj:`str`, optional): Unique identifier of the message effect to be
                added to the message; only available when forwarding to private chats

                .. versionadded:: 22.6

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
            "video_start_timestamp": video_start_timestamp,
        }

        return await self._send_message(
            "forwardMessage",
            data,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            suggested_post_parameters=suggested_post_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            direct_messages_topic_id=direct_messages_topic_id,
            message_effect_id=message_effect_id,
        )

    async def forward_messages(
        self,
        chat_id: int | str,
        from_chat_id: str | int,
        message_ids: Sequence[int],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple[MessageId, ...]:
        """
        Use this method to forward messages of any kind. If some of the specified messages can't be
        found or forwarded, they are skipped. Service messages and messages with protected content
        can't be forwarded. Album grouping is kept for forwarded messages.

        .. versionadded:: 20.8

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            from_chat_id (:obj:`int` | :obj:`str`): Unique identifier for the chat where the
                original message was sent (or channel username in the format ``@channelusername``).
            message_ids (Sequence[:obj:`int`]): A list of
                :tg-const:`telegram.constants.BulkRequestLimit.MIN_LIMIT`-
                :tg-const:`telegram.constants.BulkRequestLimit.MAX_LIMIT` identifiers of messages
                in the chat :paramref:`from_chat_id` to forward. The identifiers must be specified
                in a strictly increasing order.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|
            direct_messages_topic_id (:obj:`int`, optional): Identifier of the direct messages
                topic to which the messages will be forwarded; required if the messages are
                forwarded to a direct messages chat.

                .. versionadded:: 22.4

        Returns:
            tuple[:class:`telegram.Message`]: On success, a tuple of ``MessageId`` of sent messages
            is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_ids": message_ids,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "message_thread_id": message_thread_id,
            "direct_messages_topic_id": direct_messages_topic_id,
        }

        result = await self._post(
            "forwardMessages",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return MessageId.de_list(result, self)

    async def send_photo(
        self,
        chat_id: int | str,
        photo: "FileInput | PhotoSize",
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        has_spoiler: bool | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send photos.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            photo (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | :obj:`bytes` \
                | :class:`pathlib.Path` | :class:`telegram.PhotoSize`): Photo to send.
                |fileinput|
                Lastly you can pass an existing :class:`telegram.PhotoSize` object to send.

                Caution:
                    * The photo must be at most 10MB in size.
                    * The photo's width and height must not exceed 10000 in total.
                    * Width and height ratio must be at most 20.

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.

                .. versionchanged:: 20.0
                    File paths as input is also accepted for bots *not* running in
                    :paramref:`~telegram.Bot.local_mode`.
            caption (:obj:`str`, optional): Photo caption (may also be used when resending photos
                by file_id), 0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH`
                characters after entities parsing.
            parse_mode (:obj:`str`, optional): |parse_mode|
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|

                .. versionchanged:: 20.0
                    |sequenceargs|
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            has_spoiler (:obj:`bool`, optional): Pass :obj:`True` if the photo needs to be covered
                with a spoiler animation.

                .. versionadded:: 20.0
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|

                .. versionadded:: 21.3
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            filename (:obj:`str`, optional): Custom file name for the photo, when uploading a
                new file. Convenience parameter, useful e.g. when sending files generated by the
                :obj:`tempfile` module.

                .. versionadded:: 13.1

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "photo": self._parse_file_input(photo, PhotoSize, filename=filename),
            "has_spoiler": has_spoiler,
            "show_caption_above_media": show_caption_above_media,
        }

        return await self._send_message(
            "sendPhoto",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_audio(
        self,
        chat_id: int | str,
        audio: "FileInput | Audio",
        duration: TimePeriod | None = None,
        performer: str | None = None,
        title: str | None = None,
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to send audio files, if you want Telegram clients to display them in the
        music player. Your audio must be in the ``.mp3`` or ``.m4a`` format.

        Bots can currently send audio files of up to
        :tg-const:`telegram.constants.FileSizeLimit.FILESIZE_UPLOAD` in size, this limit may be
        changed in the future.

        For sending voice messages, use the :meth:`send_voice` method instead.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        .. versionchanged:: 20.5
            |removed_thumb_arg|

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            audio (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | \
                :obj:`bytes` | :class:`pathlib.Path` | :class:`telegram.Audio`): Audio file to
                send. |fileinput|
                Lastly you can pass an existing :class:`telegram.Audio` object to send.

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.

                .. versionchanged:: 20.0
                    File paths as input is also accepted for bots *not* running in
                    :paramref:`~telegram.Bot.local_mode`.
            caption (:obj:`str`, optional): Audio caption,
                0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`, optional): |parse_mode|
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|

                .. versionchanged:: 20.0
                    |sequenceargs|
            duration (:obj:`int` | :class:`datetime.timedelta`, optional): Duration of sent audio
                in seconds.

                .. versionchanged:: 21.11
                    |time-period-input|
            performer (:obj:`str`, optional): Performer.
            title (:obj:`str`, optional): Track name.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            thumbnail (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`, \
                optional): |thumbdocstring|

                .. versionadded:: 20.2
            reply_parameters (:obj:`ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            filename (:obj:`str`, optional): Custom file name for the audio, when uploading a
                new file. Convenience parameter, useful e.g. when sending files generated by the
                :obj:`tempfile` module.

                .. versionadded:: 13.1

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "audio": self._parse_file_input(audio, Audio, filename=filename),
            "duration": duration,
            "performer": performer,
            "title": title,
            "thumbnail": self._parse_file_input(thumbnail, attach=True) if thumbnail else None,
        }

        return await self._send_message(
            "sendAudio",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_document(
        self,
        chat_id: int | str,
        document: "FileInput | Document",
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        disable_content_type_detection: bool | None = None,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to send general files.

        Bots can currently send files of any type of up to
        :tg-const:`telegram.constants.FileSizeLimit.FILESIZE_UPLOAD` in size, this limit may be
        changed in the future.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        .. versionchanged:: 20.5
            |removed_thumb_arg|

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            document (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | \
                :obj:`bytes` | :class:`pathlib.Path` | :class:`telegram.Document`): File to send.
                |fileinput|
                Lastly you can pass an existing :class:`telegram.Document` object to send.

                Note:
                    Sending by URL will currently only work ``GIF``, ``PDF`` & ``ZIP`` files.

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.

                .. versionchanged:: 20.0
                    File paths as input is also accepted for bots *not* running in
                    :paramref:`~telegram.Bot.local_mode`.
            caption (:obj:`str`, optional): Document caption (may also be used when resending
                documents by file_id), 0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH`
                characters after entities parsing.
            disable_content_type_detection (:obj:`bool`, optional): Disables automatic server-side
                content type detection for files uploaded using multipart/form-data.
            parse_mode (:obj:`str`, optional): |parse_mode|
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|

                .. versionchanged:: 20.0
                    |sequenceargs|
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            thumbnail (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`, \
                optional): |thumbdocstring|

                .. versionadded:: 20.2
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            filename (:obj:`str`, optional): Custom file name for the document, when uploading a
                new file. Convenience parameter, useful e.g. when sending files generated by the
                :obj:`tempfile` module.

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "document": self._parse_file_input(document, Document, filename=filename),
            "disable_content_type_detection": disable_content_type_detection,
            "thumbnail": self._parse_file_input(thumbnail, attach=True) if thumbnail else None,
        }

        return await self._send_message(
            "sendDocument",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_sticker(
        self,
        chat_id: int | str,
        sticker: "FileInput | Sticker",
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        emoji: str | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to send static ``.WEBP``, animated ``.TGS``, or video ``.WEBM`` stickers.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            sticker (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | \
                :obj:`bytes` | :class:`pathlib.Path` | :class:`telegram.Sticker`): Sticker to send.
                |fileinput| Video stickers can only be sent by a ``file_id``. Video and animated
                stickers can't be sent via an HTTP URL.

                Lastly you can pass an existing :class:`telegram.Sticker` object to send.

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.

                .. versionchanged:: 20.0
                    File paths as input is also accepted for bots *not* running in
                    :paramref:`~telegram.Bot.local_mode`.
            emoji (:obj:`str`, optional): Emoji associated with the sticker; only for just
                uploaded stickers

                .. versionadded:: 20.2
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "sticker": self._parse_file_input(sticker, Sticker),
            "emoji": emoji,
        }
        return await self._send_message(
            "sendSticker",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_video(
        self,
        chat_id: int | str,
        video: "FileInput | Video",
        duration: TimePeriod | None = None,
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        width: int | None = None,
        height: int | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        supports_streaming: bool | None = None,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        has_spoiler: bool | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        cover: "FileInput | None" = None,
        start_timestamp: int | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send video files, Telegram clients support mp4 videos
        (other formats may be sent as Document).

        Bots can currently send video files of up to
        :tg-const:`telegram.constants.FileSizeLimit.FILESIZE_UPLOAD` in size, this limit may be
        changed in the future.

        Note:
            :paramref:`thumbnail` will be ignored for small video files, for which Telegram can
            easily generate thumbnails. However, this behaviour is undocumented and might be
            changed by Telegram.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        .. versionchanged:: 20.5
            |removed_thumb_arg|

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            video (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | :obj:`bytes` \
                | :class:`pathlib.Path` | :class:`telegram.Video`): Video file to send.
                |fileinput|
                Lastly you can pass an existing :class:`telegram.Video` object to send.

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.

                .. versionchanged:: 20.0
                    File paths as input is also accepted for bots *not* running in
                    :paramref:`~telegram.Bot.local_mode`.
            duration (:obj:`int` | :class:`datetime.timedelta`, optional): Duration of sent video
                in seconds.

                .. versionchanged:: 21.11
                    |time-period-input|
            width (:obj:`int`, optional): Video width.
            height (:obj:`int`, optional): Video height.
            cover (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`, \
                optional): Cover for the video in the message. |fileinputnopath|

                .. versionadded:: 21.11
            start_timestamp (:obj:`int`, optional): Start timestamp for the video in the message.

                .. versionadded:: 21.11
            caption (:obj:`str`, optional): Video caption (may also be used when resending videos
                by file_id), 0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH`
                characters after entities parsing.
            parse_mode (:obj:`str`, optional): |parse_mode|
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|

                .. versionchanged:: 20.0
                    |sequenceargs|
            supports_streaming (:obj:`bool`, optional): Pass :obj:`True`, if the uploaded video is
                suitable for streaming.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            has_spoiler (:obj:`bool`, optional): Pass :obj:`True` if the video needs to be covered
                with a spoiler animation.

                .. versionadded:: 20.0
            thumbnail (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`, \
                optional): |thumbdocstring|

                .. versionadded:: 20.2
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|

                .. versionadded:: 21.3
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            filename (:obj:`str`, optional): Custom file name for the video, when uploading a
                new file. Convenience parameter, useful e.g. when sending files generated by the
                :obj:`tempfile` module.

                .. versionadded:: 13.1

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "video": self._parse_file_input(video, Video, filename=filename),
            "duration": duration,
            "width": width,
            "height": height,
            "supports_streaming": supports_streaming,
            "cover": self._parse_file_input(cover, attach=True) if cover else None,
            "start_timestamp": start_timestamp,
            "thumbnail": self._parse_file_input(thumbnail, attach=True) if thumbnail else None,
            "has_spoiler": has_spoiler,
            "show_caption_above_media": show_caption_above_media,
        }

        return await self._send_message(
            "sendVideo",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_video_note(
        self,
        chat_id: int | str,
        video_note: "FileInput | VideoNote",
        duration: TimePeriod | None = None,
        length: int | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        As of v.4.0, Telegram clients support rounded square mp4 videos of up to 1 minute long.
        Use this method to send video messages.

        Note:
            :paramref:`thumbnail` will be ignored for small video files, for which Telegram can
            easily generate thumbnails. However, this behaviour is undocumented and might be
            changed by Telegram.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        .. versionchanged:: 20.5
            |removed_thumb_arg|

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            video_note (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | \
                :obj:`bytes` | :class:`pathlib.Path` | :class:`telegram.VideoNote`): Video note
                to send.
                Pass a file_id as String to send a video note that exists on the Telegram
                servers (recommended) or upload a new video using multipart/form-data.
                |uploadinput|
                Lastly you can pass an existing :class:`telegram.VideoNote` object to send.
                Sending video notes by a URL is currently unsupported.

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.

                .. versionchanged:: 20.0
                    File paths as input is also accepted for bots *not* running in
                    :paramref:`~telegram.Bot.local_mode`.
            duration (:obj:`int` | :class:`datetime.timedelta`, optional): Duration of sent video
                in seconds.

                .. versionchanged:: 21.11
                    |time-period-input|
            length (:obj:`int`, optional): Video width and height, i.e. diameter of the video
                message.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            thumbnail (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`, \
                optional): |thumbdocstring|

                .. versionadded:: 20.2
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            filename (:obj:`str`, optional): Custom file name for the video note, when uploading a
                new file. Convenience parameter, useful e.g. when sending files generated by the
                :obj:`tempfile` module.

                .. versionadded:: 13.1

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "video_note": self._parse_file_input(video_note, VideoNote, filename=filename),
            "duration": duration,
            "length": length,
            "thumbnail": self._parse_file_input(thumbnail, attach=True) if thumbnail else None,
        }

        return await self._send_message(
            "sendVideoNote",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_animation(
        self,
        chat_id: int | str,
        animation: "FileInput | Animation",
        duration: TimePeriod | None = None,
        width: int | None = None,
        height: int | None = None,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        has_spoiler: bool | None = None,
        thumbnail: "FileInput | None" = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        show_caption_above_media: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to send animation files (GIF or H.264/MPEG-4 AVC video without sound).
        Bots can currently send animation files of up to
        :tg-const:`telegram.constants.FileSizeLimit.FILESIZE_UPLOAD` in size, this limit may be
        changed in the future.

        Note:
            :paramref:`thumbnail` will be ignored for small files, for which Telegram can easily
            generate thumbnails. However, this behaviour is undocumented and might be changed
            by Telegram.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        .. versionchanged:: 20.5
            |removed_thumb_arg|

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            animation (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | \
                :obj:`bytes` | :class:`pathlib.Path` | :class:`telegram.Animation`): Animation to
                send. |fileinput|
                Lastly you can pass an existing :class:`telegram.Animation` object to send.

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.
            duration (:obj:`int` | :class:`datetime.timedelta`, optional): Duration of sent
                animation in seconds.

                .. versionchanged:: 21.11
                    |time-period-input|
            width (:obj:`int`, optional): Animation width.
            height (:obj:`int`, optional): Animation height.
            caption (:obj:`str`, optional): Animation caption (may also be used when resending
                animations by file_id),
                0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`, optional): |parse_mode|
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|

                .. versionchanged:: 20.0
                    |sequenceargs|
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            has_spoiler (:obj:`bool`, optional): Pass :obj:`True` if the animation needs to be
                covered with a spoiler animation.

                .. versionadded:: 20.0
            thumbnail (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`, \
                optional): |thumbdocstring|

                .. versionadded:: 20.2
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|

                .. versionadded:: 21.3
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            filename (:obj:`str`, optional): Custom file name for the animation, when uploading a
                new file. Convenience parameter, useful e.g. when sending files generated by the
                :obj:`tempfile` module.

                .. versionadded:: 13.1

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "animation": self._parse_file_input(animation, Animation, filename=filename),
            "duration": duration,
            "width": width,
            "height": height,
            "thumbnail": self._parse_file_input(thumbnail, attach=True) if thumbnail else None,
            "has_spoiler": has_spoiler,
            "show_caption_above_media": show_caption_above_media,
        }

        return await self._send_message(
            "sendAnimation",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_voice(
        self,
        chat_id: int | str,
        voice: "FileInput | Voice",
        duration: TimePeriod | None = None,
        caption: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to send audio files, if you want Telegram clients to display the file
        as a playable voice message. For this to work, your audio must be in an ``.ogg`` file
        encoded with OPUS , or in .MP3 format, or in .M4A format (other formats may be sent as
        :class:`~telegram.Audio` or :class:`~telegram.Document`). Bots can currently send voice
        messages of up to :tg-const:`telegram.constants.FileSizeLimit.FILESIZE_UPLOAD` in size,
        this limit may be changed in the future.

        Note:
            To use this method, the file must have the type :mimetype:`audio/ogg` and be no more
            than :tg-const:`telegram.constants.FileSizeLimit.VOICE_NOTE_FILE_SIZE` in size.
            :tg-const:`telegram.constants.FileSizeLimit.VOICE_NOTE_FILE_SIZE`-
            :tg-const:`telegram.constants.FileSizeLimit.FILESIZE_DOWNLOAD` voice notes will be
            sent as files.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            voice (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | :obj:`bytes` \
                | :class:`pathlib.Path` | :class:`telegram.Voice`): Voice file to send.
                |fileinput|
                Lastly you can pass an existing :class:`telegram.Voice` object to send.

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.

                .. versionchanged:: 20.0
                    File paths as input is also accepted for bots *not* running in
                    :paramref:`~telegram.Bot.local_mode`.
            caption (:obj:`str`, optional): Voice message caption,
                0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`, optional): |parse_mode|
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|

                .. versionchanged:: 20.0
                    |sequenceargs|
            duration (:obj:`int` | :class:`datetime.timedelta`, optional): Duration of the voice
                message in seconds.

                .. versionchanged:: 21.11
                    |time-period-input|
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            filename (:obj:`str`, optional): Custom file name for the voice, when uploading a
                new file. Convenience parameter, useful e.g. when sending files generated by the
                :obj:`tempfile` module.

                .. versionadded:: 13.1

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "voice": self._parse_file_input(voice, Voice, filename=filename),
            "duration": duration,
        }

        return await self._send_message(
            "sendVoice",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_media_group(
        self,
        chat_id: int | str,
        media: Sequence[
            "InputMediaAudio | InputMediaDocument | InputMediaPhoto | InputMediaVideo"
        ],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
    ) -> tuple[Message, ...]:
        """Use this method to send a group of photos, videos, documents or audios as an album.
        Documents and audio files can be only grouped in an album with messages of the same type.

        Note:
            If you supply a :paramref:`caption` (along with either :paramref:`parse_mode` or
            :paramref:`caption_entities`), then items in :paramref:`media` must have no captions,
            and vice versa.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        .. versionchanged:: 20.0
            Returns a tuple instead of a list.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            media (Sequence[:class:`telegram.InputMediaAudio`,\
                :class:`telegram.InputMediaDocument`, :class:`telegram.InputMediaPhoto`,\
                :class:`telegram.InputMediaVideo`]): An array
                describing messages to be sent, must include
                :tg-const:`telegram.constants.MediaGroupLimit.MIN_MEDIA_LENGTH`-
                :tg-const:`telegram.constants.MediaGroupLimit.MAX_MEDIA_LENGTH` items.

                .. versionchanged:: 20.0
                    |sequenceargs|
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            direct_messages_topic_id (:obj:`int`, optional): Identifier of the direct messages
                topic to which the messages will be sent; required if the messages are sent to a
                direct messages chat.

                .. versionadded:: 22.4


        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            caption (:obj:`str`, optional): Caption that will be added to the
                first element of :paramref:`media`, so that it will be used as caption for the
                whole media group.
                Defaults to :obj:`None`.

                .. versionadded:: 20.0
            parse_mode (:obj:`str` | :obj:`None`, optional):
                Parse mode for :paramref:`caption`.
                See the constants in :class:`telegram.constants.ParseMode` for the
                available modes.

                .. versionadded:: 20.0
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                List of special entities for :paramref:`caption`,
                which can be specified instead of :paramref:`parse_mode`.
                Defaults to :obj:`None`.

                .. versionadded:: 20.0

        Returns:
            tuple[:class:`telegram.Message`]: An array of the sent Messages.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        if caption and any(
            [
                any(item.caption for item in media),
                any(item.caption_entities for item in media),
                # if parse_mode was set explicitly, even to None, error must be raised
                any(item.parse_mode is not DEFAULT_NONE for item in media),
            ]
        ):
            raise ValueError("You can only supply either group caption or media with captions.")

        if caption:
            # Copy first item (to avoid mutation of original object), apply group caption to it.
            # This will lead to the group being shown with this caption.
            item_to_get_caption = copy.copy(media[0])
            with item_to_get_caption._unfrozen():
                item_to_get_caption.caption = caption
                if parse_mode is not DEFAULT_NONE:
                    item_to_get_caption.parse_mode = parse_mode
                item_to_get_caption.caption_entities = parse_sequence_arg(caption_entities)

            # copy the list (just the references) to avoid mutating the original list
            media = list(media)
            media[0] = item_to_get_caption

        if allow_sending_without_reply is not DEFAULT_NONE and reply_parameters is not None:
            raise ValueError(
                "`allow_sending_without_reply` and `reply_parameters` are mutually exclusive."
            )

        if reply_to_message_id is not None and reply_parameters is not None:
            raise ValueError(
                "`reply_to_message_id` and `reply_parameters` are mutually exclusive."
            )

        if reply_to_message_id is not None:
            reply_parameters = ReplyParameters(
                message_id=reply_to_message_id,
                allow_sending_without_reply=allow_sending_without_reply,
            )

        data: JSONDict = {
            "chat_id": chat_id,
            "media": media,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "message_thread_id": message_thread_id,
            "reply_parameters": reply_parameters,
            "business_connection_id": business_connection_id,
            "message_effect_id": message_effect_id,
            "allow_paid_broadcast": allow_paid_broadcast,
            "direct_messages_topic_id": direct_messages_topic_id,
        }

        result = await self._post(
            "sendMediaGroup",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return Message.de_list(result, self)

    async def send_location(
        self,
        chat_id: int | str,
        latitude: float | None = None,
        longitude: float | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        live_period: TimePeriod | None = None,
        horizontal_accuracy: float | None = None,
        heading: int | None = None,
        proximity_alert_radius: int | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        location: "Location | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send point on the map.

        Note:
            You can either supply a :paramref:`latitude` and :paramref:`longitude` or a
            :paramref:`location`.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            latitude (:obj:`float`, optional): Latitude of location.
            longitude (:obj:`float`, optional): Longitude of location.
            horizontal_accuracy (:obj:`int`, optional): The radius of uncertainty for the location,
                measured in meters;
                0-:tg-const:`telegram.constants.LocationLimit.HORIZONTAL_ACCURACY`.
            live_period (:obj:`int` | :class:`datetime.timedelta`, optional): Period in seconds for
                which the location will be
                updated, should be between
                :tg-const:`telegram.constants.LocationLimit.MIN_LIVE_PERIOD` and
                :tg-const:`telegram.constants.LocationLimit.MAX_LIVE_PERIOD`, or
                :tg-const:`telegram.constants.LocationLimit.LIVE_PERIOD_FOREVER` for live
                locations that can be edited indefinitely.

                .. versionchanged:: 21.11
                    |time-period-input|
            heading (:obj:`int`, optional): For live locations, a direction in which the user is
                moving, in degrees. Must be between
                :tg-const:`telegram.constants.LocationLimit.MIN_HEADING` and
                :tg-const:`telegram.constants.LocationLimit.MAX_HEADING` if specified.
            proximity_alert_radius (:obj:`int`, optional): For live locations, a maximum distance
                for proximity alerts about approaching another chat member, in meters. Must be
                between :tg-const:`telegram.constants.LocationLimit.MIN_PROXIMITY_ALERT_RADIUS`
                and :tg-const:`telegram.constants.LocationLimit.MAX_PROXIMITY_ALERT_RADIUS`
                if specified.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            location (:class:`telegram.Location`, optional): The location to send.

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        if not ((latitude is not None and longitude is not None) or location):
            raise ValueError(
                "Either location or latitude and longitude must be passed as argument."
            )

        if not (latitude is not None or longitude is not None) ^ bool(location):
            raise ValueError(
                "Either location or latitude and longitude must be passed as argument. Not both."
            )

        if isinstance(location, Location):
            latitude = location.latitude
            longitude = location.longitude

        data: JSONDict = {
            "chat_id": chat_id,
            "latitude": latitude,
            "longitude": longitude,
            "horizontal_accuracy": horizontal_accuracy,
            "live_period": live_period,
            "heading": heading,
            "proximity_alert_radius": proximity_alert_radius,
        }

        return await self._send_message(
            "sendLocation",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def edit_message_live_location(
        self,
        chat_id: str | int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        horizontal_accuracy: float | None = None,
        heading: int | None = None,
        proximity_alert_radius: int | None = None,
        live_period: TimePeriod | None = None,
        business_connection_id: str | None = None,
        *,
        location: "Location | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Use this method to edit live location messages sent by the bot or via the bot
        (for inline bots). A location can be edited until its :attr:`telegram.Location.live_period`
        expires or editing is explicitly disabled by a call to :meth:`stop_message_live_location`.

        Note:
            You can either supply a :paramref:`latitude` and :paramref:`longitude` or a
            :paramref:`location`.

        Args:
            chat_id (:obj:`int` | :obj:`str`, optional): Required if :paramref:`inline_message_id`
                is not specified. |chat_id_channel|
            message_id (:obj:`int`, optional): Required if :paramref:`inline_message_id` is not
                specified. Identifier of the message to edit.
            inline_message_id (:obj:`str`, optional): Required if :paramref:`chat_id` and
                :paramref:`message_id` are not specified. Identifier of the inline message.
            latitude (:obj:`float`, optional): Latitude of location.
            longitude (:obj:`float`, optional): Longitude of location.
            horizontal_accuracy (:obj:`float`, optional): The radius of uncertainty for the
                location, measured in meters;
                0-:tg-const:`telegram.constants.LocationLimit.HORIZONTAL_ACCURACY`.
            heading (:obj:`int`, optional): Direction in which the user is moving, in degrees. Must
                be between :tg-const:`telegram.constants.LocationLimit.MIN_HEADING`
                and :tg-const:`telegram.constants.LocationLimit.MAX_HEADING` if specified.
            proximity_alert_radius (:obj:`int`, optional): Maximum distance for proximity alerts
                about approaching another chat member, in meters. Must be between
                :tg-const:`telegram.constants.LocationLimit.MIN_PROXIMITY_ALERT_RADIUS`
                and :tg-const:`telegram.constants.LocationLimit.MAX_PROXIMITY_ALERT_RADIUS`
                if specified.
            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for a new
                inline keyboard.
            live_period (:obj:`int` | :class:`datetime.timedelta`, optional): New period in seconds
                during which the location
                can be updated, starting from the message send date. If
                :tg-const:`telegram.constants.LocationLimit.LIVE_PERIOD_FOREVER` is specified,
                then the location can be updated forever. Otherwise, the new value must not exceed
                the current ``live_period`` by more than a day, and the live location expiration
                date must remain within the next 90 days. If not specified, then ``live_period``
                remains unchanged

                .. versionadded:: 21.2.

                .. versionchanged:: 21.11
                    |time-period-input|
            business_connection_id (:obj:`str`, optional): |business_id_str_edit|

                .. versionadded:: 21.4

        Keyword Args:
            location (:class:`telegram.Location`, optional): The location to send.

        Returns:
            :class:`telegram.Message`: On success, if edited message is not an inline message, the
            edited message is returned, otherwise :obj:`True` is returned.
        """
        # The location parameter is a convenience functionality added by us, so enforcing the
        # mutual exclusivity here is nothing that Telegram would handle anyway
        if not (all([latitude, longitude]) or location):
            raise ValueError(
                "Either location or latitude and longitude must be passed as argument."
            )
        if not (latitude is not None or longitude is not None) ^ bool(location):
            raise ValueError(
                "Either location or latitude and longitude must be passed as argument. Not both."
            )

        if isinstance(location, Location):
            latitude = location.latitude
            longitude = location.longitude

        data: JSONDict = {
            "latitude": latitude,
            "longitude": longitude,
            "chat_id": chat_id,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
            "horizontal_accuracy": horizontal_accuracy,
            "heading": heading,
            "proximity_alert_radius": proximity_alert_radius,
            "live_period": live_period,
        }

        return await self._send_message(
            "editMessageLiveLocation",
            data,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def stop_message_live_location(
        self,
        chat_id: str | int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """Use this method to stop updating a live location message sent by the bot or via the bot
        (for inline bots) before :paramref:`~telegram.Location.live_period` expires.

        Args:
            chat_id (:obj:`int` | :obj:`str`, optional): Required if :paramref:`inline_message_id`
                is not specified. |chat_id_channel|
            message_id (:obj:`int`, optional): Required if :paramref:`inline_message_id` is not
                specified. Identifier of the sent message with live location to stop.
            inline_message_id (:obj:`str`, optional): Required if :paramref:`chat_id` and
                :paramref:`message_id` are not specified. Identifier of the inline message.
            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for a new
                inline keyboard.
            business_connection_id (:obj:`str`, optional): |business_id_str_edit|

                .. versionadded:: 21.4

        Returns:
            :class:`telegram.Message`: On success, if edited message is not an inline message, the
            edited message is returned, otherwise :obj:`True` is returned.
        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
        }

        return await self._send_message(
            "stopMessageLiveLocation",
            data,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_venue(
        self,
        chat_id: int | str,
        latitude: float | None = None,
        longitude: float | None = None,
        title: str | None = None,
        address: str | None = None,
        foursquare_id: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        foursquare_type: str | None = None,
        google_place_id: str | None = None,
        google_place_type: str | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        venue: "Venue | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send information about a venue.

        Note:
            * You can either supply :paramref:`venue`, or :paramref:`latitude`,
              :paramref:`longitude`, :paramref:`title` and :paramref:`address` and optionally
              :paramref:`foursquare_id` and :paramref:`foursquare_type` or optionally
              :paramref:`google_place_id` and :paramref:`google_place_type`.
            * Foursquare details and Google Place details are mutually exclusive. However, this
              behaviour is undocumented and might be changed by Telegram.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            latitude (:obj:`float`, optional): Latitude of venue.
            longitude (:obj:`float`, optional): Longitude of venue.
            title (:obj:`str`, optional): Name of the venue.
            address (:obj:`str`, optional): Address of the venue.
            foursquare_id (:obj:`str`, optional): Foursquare identifier of the venue.
            foursquare_type (:obj:`str`, optional): Foursquare type of the venue, if known.
                (For example, "arts_entertainment/default", "arts_entertainment/aquarium" or
                "food/icecream".)
            google_place_id (:obj:`str`, optional): Google Places identifier of the venue.
            google_place_type (:obj:`str`, optional): Google Places type of the venue. (See
                `supported types \
                <https://developers.google.com/maps/documentation/places/web-service/place-types>`_.)
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            venue (:class:`telegram.Venue`, optional): The venue to send.

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        # The venue parameter is a convenience functionality added by us, so enforcing the
        # mutual exclusivity here is nothing that Telegram would handle anyway
        if not (venue or all([latitude, longitude, address, title])):
            raise ValueError(
                "Either venue or latitude, longitude, address and title must be "
                "passed as arguments."
            )
        if not bool(venue) ^ any([latitude, longitude, address, title]):
            raise ValueError(
                "Either venue or latitude, longitude, address and title must be "
                "passed as arguments. Not both."
            )

        if isinstance(venue, Venue):
            latitude = venue.location.latitude
            longitude = venue.location.longitude
            address = venue.address
            title = venue.title
            foursquare_id = venue.foursquare_id
            foursquare_type = venue.foursquare_type
            google_place_id = venue.google_place_id
            google_place_type = venue.google_place_type

        data: JSONDict = {
            "chat_id": chat_id,
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
            "title": title,
            "foursquare_id": foursquare_id,
            "foursquare_type": foursquare_type,
            "google_place_id": google_place_id,
            "google_place_type": google_place_type,
        }

        return await self._send_message(
            "sendVenue",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_contact(
        self,
        chat_id: int | str,
        phone_number: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        vcard: str | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        contact: "Contact | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send phone contacts.

        Note:
            You can either supply :paramref:`contact` or :paramref:`phone_number` and
            :paramref:`first_name` with optionally :paramref:`last_name` and optionally
            :paramref:`vcard`.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            phone_number (:obj:`str`, optional): Contact's phone number.
            first_name (:obj:`str`, optional): Contact's first name.
            last_name (:obj:`str`, optional): Contact's last name.
            vcard (:obj:`str`, optional): Additional data about the contact in the form of a vCard,
                0-:tg-const:`telegram.constants.ContactLimit.VCARD` bytes.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            contact (:class:`telegram.Contact`, optional): The contact to send.

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        # The contact parameter is a convenience functionality added by us, so enforcing the
        # mutual exclusivity here is nothing that Telegram would handle anyway
        if (not contact) and (not all([phone_number, first_name])):
            raise ValueError(
                "Either contact or phone_number and first_name must be passed as arguments."
            )
        if not bool(contact) ^ any([phone_number, first_name]):
            raise ValueError(
                "Either contact or phone_number and first_name must be passed as arguments. "
                "Not both."
            )

        if isinstance(contact, Contact):
            phone_number = contact.phone_number
            first_name = contact.first_name
            last_name = contact.last_name
            vcard = contact.vcard

        data: JSONDict = {
            "chat_id": chat_id,
            "phone_number": phone_number,
            "first_name": first_name,
            "last_name": last_name,
            "vcard": vcard,
        }

        return await self._send_message(
            "sendContact",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def send_game(
        self,
        chat_id: int,
        game_short_name: str,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send a game.

        Args:
            chat_id (:obj:`int`): Unique identifier for the target chat.
            game_short_name (:obj:`str`): Short name of the game, serves as the unique identifier
                for the game. Set up your games via `@BotFather <https://t.me/BotFather>`_.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for a new
                inline keyboard. If empty, one "Play game_title" button will be
                shown. If not empty, the first button must launch the game.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "game_short_name": game_short_name}

        return await self._send_message(
            "sendGame",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
        )

    async def send_chat_action(
        self,
        chat_id: str | int,
        action: str,
        message_thread_id: int | None = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method when you need to tell the user that something is happening on the bot's
        side. The status is set for 5 seconds or less (when a message arrives from your bot,
        Telegram clients clear its typing status). Telegram only recommends using this method when
        a response from the bot will take a noticeable amount of time to arrive.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            action(:obj:`str`): Type of action to broadcast. Choose one, depending on what the user
                is about to receive. For convenience look at the constants in
                :class:`telegram.constants.ChatAction`.
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1

        Returns:
            :obj:`bool`:  On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "action": action,
            "message_thread_id": message_thread_id,
            "business_connection_id": business_connection_id,
        }
        return await self._post(
            "sendChatAction",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    def _effective_inline_results(
        self,
        results: Sequence["InlineQueryResult"]
        | (Callable[[int], Sequence["InlineQueryResult"] | None]),
        next_offset: str | None = None,
        current_offset: str | None = None,
    ) -> tuple[Sequence["InlineQueryResult"], str | None]:
        """
        Builds the effective results from the results input.
        We make this a stand-alone method so tg.ext.ExtBot can wrap it.

        Returns:
            Tuple of 1. the effective results and 2. correct the next_offset

        """
        if current_offset is not None and next_offset is not None:
            raise ValueError("`current_offset` and `next_offset` are mutually exclusive!")

        if current_offset is not None:
            # Convert the string input to integer
            current_offset_int = 0 if not current_offset else int(current_offset)

            # for now set to empty string, stating that there are no more results
            # might change later
            next_offset = ""

            if callable(results):
                callable_output = results(current_offset_int)
                if not callable_output:
                    effective_results: Sequence[InlineQueryResult] = []
                else:
                    effective_results = callable_output
                    # the callback *might* return more results on the next call, so we increment
                    # the page count
                    next_offset = str(current_offset_int + 1)

            elif len(results) > (current_offset_int + 1) * InlineQueryLimit.RESULTS:
                # we expect more results for the next page
                next_offset_int = current_offset_int + 1
                next_offset = str(next_offset_int)
                effective_results = results[
                    current_offset_int * InlineQueryLimit.RESULTS : next_offset_int
                    * InlineQueryLimit.RESULTS
                ]
            else:
                effective_results = results[current_offset_int * InlineQueryLimit.RESULTS :]
        else:
            effective_results = results  # type: ignore[assignment]

        return effective_results, next_offset

    @no_type_check  # mypy doesn't play too well with hasattr
    def _insert_defaults_for_ilq_results(self, res: "InlineQueryResult") -> "InlineQueryResult":
        """The reason why this method exists is similar to the description of _insert_defaults
        The reason why we do this in rather than in _insert_defaults is because converting
        DEFAULT_NONE to NONE *before* calling to_dict() makes it way easier to drop None entries
        from the json data.

        Must return the correct object instead of editing in-place!
        """
        # Copy the objects that need modification to avoid modifying the original object
        copied = False
        if hasattr(res, "parse_mode"):
            res = copy.copy(res)
            copied = True
            with res._unfrozen():
                res.parse_mode = DefaultValue.get_value(res.parse_mode)
        if hasattr(res, "input_message_content") and res.input_message_content:
            if hasattr(res.input_message_content, "parse_mode"):
                if not copied:
                    res = copy.copy(res)
                    copied = True

                with res._unfrozen():
                    res.input_message_content = copy.copy(res.input_message_content)
                with res.input_message_content._unfrozen():
                    res.input_message_content.parse_mode = DefaultValue.get_value(
                        res.input_message_content.parse_mode
                    )
            if hasattr(res.input_message_content, "link_preview_options"):
                if not copied:
                    res = copy.copy(res)

                with res._unfrozen():
                    res.input_message_content = copy.copy(res.input_message_content)
                with res.input_message_content._unfrozen():
                    res.input_message_content.link_preview_options = DefaultValue.get_value(
                        res.input_message_content.link_preview_options
                    )

        return res

    async def answer_inline_query(
        self,
        inline_query_id: str,
        results: Sequence["InlineQueryResult"]
        | (Callable[[int], Sequence["InlineQueryResult"] | None]),
        cache_time: TimePeriod | None = None,
        is_personal: bool | None = None,
        next_offset: str | None = None,
        button: InlineQueryResultsButton | None = None,
        *,
        current_offset: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to send answers to an inline query. No more than
        :tg-const:`telegram.InlineQuery.MAX_RESULTS` results per query are allowed.

        Warning:
            In most use cases :paramref:`current_offset` should not be passed manually. Instead of
            calling this method directly, use the shortcut :meth:`telegram.InlineQuery.answer` with
            :paramref:`telegram.InlineQuery.answer.auto_pagination` set to :obj:`True`, which will
            take care of passing the correct value.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`


        .. versionchanged:: 20.5
           Removed deprecated arguments ``switch_pm_text`` and ``switch_pm_parameter``.

        Args:
            inline_query_id (:obj:`str`): Unique identifier for the answered query.
            results (list[:class:`telegram.InlineQueryResult`] | Callable): A list of results for
                the inline query. In case :paramref:`current_offset` is passed,
                :paramref:`results` may also be
                a callable that accepts the current page index starting from 0. It must return
                either a list of :class:`telegram.InlineQueryResult` instances or :obj:`None` if
                there are no more results.
            cache_time (:obj:`int` | :class:`datetime.timedelta`, optional): The maximum amount of
                time in seconds that the
                result of the inline query may be cached on the server. Defaults to ``300``.

                .. versionchanged:: 21.11
                    |time-period-input|
            is_personal (:obj:`bool`, optional): Pass :obj:`True`, if results may be cached on
                the server side only for the user that sent the query. By default,
                results may be returned to any user who sends the same query.
            next_offset (:obj:`str`, optional): Pass the offset that a client should send in the
                next query with the same text to receive more results. Pass an empty string if
                there are no more results or if you don't support pagination. Offset length can't
                exceed :tg-const:`telegram.InlineQuery.MAX_OFFSET_LENGTH` bytes.
            button (:class:`telegram.InlineQueryResultsButton`, optional): A button to be shown
                above the inline query results.

                .. versionadded:: 20.3

        Keyword Args:
            current_offset (:obj:`str`, optional): The :attr:`telegram.InlineQuery.offset` of
                the inline query to answer. If passed, PTB will automatically take care of
                the pagination for you, i.e. pass the correct :paramref:`next_offset` and truncate
                the results list/get the results from the callable you passed.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        effective_results, next_offset = self._effective_inline_results(
            results=results, next_offset=next_offset, current_offset=current_offset
        )

        # Apply defaults
        effective_results = [
            self._insert_defaults_for_ilq_results(result) for result in effective_results
        ]

        data: JSONDict = {
            "inline_query_id": inline_query_id,
            "results": effective_results,
            "next_offset": next_offset,
            "cache_time": cache_time,
            "is_personal": is_personal,
            "button": button,
        }

        return await self._post(
            "answerInlineQuery",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def save_prepared_inline_message(
        self,
        user_id: int,
        result: "InlineQueryResult",
        allow_user_chats: bool | None = None,
        allow_bot_chats: bool | None = None,
        allow_group_chats: bool | None = None,
        allow_channel_chats: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> PreparedInlineMessage:
        """Stores a message that can be sent by a user of a Mini App.

        .. versionadded:: 21.8

        Args:
            user_id (:obj:`int`): Unique identifier of the target user that can use the prepared
                message.
            result (:class:`telegram.InlineQueryResult`): The result to store.
            allow_user_chats (:obj:`bool`, optional): Pass :obj:`True` if the message can be sent
                to private chats with users
            allow_bot_chats (:obj:`bool`, optional): Pass :obj:`True` if the message can be sent
                to private chats with bots
            allow_group_chats (:obj:`bool`, optional): Pass :obj:`True` if the message can be sent
                to group and supergroup chats
            allow_channel_chats (:obj:`bool`, optional): Pass :obj:`True` if the message can be
                sent to channels

        Returns:
            :class:`telegram.PreparedInlineMessage`: On success, the prepared message is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
            "result": result,
            "allow_user_chats": allow_user_chats,
            "allow_bot_chats": allow_bot_chats,
            "allow_group_chats": allow_group_chats,
            "allow_channel_chats": allow_channel_chats,
        }
        return PreparedInlineMessage.de_json(
            await self._post(
                "savePreparedInlineMessage",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            self,
        )

    async def get_user_profile_photos(
        self,
        user_id: int,
        offset: int | None = None,
        limit: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "UserProfilePhotos":
        """Use this method to get a list of profile pictures for a user.

        Args:
            user_id (:obj:`int`): Unique identifier of the target user.
            offset (:obj:`int`, optional): Sequential number of the first photo to be returned.
                By default, all photos are returned.
            limit (:obj:`int`, optional): Limits the number of photos to be retrieved. Values
                between :tg-const:`telegram.constants.UserProfilePhotosLimit.MIN_LIMIT`-
                :tg-const:`telegram.constants.UserProfilePhotosLimit.MAX_LIMIT` are accepted.
                Defaults to ``100``.

        Returns:
            :class:`telegram.UserProfilePhotos`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"user_id": user_id, "offset": offset, "limit": limit}

        result = await self._post(
            "getUserProfilePhotos",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return UserProfilePhotos.de_json(result, self)

    async def get_file(
        self,
        file_id: (
            str
            | Animation
            | Audio
            | ChatPhoto
            | Document
            | PhotoSize
            | Sticker
            | Video
            | VideoNote
            | Voice
        ),
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> File:
        """
        Use this method to get basic info about a file and prepare it for downloading. For the
        moment, bots can download files of up to
        :tg-const:`telegram.constants.FileSizeLimit.FILESIZE_DOWNLOAD` in size. The file can then
        be e.g. downloaded with :meth:`telegram.File.download_to_drive`. It is guaranteed that
        the link will be valid for at least 1 hour. When the link expires, a new one can be
        requested by calling get_file again.

        Note:
            This function may not preserve the original file name and MIME type.
            You should save the file's MIME type and name (if available) when the File object
            is received.

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        Args:
            file_id (:obj:`str` | :class:`telegram.Animation` | :class:`telegram.Audio` |         \
                     :class:`telegram.ChatPhoto` | :class:`telegram.Document` |                   \
                     :class:`telegram.PhotoSize` | :class:`telegram.Sticker` |                    \
                     :class:`telegram.Video` | :class:`telegram.VideoNote` |                      \
                     :class:`telegram.Voice`):
                Either the file identifier or an object that has a file_id attribute
                to get file information about.

        Returns:
            :class:`telegram.File`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        # Try to get the file_id from the object, if it fails, assume it's a string
        with contextlib.suppress(AttributeError):
            file_id = file_id.file_id  # type: ignore[union-attr]

        data: JSONDict = {"file_id": file_id}

        result = await self._post(
            "getFile",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        file_path = cast("dict", result).get("file_path")
        if file_path and not is_local_file(file_path):
            result["file_path"] = f"{self._base_file_url}/{file_path}"

        return File.de_json(result, self)

    async def ban_chat_member(
        self,
        chat_id: str | int,
        user_id: int,
        until_date: int | dtm.datetime | None = None,
        revoke_messages: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to ban a user from a group, supergroup or a channel. In the case of
        supergroups and channels, the user will not be able to return to the group on their own
        using invite links, etc., unless unbanned first. The bot must be an administrator in the
        chat for this to work and must have the appropriate admin rights.

        .. versionadded:: 13.7

        Args:
            chat_id (:obj:`int` | :obj:`str`): Unique identifier for the target group or username
                of the target supergroup or channel (in the format ``@channelusername``).
            user_id (:obj:`int`): Unique identifier of the target user.
            until_date (:obj:`int` | :obj:`datetime.datetime`, optional): Date when the user will
                be unbanned, unix time. If user is banned for more than 366 days or less than 30
                seconds from the current time they are considered to be banned forever. Applied
                for supergroups and channels only.
                |tz-naive-dtms|
            revoke_messages (:obj:`bool`, optional): Pass :obj:`True` to delete all messages from
                the chat for the user that is being removed. If :obj:`False`, the user will be able
                to see messages in the group that were sent before the user was removed.
                Always :obj:`True` for supergroups and channels.

                .. versionadded:: 13.4

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "user_id": user_id,
            "revoke_messages": revoke_messages,
            "until_date": until_date,
        }

        return await self._post(
            "banChatMember",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def ban_chat_sender_chat(
        self,
        chat_id: str | int,
        sender_chat_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to ban a channel chat in a supergroup or a channel. Until the chat is
        unbanned, the owner of the banned chat won't be able to send messages on behalf of **any of
        their channels**. The bot must be an administrator in the supergroup or channel for this
        to work and must have the appropriate administrator rights.

        .. versionadded:: 13.9

        Args:
            chat_id (:obj:`int` | :obj:`str`): Unique identifier for the target group or username
                of the target supergroup or channel (in the format ``@channelusername``).
            sender_chat_id (:obj:`int`): Unique identifier of the target sender chat.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "sender_chat_id": sender_chat_id}

        return await self._post(
            "banChatSenderChat",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unban_chat_member(
        self,
        chat_id: str | int,
        user_id: int,
        only_if_banned: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to unban a previously kicked user in a supergroup or channel.

        The user will *not* return to the group or channel automatically, but will be able to join
        via link, etc. The bot must be an administrator for this to work. By default, this method
        guarantees that after the call the user is not a member of the chat, but will be able to
        join it. So if the user is a member of the chat they will also be *removed* from the chat.
        If you don't want this, use the parameter :paramref:`only_if_banned`.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            user_id (:obj:`int`): Unique identifier of the target user.
            only_if_banned (:obj:`bool`, optional): Do nothing if the user is not banned.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "user_id": user_id, "only_if_banned": only_if_banned}

        return await self._post(
            "unbanChatMember",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unban_chat_sender_chat(
        self,
        chat_id: str | int,
        sender_chat_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to unban a previously banned channel in a supergroup or channel.
        The bot must be an administrator for this to work and must have the
        appropriate administrator rights.

        .. versionadded:: 13.9

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            sender_chat_id (:obj:`int`): Unique identifier of the target sender chat.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "sender_chat_id": sender_chat_id}

        return await self._post(
            "unbanChatSenderChat",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool | None = None,
        url: str | None = None,
        cache_time: TimePeriod | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to send answers to callback queries sent from inline keyboards. The answer
        will be displayed to the user as a notification at the top of the chat screen or as an
        alert.
        Alternatively, the user can be redirected to the specified Game URL. For this option to
        work, you must first create a game for your bot via `@BotFather <https://t.me/BotFather>`_
        and accept the terms. Otherwise, you may use links like t.me/your_bot?start=XXXX that open
        your bot with a parameter.

        Args:
            callback_query_id (:obj:`str`): Unique identifier for the query to be answered.
            text (:obj:`str`, optional): Text of the notification. If not specified, nothing will
                be shown to the user, 0-:tg-const:`telegram.CallbackQuery.MAX_ANSWER_TEXT_LENGTH`
                characters.
            show_alert (:obj:`bool`, optional): If :obj:`True`, an alert will be shown by the
                client instead of a notification at the top of the chat screen. Defaults to
                :obj:`False`.
            url (:obj:`str`, optional): URL that will be opened by the user's client. If you have
                created a Game and accepted the conditions via
                `@BotFather <https://t.me/BotFather>`_, specify the URL that
                opens your game - note that this will only work if the query comes from a callback
                game button. Otherwise, you may use links like t.me/your_bot?start=XXXX that open
                your bot with a parameter.
            cache_time (:obj:`int` | :class:`datetime.timedelta`, optional): The maximum amount of
                time in seconds that the
                result of the callback query may be cached client-side. Defaults to 0.

                .. versionchanged:: 21.11
                    |time-period-input|

        Returns:
            :obj:`bool` On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "callback_query_id": callback_query_id,
            "cache_time": cache_time,
            "text": text,
            "show_alert": show_alert,
            "url": url,
        }

        return await self._post(
            "answerCallbackQuery",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_message_text(
        self,
        text: str,
        chat_id: str | int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        entities: Sequence["MessageEntity"] | None = None,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        business_connection_id: str | None = None,
        *,
        disable_web_page_preview: bool | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """
        Use this method to edit text and game messages.

        Note:
            * |editreplymarkup|
            * |bcid_edit_time|

        .. seealso:: :attr:`telegram.Game.text`

        Args:
            chat_id (:obj:`int` | :obj:`str`, optional): Required if :paramref:`inline_message_id`
                is not specified. |chat_id_channel|
            message_id (:obj:`int`, optional): Required if :paramref:`inline_message_id` is not
                specified. Identifier of the message to edit.
            inline_message_id (:obj:`str`, optional): Required if :paramref:`chat_id` and
                :paramref:`message_id` are not specified. Identifier of the inline message.
            text (:obj:`str`): New text of the message,
                :tg-const:`telegram.constants.MessageLimit.MIN_TEXT_LENGTH`-
                :tg-const:`telegram.constants.MessageLimit.MAX_TEXT_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`, optional): |parse_mode|
            entities (Sequence[:class:`telegram.MessageEntity`], optional): Sequence of special
                entities that appear in message text, which can be specified instead of
                :paramref:`parse_mode`.

                .. versionchanged:: 20.0
                    |sequenceargs|

            link_preview_options (:obj:`LinkPreviewOptions`, optional): Link preview generation
                options for the message. Mutually exclusive with
                :paramref:`disable_web_page_preview`.

                .. versionadded:: 20.8

            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for an
                inline keyboard.
            business_connection_id (:obj:`str`, optional): |business_id_str_edit|

                .. versionadded:: 21.4

        Keyword Args:
            disable_web_page_preview (:obj:`bool`, optional): Disables link previews for links in
                this message. Convenience parameter for setting :paramref:`link_preview_options`.
                Mutually exclusive with :paramref:`link_preview_options`.

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`link_preview_options` replacing this
                    argument. PTB will automatically convert this argument to that one, but
                    for advanced options, please use :paramref:`link_preview_options` directly.

                .. versionchanged:: 21.0
                    |keyword_only_arg|


        Returns:
            :class:`telegram.Message`: On success, if edited message is not an inline message, the
            edited message is returned, otherwise :obj:`True` is returned.

        Raises:
            :exc:`ValueError`: If both :paramref:`disable_web_page_preview` and
                :paramref:`link_preview_options` are passed.
            :class:`telegram.error.TelegramError`: For other errors.

        """
        data: JSONDict = {
            "text": text,
            "chat_id": chat_id,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
            "entities": entities,
        }

        link_preview_options = parse_lpo_and_dwpp(disable_web_page_preview, link_preview_options)

        return await self._send_message(
            "editMessageText",
            data,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            link_preview_options=link_preview_options,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_message_caption(
        self,
        chat_id: str | int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        caption: str | None = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        show_caption_above_media: bool | None = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """
        Use this method to edit captions of messages.

        Note:
            * |editreplymarkup|
            * |bcid_edit_time|

        Args:
            chat_id (:obj:`int` | :obj:`str`, optional): Required if inline_message_id is not
                specified. |chat_id_channel|
            message_id (:obj:`int`, optional): Required if inline_message_id is not specified.
                Identifier of the message to edit.
            inline_message_id (:obj:`str`, optional): Required if chat_id and message_id are not
                specified. Identifier of the inline message.
            caption (:obj:`str`, optional): New caption of the message,
                0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`, optional): |parse_mode|
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|

                .. versionchanged:: 20.0
                    |sequenceargs|
            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for an
                inline keyboard.
            show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|

                .. versionadded:: 21.3
            business_connection_id (:obj:`str`, optional): |business_id_str_edit|

                .. versionadded:: 21.4

        Returns:
            :class:`telegram.Message`: On success, if edited message is not an inline message, the
            edited message is returned, otherwise :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
            "show_caption_above_media": show_caption_above_media,
        }

        return await self._send_message(
            "editMessageCaption",
            data,
            reply_markup=reply_markup,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_message_media(
        self,
        media: "InputMedia",
        chat_id: str | int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """
        Use this method to edit animation, audio, document, photo, or video messages, or to add
        media to text messages. If a message
        is part of a message album, then it can be edited only to an audio for audio albums, only
        to a document for document albums and to a photo or a video otherwise. When an inline
        message is edited, a new file can't be uploaded; use a previously uploaded file via its
        :attr:`~telegram.File.file_id` or specify a URL.

        Note:
            * |editreplymarkup|
            * |bcid_edit_time|

        .. seealso:: :wiki:`Working with Files and Media <Working-with-Files-and-Media>`

        Args:
            media (:class:`telegram.InputMedia`): An object for a new media content
                of the message.
            chat_id (:obj:`int` | :obj:`str`, optional): Required if inline_message_id is not
                specified. |chat_id_channel|
            message_id (:obj:`int`, optional): Required if inline_message_id is not specified.
                Identifier of the message to edit.
            inline_message_id (:obj:`str`, optional): Required if chat_id and message_id are not
                specified. Identifier of the inline message.
            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for an
                inline keyboard.
            business_connection_id (:obj:`str`, optional): |business_id_str_edit|

                .. versionadded:: 21.4

        Returns:
            :class:`telegram.Message`: On success, if edited message is not an inline message, the
            edited Message is returned, otherwise :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "media": media,
            "chat_id": chat_id,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
        }

        return await self._send_message(
            "editMessageMedia",
            data,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_message_reply_markup(
        self,
        chat_id: str | int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """
        Use this method to edit only the reply markup of messages sent by the bot or via the bot
        (for inline bots).

        Note:
            * |editreplymarkup|
            * |bcid_edit_time|

        Args:
            chat_id (:obj:`int` | :obj:`str`, optional): Required if inline_message_id is not
                specified. |chat_id_channel|
            message_id (:obj:`int`, optional): Required if inline_message_id is not specified.
                Identifier of the message to edit.
            inline_message_id (:obj:`str`, optional): Required if chat_id and message_id are not
                specified. Identifier of the inline message.
            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for an
                inline keyboard.
            business_connection_id (:obj:`str`, optional): |business_id_str_edit|

                .. versionadded:: 21.4

        Returns:
            :class:`telegram.Message`: On success, if edited message is not an inline message, the
            edited message is returned, otherwise :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
        }

        return await self._send_message(
            "editMessageReplyMarkup",
            data,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_updates(
        self,
        offset: int | None = None,
        limit: int | None = None,
        timeout: TimePeriod | None = None,
        allowed_updates: Sequence[str] | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple[Update, ...]:
        """Use this method to receive incoming updates using long polling.

        Note:
            1. This method will not work if an outgoing webhook is set up.
            2. In order to avoid getting duplicate updates, recalculate offset after each
               server response.
            3. To take full advantage of this library take a look at :class:`telegram.ext.Updater`

        .. seealso:: :meth:`telegram.ext.Application.run_polling`,
            :meth:`telegram.ext.Updater.start_polling`

        .. versionchanged:: 20.0
            Returns a tuple instead of a list.

        Args:
            offset (:obj:`int`, optional): Identifier of the first update to be returned. Must be
                greater by one than the highest among the identifiers of previously received
                updates. By default, updates starting with the earliest unconfirmed update are
                returned. An update is considered confirmed as soon as this method is called with
                an offset higher than its :attr:`telegram.Update.update_id`. The negative offset
                can be specified to retrieve updates starting from -offset update from the end of
                the updates queue. All previous updates will be forgotten.
            limit (:obj:`int`, optional): Limits the number of updates to be retrieved. Values
                between :tg-const:`telegram.constants.PollingLimit.MIN_LIMIT`-
                :tg-const:`telegram.constants.PollingLimit.MAX_LIMIT` are accepted.
                Defaults to ``100``.
            timeout (:obj:`int` | :class:`datetime.timedelta`, optional): Timeout in seconds for
                long polling. Defaults to ``0``, i.e. usual short polling. Should be positive,
                short polling should be used for testing purposes only.

                .. versionchanged:: v22.2
                    |time-period-input|
            allowed_updates (Sequence[:obj:`str`]), optional): A sequence the types of
                updates you want your bot to receive. For example, specify ["message",
                "edited_channel_post", "callback_query"] to only receive updates of these types.
                See :class:`telegram.Update` for a complete list of available update types.
                Specify an empty sequence to receive all updates except
                :attr:`telegram.Update.chat_member`, :attr:`telegram.Update.message_reaction` and
                :attr:`telegram.Update.message_reaction_count` (default). If not specified, the
                previous setting will be used. Please note that this parameter doesn't affect
                updates created before the call to the get_updates, so unwanted updates may be
                received for a short period of time.

                .. versionchanged:: 20.0
                    |sequenceargs|

        Returns:
            tuple[:class:`telegram.Update`]

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "timeout": timeout,
            "offset": offset,
            "limit": limit,
            "allowed_updates": allowed_updates,
        }

        # The "or 0" is needed for the case where read_timeout is None.
        if not isinstance(read_timeout, DefaultValue):
            arg_read_timeout: float = read_timeout or 0
        else:
            arg_read_timeout = self._request[0].read_timeout or 0

        read_timeout = (
            (arg_read_timeout + timeout.total_seconds())
            if isinstance(timeout, dtm.timedelta)
            else (arg_read_timeout + timeout if timeout else arg_read_timeout)
        )

        # Ideally we'd use an aggressive read timeout for the polling. However,
        # * Short polling should return within 2 seconds.
        # * Long polling poses a different problem: the connection might have been dropped while
        #   waiting for the server to return and there's no way of knowing the connection had been
        #   dropped in real time.
        result = cast(
            "list[JSONDict]",
            await self._post(
                "getUpdates",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
        )

        if result:
            self._LOGGER.debug("Getting updates: %s", [u["update_id"] for u in result])
        else:
            self._LOGGER.debug("No new updates found.")

        try:
            return Update.de_list(result, self)
        except Exception as exc:
            # This logging is in place mostly b/c we can't access the raw json data in Updater,
            # where the exception is caught and logged again. Still, it might also be beneficial
            # for custom usages of `get_updates`.
            self._LOGGER.critical(
                "Error while parsing updates! Received data was %r", result, exc_info=exc
            )
            raise

    async def set_webhook(
        self,
        url: str,
        certificate: "FileInput | None" = None,
        max_connections: int | None = None,
        allowed_updates: Sequence[str] | None = None,
        ip_address: str | None = None,
        drop_pending_updates: bool | None = None,
        secret_token: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to specify a url and receive incoming updates via an outgoing webhook.
        Whenever there is an update for the bot, Telegram will send an HTTPS POST request to the
        specified url, containing An Update. In case of an unsuccessful request
        (a request with response
        `HTTP status code <https://en.wikipedia.org/wiki/List_of_HTTP_status_codes>`_different
        from ``2XY``),
        Telegram will repeat the request and give up after a reasonable amount of attempts.

        If you'd like to make sure that the Webhook was set by you, you can specify secret data in
        the parameter :paramref:`secret_token`. If specified, the request will contain a header
        ``X-Telegram-Bot-Api-Secret-Token`` with the secret token as content.

        Note:
            1. You will not be able to receive updates using :meth:`get_updates` for long as an
               outgoing webhook is set up.
            2. To use a self-signed certificate, you need to upload your public key certificate
               using :paramref:`certificate` parameter. Please upload as
               :class:`~telegram.InputFile`, sending a String will not work.
            3. Ports currently supported for Webhooks:
               :attr:`telegram.constants.SUPPORTED_WEBHOOK_PORTS`.

            If you're having any trouble setting up webhooks, please check out this `guide to
            Webhooks`_.

        .. seealso:: :meth:`telegram.ext.Application.run_webhook`,
            :meth:`telegram.ext.Updater.start_webhook`

        Examples:
            :any:`Custom Webhook Bot <examples.customwebhookbot>`

        Args:
            url (:obj:`str`): HTTPS url to send updates to. Use an empty string to remove webhook
                integration.
            certificate (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path` | :obj:`str`):
                Upload your public key certificate so that the root
                certificate in use can be checked. See our :wiki:`self-signed guide\
                <Webhooks#creating-a-self-signed-certificate-using-openssl>` for details.
                |uploadinputnopath|
            ip_address (:obj:`str`, optional): The fixed IP address which will be used to send
                webhook requests instead of the IP address resolved through DNS.
            max_connections (:obj:`int`, optional): Maximum allowed number of simultaneous HTTPS
                connections to the webhook for update delivery,
                :tg-const:`telegram.constants.WebhookLimit.MIN_CONNECTIONS_LIMIT`-
                :tg-const:`telegram.constants.WebhookLimit.MAX_CONNECTIONS_LIMIT`.
                Defaults to ``40``. Use lower values to limit the load on your bot's server,
                and higher values to increase your bot's throughput.
            allowed_updates (Sequence[:obj:`str`], optional): A sequence of the types of
                updates you want your bot to receive. For example, specify ["message",
                "edited_channel_post", "callback_query"] to only receive updates of these types.
                See :class:`telegram.Update` for a complete list of available update types.
                Specify an empty sequence to receive all updates except
                :attr:`telegram.Update.chat_member`,
                :attr:`telegram.Update.message_reaction`
                and :attr:`telegram.Update.message_reaction_count` (default). If not
                specified, the previous setting will be used. Please note that this
                parameter doesn't affect
                updates created before the call to the set_webhook, so unwanted update
                may be received for a short period of time.

                .. versionchanged:: 20.0
                    |sequenceargs|
            drop_pending_updates (:obj:`bool`, optional): Pass :obj:`True` to drop all pending
                updates.
            secret_token (:obj:`str`, optional): A secret token to be sent in a header
                ``X-Telegram-Bot-Api-Secret-Token`` in every webhook request,
                :tg-const:`telegram.constants.WebhookLimit.MIN_SECRET_TOKEN_LENGTH`-
                :tg-const:`telegram.constants.WebhookLimit.MAX_SECRET_TOKEN_LENGTH` characters.
                Only characters ``A-Z``, ``a-z``, ``0-9``, ``_`` and ``-`` are allowed.
                The header is useful to ensure that the request comes from a webhook set by you.

                .. versionadded:: 20.0

        Returns:
            :obj:`bool` On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        .. _`guide to Webhooks`: https://core.telegram.org/bots/webhooks

        """
        data: JSONDict = {
            "url": url,
            "max_connections": max_connections,
            "allowed_updates": allowed_updates,
            "ip_address": ip_address,
            "drop_pending_updates": drop_pending_updates,
            "secret_token": secret_token,
            "certificate": self._parse_file_input(certificate),  # type: ignore[arg-type]
        }

        return await self._post(
            "setWebhook",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_webhook(
        self,
        drop_pending_updates: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to remove webhook integration if you decide to switch back to
        :meth:`get_updates()`.

        Args:
            drop_pending_updates (:obj:`bool`, optional): Pass :obj:`True` to drop all pending
                updates.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data = {"drop_pending_updates": drop_pending_updates}

        return await self._post(
            "deleteWebhook",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def leave_chat(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method for your bot to leave a group, supergroup or channel.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}

        return await self._post(
            "leaveChat",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_chat(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ChatFullInfo:
        """
        Use this method to get up to date information about the chat (current name of the user for
        one-on-one conversations, current username of a user, group or channel, etc.).

        .. versionchanged:: 21.2
            In accordance to Bot API 7.3, this method now returns a :class:`telegram.ChatFullInfo`.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|

        Returns:
            :class:`telegram.ChatFullInfo`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}

        result = await self._post(
            "getChat",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return ChatFullInfo.de_json(result, self)

    async def get_chat_administrators(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple[ChatMember, ...]:
        """
        Use this method to get a list of administrators in a chat.

        .. versionchanged:: 20.0
            Returns a tuple instead of a list.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|

        Returns:
            tuple[:class:`telegram.ChatMember`]: On success, returns a tuple of ``ChatMember``
            objects that contains information about all chat administrators except
            other bots. If the chat is a group or a supergroup and no administrators were
            appointed, only the creator will be returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}
        result = await self._post(
            "getChatAdministrators",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return ChatMember.de_list(result, self)

    async def get_chat_member_count(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> int:
        """Use this method to get the number of members in a chat.

        .. versionadded:: 13.7

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|

        Returns:
            :obj:`int`: Number of members in the chat.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}
        return await self._post(
            "getChatMemberCount",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_chat_member(
        self,
        chat_id: str | int,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ChatMember:
        """Use this method to get information about a member of a chat. The method is only
        guaranteed to work for other users if the bot is an administrator in the chat.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            user_id (:obj:`int`): Unique identifier of the target user.

        Returns:
            :class:`telegram.ChatMember`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "user_id": user_id}
        result = await self._post(
            "getChatMember",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return ChatMember.de_json(result, self)

    async def set_chat_sticker_set(
        self,
        chat_id: str | int,
        sticker_set_name: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to set a new group sticker set for a supergroup.
        The bot must be an administrator in the chat for this to work and must have the appropriate
        admin rights. Use the field :attr:`telegram.ChatFullInfo.can_set_sticker_set` optionally
        returned in :meth:`get_chat` requests to check if the bot can use this method.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            sticker_set_name (:obj:`str`): Name of the sticker set to be set as the group
                sticker set.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.
        """
        data: JSONDict = {"chat_id": chat_id, "sticker_set_name": sticker_set_name}
        return await self._post(
            "setChatStickerSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_chat_sticker_set(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to delete a group sticker set from a supergroup. The bot must be an
        administrator in the chat for this to work and must have the appropriate admin rights.
        Use the field :attr:`telegram.ChatFullInfo.can_set_sticker_set` optionally returned in
        :meth:`get_chat` requests to check if the bot can use this method.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|

        Returns:
             :obj:`bool`: On success, :obj:`True` is returned.
        """
        data: JSONDict = {"chat_id": chat_id}
        return await self._post(
            "deleteChatStickerSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_webhook_info(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> WebhookInfo:
        """Use this method to get current webhook status. Requires no parameters.

        If the bot is using :meth:`get_updates`, will return an object with the
        :attr:`telegram.WebhookInfo.url` field empty.

        Returns:
            :class:`telegram.WebhookInfo`

        """
        result = await self._post(
            "getWebhookInfo",
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return WebhookInfo.de_json(result, self)

    async def set_game_score(
        self,
        user_id: int,
        score: int,
        chat_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        force: bool | None = None,
        disable_edit_message: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> "Message | bool":
        """
        Use this method to set the score of the specified user in a game message.

        .. seealso:: :attr:`telegram.Game.text`

        Args:
            user_id (:obj:`int`): User identifier.
            score (:obj:`int`): New score, must be non-negative.
            force (:obj:`bool`, optional): Pass :obj:`True`, if the high score is allowed to
                decrease. This can be useful when fixing mistakes or banning cheaters.
            disable_edit_message (:obj:`bool`, optional): Pass :obj:`True`, if the game message
                should not be automatically edited to include the current scoreboard.
            chat_id (:obj:`int`, optional): Required if :paramref:`inline_message_id`
                is not specified. Unique identifier for the target chat.
            message_id (:obj:`int`, optional): Required if :paramref:`inline_message_id` is not
                specified. Identifier of the sent message.
            inline_message_id (:obj:`str`, optional): Required if :paramref:`chat_id` and
                :paramref:`message_id` are not specified. Identifier of the inline message.

        Returns:
            :class:`telegram.Message`: The edited message. If the message is not an inline message
            , :obj:`True`.

        Raises:
            :class:`telegram.error.TelegramError`: If the new score is not greater than the user's
                current score in the chat and :paramref:`force` is :obj:`False`.

        """
        data: JSONDict = {
            "user_id": user_id,
            "score": score,
            "force": force,
            "disable_edit_message": disable_edit_message,
            "chat_id": chat_id,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
        }

        return await self._send_message(
            "setGameScore",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_game_high_scores(
        self,
        user_id: int,
        chat_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple[GameHighScore, ...]:
        """
        Use this method to get data for high score tables. Will return the score of the specified
        user and several of their neighbors in a game.

        Note:
            This method will currently return scores for the target user, plus two of their
            closest neighbors on each side. Will also return the top three users if the user and
            his neighbors are not among them. Please note that this behavior is subject to change.

        .. versionchanged:: 20.0
            Returns a tuple instead of a list.

        Args:
            user_id (:obj:`int`): Target user id.
            chat_id (:obj:`int`, optional): Required if :paramref:`inline_message_id`
                is not specified. Unique identifier for the target chat.
            message_id (:obj:`int`, optional): Required if :paramref:`inline_message_id` is not
                specified. Identifier of the sent message.
            inline_message_id (:obj:`str`, optional): Required if :paramref:`chat_id` and
                :paramref:`message_id` are not specified. Identifier of the inline message.

        Returns:
            tuple[:class:`telegram.GameHighScore`]

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
        }

        result = await self._post(
            "getGameHighScores",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return GameHighScore.de_list(result, self)

    async def send_invoice(
        self,
        chat_id: int | str,
        title: str,
        description: str,
        payload: str,
        currency: str,
        prices: Sequence["LabeledPrice"],
        provider_token: str | None = None,
        start_parameter: str | None = None,
        photo_url: str | None = None,
        photo_size: int | None = None,
        photo_width: int | None = None,
        photo_height: int | None = None,
        need_name: bool | None = None,
        need_phone_number: bool | None = None,
        need_email: bool | None = None,
        need_shipping_address: bool | None = None,
        is_flexible: bool | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        provider_data: str | object | None = None,
        send_phone_number_to_provider: bool | None = None,
        send_email_to_provider: bool | None = None,
        max_tip_amount: int | None = None,
        suggested_tip_amounts: Sequence[int] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send invoices.

        Warning:
            As of API 5.2 :paramref:`start_parameter` is an optional argument and therefore the
            order of the arguments had to be changed. Use keyword arguments to make sure that the
            arguments are passed correctly.

        .. versionchanged:: 13.5
            As of Bot API 5.2, the parameter :paramref:`start_parameter` is optional.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            title (:obj:`str`): Product name. :tg-const:`telegram.Invoice.MIN_TITLE_LENGTH`-
                :tg-const:`telegram.Invoice.MAX_TITLE_LENGTH` characters.
            description (:obj:`str`): Product description.
                :tg-const:`telegram.Invoice.MIN_DESCRIPTION_LENGTH`-
                :tg-const:`telegram.Invoice.MAX_DESCRIPTION_LENGTH` characters.
            payload (:obj:`str`): Bot-defined invoice payload.
                :tg-const:`telegram.Invoice.MIN_PAYLOAD_LENGTH`-
                :tg-const:`telegram.Invoice.MAX_PAYLOAD_LENGTH` bytes. This will not be
                displayed to the user, use it for your internal processes.
            provider_token (:obj:`str`, optional): Payments provider token, obtained via
                `@BotFather <https://t.me/BotFather>`_. Pass an empty string for payments in
                |tg_stars|.

                .. versionchanged:: 21.11
                    Bot API 7.4 made this parameter is optional and this is now reflected in the
                    function signature.

            currency (:obj:`str`): Three-letter ISO 4217 currency code, see `more on currencies
                <https://core.telegram.org/bots/payments#supported-currencies>`_. Pass ``XTR`` for
                payment in |tg_stars|.
            prices (Sequence[:class:`telegram.LabeledPrice`]): Price breakdown, a sequence
                of components (e.g. product price, tax, discount, delivery cost, delivery tax,
                bonus, etc.). Must contain exactly one item for payment in |tg_stars|.

                .. versionchanged:: 20.0
                    |sequenceargs|
            max_tip_amount (:obj:`int`, optional): The maximum accepted amount for tips in the
                *smallest units* of the currency (integer, **not** float/double). For example, for
                a maximum tip of ``US$ 1.45`` pass ``max_tip_amount = 145``. See the ``exp``
                parameter in `currencies.json
                <https://core.telegram.org/bots/payments/currencies.json>`_, it shows the number of
                digits past the decimal point for each currency (2 for the majority of currencies).
                Defaults to ``0``. Not supported for payment in |tg_stars|.

                .. versionadded:: 13.5
            suggested_tip_amounts (Sequence[:obj:`int`], optional): An array of
                suggested amounts of tips in the *smallest units* of the currency (integer, **not**
                float/double). At most :tg-const:`telegram.Invoice.MAX_TIP_AMOUNTS` suggested tip
                amounts can be specified. The suggested tip amounts must be positive, passed in a
                strictly increased order and must not exceed :paramref:`max_tip_amount`.

                .. versionadded:: 13.5

                .. versionchanged:: 20.0
                    |sequenceargs|
            start_parameter (:obj:`str`, optional): Unique deep-linking parameter. If left empty,
                *forwarded copies* of the sent message will have a *Pay* button, allowing
                multiple users to pay directly from the forwarded message, using the same invoice.
                If non-empty, forwarded copies of the sent message will have a *URL* button with a
                deep link to the bot (instead of a *Pay* button), with the value used as the
                start parameter.

                .. versionchanged:: 13.5
                    As of Bot API 5.2, this parameter is optional.
            provider_data (:obj:`str` | :obj:`object`, optional): data about the
                invoice, which will be shared with the payment provider. A detailed description of
                required fields should be provided by the payment provider. When an object is
                passed, it will be encoded as JSON.
            photo_url (:obj:`str`, optional): URL of the product photo for the invoice. Can be a
                photo of the goods or a marketing image for a service. People like it better when
                they see what they are paying for.
            photo_size (:obj:`str`, optional): Photo size.
            photo_width (:obj:`int`, optional): Photo width.
            photo_height (:obj:`int`, optional): Photo height.
            need_name (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's full
                name to complete the order. Ignored for payments in |tg_stars|.
            need_phone_number (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's
                phone number to complete the order. Ignored for payments in |tg_stars|.
            need_email (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's email
                to complete the order. Ignored for payments in |tg_stars|.
            need_shipping_address (:obj:`bool`, optional): Pass :obj:`True`, if you require the
                user's shipping address to complete the order. Ignored for payments in
                |tg_stars|.
            send_phone_number_to_provider (:obj:`bool`, optional): Pass :obj:`True`, if user's
                phone number should be sent to provider. Ignored for payments in |tg_stars|.
            send_email_to_provider (:obj:`bool`, optional): Pass :obj:`True`, if user's email
                address should be sent to provider. Ignored for payments in |tg_stars|.
            is_flexible (:obj:`bool`, optional): Pass :obj:`True`, if the final price depends on
                the shipping method. Ignored for payments in |tg_stars|.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for an
                inline keyboard. If empty, one 'Pay total price' button will be
                shown. If not empty, the first button must be a Pay button.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "title": title,
            "description": description,
            "payload": payload,
            "provider_token": provider_token,
            "currency": currency,
            "prices": prices,
            "max_tip_amount": max_tip_amount,
            "suggested_tip_amounts": suggested_tip_amounts,
            "start_parameter": start_parameter,
            "provider_data": provider_data,
            "photo_url": photo_url,
            "photo_size": photo_size,
            "photo_width": photo_width,
            "photo_height": photo_height,
            "need_name": need_name,
            "need_phone_number": need_phone_number,
            "need_email": need_email,
            "need_shipping_address": need_shipping_address,
            "is_flexible": is_flexible,
            "send_phone_number_to_provider": send_phone_number_to_provider,
            "send_email_to_provider": send_email_to_provider,
        }

        return await self._send_message(
            "sendInvoice",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def answer_shipping_query(
        self,
        shipping_query_id: str,
        ok: bool,
        shipping_options: Sequence["ShippingOption"] | None = None,
        error_message: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        If you sent an invoice requesting a shipping address and the parameter
        :paramref:`send_invoice.is_flexible` was specified, the Bot API will send an
        :class:`telegram.Update` with a :attr:`telegram.Update.shipping_query` field to the bot.
        Use this method to reply to shipping queries.

        Args:
            shipping_query_id (:obj:`str`): Unique identifier for the query to be answered.
            ok (:obj:`bool`): Specify :obj:`True` if delivery to the specified address is possible
                and :obj:`False` if there are any problems (for example, if delivery to the
                specified address is not possible).
            shipping_options (Sequence[:class:`telegram.ShippingOption`]), optional): Required if
                :paramref:`ok` is :obj:`True`. A sequence of available shipping options.

                .. versionchanged:: 20.0
                    |sequenceargs|
            error_message (:obj:`str`, optional): Required if :paramref:`ok` is :obj:`False`.
                Error message in human readable form that explains why it is impossible to complete
                the order (e.g. "Sorry, delivery to your desired address is unavailable"). Telegram
                will display this message to the user.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "shipping_query_id": shipping_query_id,
            "ok": ok,
            "shipping_options": shipping_options,
            "error_message": error_message,
        }

        return await self._post(
            "answerShippingQuery",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def answer_pre_checkout_query(
        self,
        pre_checkout_query_id: str,
        ok: bool,
        error_message: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Once the user has confirmed their payment and shipping details, the Bot API sends the final
        confirmation in the form of an :class:`telegram.Update` with the field
        :attr:`telegram.Update.pre_checkout_query`. Use this method to respond to such pre-checkout
        queries.

        Note:
            The Bot API must receive an answer within 10 seconds after the pre-checkout
            query was sent.

        Args:
            pre_checkout_query_id (:obj:`str`): Unique identifier for the query to be answered.
            ok (:obj:`bool`): Specify :obj:`True` if everything is alright
                (goods are available, etc.) and the bot is ready to proceed with the order. Use
                :obj:`False` if there are any problems.
            error_message (:obj:`str`, optional): Required if :paramref:`ok` is :obj:`False`. Error
                message in human readable form that explains the reason for failure to proceed with
                the checkout (e.g. "Sorry, somebody just bought the last of our amazing black
                T-shirts while you were busy filling out your payment details. Please choose a
                different color or garment!"). Telegram will display this message to the user.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "pre_checkout_query_id": pre_checkout_query_id,
            "ok": ok,
            "error_message": error_message,
        }

        return await self._post(
            "answerPreCheckoutQuery",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def answer_web_app_query(
        self,
        web_app_query_id: str,
        result: "InlineQueryResult",
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> SentWebAppMessage:
        """Use this method to set the result of an interaction with a Web App and send a
        corresponding message on behalf of the user to the chat from which the query originated.

        .. versionadded:: 20.0

        Args:
            web_app_query_id (:obj:`str`): Unique identifier for the query to be answered.
            result (:class:`telegram.InlineQueryResult`): An object describing the message to be
                sent.

        Returns:
            :class:`telegram.SentWebAppMessage`: On success, a sent
            :class:`telegram.SentWebAppMessage` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "web_app_query_id": web_app_query_id,
            "result": self._insert_defaults_for_ilq_results(result),
        }

        api_result = await self._post(
            "answerWebAppQuery",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return SentWebAppMessage.de_json(api_result, self)

    async def restrict_chat_member(
        self,
        chat_id: str | int,
        user_id: int,
        permissions: ChatPermissions,
        until_date: int | dtm.datetime | None = None,
        use_independent_chat_permissions: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to restrict a user in a supergroup. The bot must be an administrator in
        the supergroup for this to work and must have the appropriate admin rights. Pass
        :obj:`True` for all boolean parameters to lift restrictions from a user.

        .. seealso:: :meth:`telegram.ChatPermissions.all_permissions`

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            user_id (:obj:`int`): Unique identifier of the target user.
            until_date (:obj:`int` | :obj:`datetime.datetime`, optional): Date when restrictions
                will be lifted for the user, unix time. If user is restricted for more than 366
                days or less than 30 seconds from the current time, they are considered to be
                restricted forever.
                |tz-naive-dtms|
            permissions (:class:`telegram.ChatPermissions`): An object for new user
                permissions.
            use_independent_chat_permissions (:obj:`bool`, optional): Pass :obj:`True` if chat
                permissions are set independently. Otherwise, the
                :attr:`~telegram.ChatPermissions.can_send_other_messages` and
                :attr:`~telegram.ChatPermissions.can_add_web_page_previews` permissions will imply
                the :attr:`~telegram.ChatPermissions.can_send_messages`,
                :attr:`~telegram.ChatPermissions.can_send_audios`,
                :attr:`~telegram.ChatPermissions.can_send_documents`,
                :attr:`~telegram.ChatPermissions.can_send_photos`,
                :attr:`~telegram.ChatPermissions.can_send_videos`,
                :attr:`~telegram.ChatPermissions.can_send_video_notes`, and
                :attr:`~telegram.ChatPermissions.can_send_voice_notes` permissions; the
                :attr:`~telegram.ChatPermissions.can_send_polls` permission will imply the
                :attr:`~telegram.ChatPermissions.can_send_messages` permission.

                .. versionadded: 20.1

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "chat_id": chat_id,
            "user_id": user_id,
            "permissions": permissions,
            "until_date": until_date,
            "use_independent_chat_permissions": use_independent_chat_permissions,
        }

        return await self._post(
            "restrictChatMember",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def promote_chat_member(
        self,
        chat_id: str | int,
        user_id: int,
        can_change_info: bool | None = None,
        can_post_messages: bool | None = None,
        can_edit_messages: bool | None = None,
        can_delete_messages: bool | None = None,
        can_invite_users: bool | None = None,
        can_restrict_members: bool | None = None,
        can_pin_messages: bool | None = None,
        can_promote_members: bool | None = None,
        is_anonymous: bool | None = None,
        can_manage_chat: bool | None = None,
        can_manage_video_chats: bool | None = None,
        can_manage_topics: bool | None = None,
        can_post_stories: bool | None = None,
        can_edit_stories: bool | None = None,
        can_delete_stories: bool | None = None,
        can_manage_direct_messages: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to promote or demote a user in a supergroup or a channel. The bot must be
        an administrator in the chat for this to work and must have the appropriate admin rights.
        Pass :obj:`False` for all boolean parameters to demote a user.

        .. versionchanged:: 20.0
           The argument ``can_manage_voice_chats`` was renamed to
           :paramref:`can_manage_video_chats` in accordance to Bot API 6.0.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            user_id (:obj:`int`): Unique identifier of the target user.
            is_anonymous (:obj:`bool`, optional): Pass :obj:`True`, if the administrator's presence
                in the chat is hidden.
            can_manage_chat (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                access the chat event log, get boost list, see hidden supergroup and channel
                members, report spam messages and ignore slow mode. Implied by any other
                administrator privilege.

                .. versionadded:: 13.4

            can_manage_video_chats (:obj:`bool`, optional): Pass :obj:`True`, if the administrator
                can manage video chats.

                .. versionadded:: 20.0

            can_change_info (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                change chat title, photo and other settings.
            can_post_messages (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                post messages in the channel, or access channel statistics; for channels only.
            can_edit_messages (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                edit messages of other users and can pin messages, for channels only.
            can_delete_messages (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                delete messages of other users.
            can_invite_users (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                invite new users to the chat.
            can_restrict_members (:obj:`bool`, optional): Pass :obj:`True`, if the administrator
                can restrict, ban or unban chat members, or access supergroup statistics. For
                backward compatibility, defaults to :obj:`True` for promotions of channel
                administrators.
            can_pin_messages (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                pin messages, for supergroups only.
            can_promote_members (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                add new administrators with a subset of their own privileges or demote
                administrators that they have promoted, directly or indirectly
                (promoted by administrators that were appointed by the user).
            can_manage_topics (:obj:`bool`, optional): Pass :obj:`True`, if the user is
                allowed to create, rename, close, and reopen forum topics; for supergroups only.

                .. versionadded:: 20.0
            can_post_stories (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                post stories to the chat.

                .. versionadded:: 20.6
            can_edit_stories (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                edit stories posted by other users, post stories to the chat page, pin chat
                stories, and access the chat's story archive

                .. versionadded:: 20.6
            can_delete_stories (:obj:`bool`, optional): Pass :obj:`True`, if the administrator can
                delete stories posted by other users.

                .. versionadded:: 20.6
            can_manage_direct_messages (:obj:`bool`, optional): Pass :obj:`True`, if the
                administrator can manage direct messages within the channel and decline suggested
                posts; for channels only

                .. versionadded:: 22.4

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "user_id": user_id,
            "is_anonymous": is_anonymous,
            "can_change_info": can_change_info,
            "can_post_messages": can_post_messages,
            "can_edit_messages": can_edit_messages,
            "can_delete_messages": can_delete_messages,
            "can_invite_users": can_invite_users,
            "can_restrict_members": can_restrict_members,
            "can_pin_messages": can_pin_messages,
            "can_promote_members": can_promote_members,
            "can_manage_chat": can_manage_chat,
            "can_manage_video_chats": can_manage_video_chats,
            "can_manage_topics": can_manage_topics,
            "can_post_stories": can_post_stories,
            "can_edit_stories": can_edit_stories,
            "can_delete_stories": can_delete_stories,
            "can_manage_direct_messages": can_manage_direct_messages,
        }

        return await self._post(
            "promoteChatMember",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_chat_permissions(
        self,
        chat_id: str | int,
        permissions: ChatPermissions,
        use_independent_chat_permissions: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to set default chat permissions for all members. The bot must be an
        administrator in the group or a supergroup for this to work and must have the
        :attr:`telegram.ChatMemberAdministrator.can_restrict_members` admin rights.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            permissions (:class:`telegram.ChatPermissions`): New default chat permissions.
            use_independent_chat_permissions (:obj:`bool`, optional): Pass :obj:`True` if chat
                permissions are set independently. Otherwise, the
                :attr:`~telegram.ChatPermissions.can_send_other_messages` and
                :attr:`~telegram.ChatPermissions.can_add_web_page_previews` permissions will imply
                the :attr:`~telegram.ChatPermissions.can_send_messages`,
                :attr:`~telegram.ChatPermissions.can_send_audios`,
                :attr:`~telegram.ChatPermissions.can_send_documents`,
                :attr:`~telegram.ChatPermissions.can_send_photos`,
                :attr:`~telegram.ChatPermissions.can_send_videos`,
                :attr:`~telegram.ChatPermissions.can_send_video_notes`, and
                :attr:`~telegram.ChatPermissions.can_send_voice_notes` permissions; the
                :attr:`~telegram.ChatPermissions.can_send_polls` permission will imply the
                :attr:`~telegram.ChatPermissions.can_send_messages` permission.

                .. versionadded: 20.1

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "permissions": permissions,
            "use_independent_chat_permissions": use_independent_chat_permissions,
        }
        return await self._post(
            "setChatPermissions",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_chat_administrator_custom_title(
        self,
        chat_id: int | str,
        user_id: int,
        custom_title: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to set a custom title for administrators promoted by the bot in a
        supergroup. The bot must be an administrator for this to work.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            user_id (:obj:`int`): Unique identifier of the target administrator.
            custom_title (:obj:`str`): New custom title for the administrator;
                0-:tg-const:`telegram.constants.ChatLimit.CHAT_ADMINISTRATOR_CUSTOM_TITLE_LENGTH`
                characters, emoji are not allowed.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "user_id": user_id, "custom_title": custom_title}

        return await self._post(
            "setChatAdministratorCustomTitle",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def export_chat_invite_link(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> str:
        """
        Use this method to generate a new primary invite link for a chat; any previously generated
        link is revoked. The bot must be an administrator in the chat for this to work and must
        have the appropriate admin rights.

        Note:
            Each administrator in a chat generates their own invite links. Bots can't use invite
            links generated by other administrators. If you want your bot to work with invite
            links, it will need to generate its own link using :meth:`export_chat_invite_link` or
            by calling the :meth:`get_chat` method. If your bot needs to generate a new primary
            invite link replacing its previous one, use :meth:`export_chat_invite_link` again.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|

        Returns:
            :obj:`str`: New invite link on success.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}
        return await self._post(
            "exportChatInviteLink",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def create_chat_invite_link(
        self,
        chat_id: str | int,
        expire_date: int | dtm.datetime | None = None,
        member_limit: int | None = None,
        name: str | None = None,
        creates_join_request: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ChatInviteLink:
        """
        Use this method to create an additional invite link for a chat. The bot must be an
        administrator in the chat for this to work and must have the appropriate admin rights.
        The link can be revoked using the method :meth:`revoke_chat_invite_link`.

        Note:
            When joining *public* groups via an invite link, Telegram clients may display the
            usual "Join" button, effectively ignoring the invite link. In particular, the parameter
            :paramref:`creates_join_request` has no effect in this case.
            However, this behavior is undocument and may be subject to change.
            See `this GitHub thread <https://github.com/tdlib/telegram-bot-api/issues/429>`_
            for some discussion.

        .. versionadded:: 13.4

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            expire_date (:obj:`int` | :obj:`datetime.datetime`, optional): Date when the link will
                expire. Integer input will be interpreted as Unix timestamp.
                |tz-naive-dtms|
            member_limit (:obj:`int`, optional): Maximum number of users that can be members of
                the chat simultaneously after joining the chat via this invite link;
                :tg-const:`telegram.constants.ChatInviteLinkLimit.MIN_MEMBER_LIMIT`-
                :tg-const:`telegram.constants.ChatInviteLinkLimit.MAX_MEMBER_LIMIT`.
            name (:obj:`str`, optional): Invite link name;
                0-:tg-const:`telegram.constants.ChatInviteLinkLimit.NAME_LENGTH` characters.

                .. versionadded:: 13.8
            creates_join_request (:obj:`bool`, optional): :obj:`True`, if users joining the chat
                via the link need to be approved by chat administrators.
                If :obj:`True`, :paramref:`member_limit` can't be specified.

                .. versionadded:: 13.8

        Returns:
            :class:`telegram.ChatInviteLink`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "expire_date": expire_date,
            "member_limit": member_limit,
            "name": name,
            "creates_join_request": creates_join_request,
        }

        result = await self._post(
            "createChatInviteLink",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return ChatInviteLink.de_json(result, self)

    async def edit_chat_invite_link(
        self,
        chat_id: str | int,
        invite_link: "str | ChatInviteLink",
        expire_date: int | dtm.datetime | None = None,
        member_limit: int | None = None,
        name: str | None = None,
        creates_join_request: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ChatInviteLink:
        """
        Use this method to edit a non-primary invite link created by the bot. The bot must be an
        administrator in the chat for this to work and must have the appropriate admin rights.

        Note:
            Though not stated explicitly in the official docs, Telegram changes not only the
            optional parameters that are explicitly passed, but also replaces all other optional
            parameters to the default values. However, since not documented, this behaviour may
            change unbeknown to PTB.

        .. versionadded:: 13.4

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            invite_link (:obj:`str` | :class:`telegram.ChatInviteLink`): The invite link to edit.

                .. versionchanged:: 20.0
                    Now also accepts :class:`telegram.ChatInviteLink` instances.
            expire_date (:obj:`int` | :obj:`datetime.datetime`, optional): Date when the link will
                expire.
                |tz-naive-dtms|
            member_limit (:obj:`int`, optional): Maximum number of users that can be members of
                the chat simultaneously after joining the chat via this invite link;
                :tg-const:`telegram.constants.ChatInviteLinkLimit.MIN_MEMBER_LIMIT`-
                :tg-const:`telegram.constants.ChatInviteLinkLimit.MAX_MEMBER_LIMIT`.
            name (:obj:`str`, optional): Invite link name;
                0-:tg-const:`telegram.constants.ChatInviteLinkLimit.NAME_LENGTH` characters.

                .. versionadded:: 13.8
            creates_join_request (:obj:`bool`, optional): :obj:`True`, if users joining the chat
                via the link need to be approved by chat administrators.
                If :obj:`True`, :paramref:`member_limit` can't be specified.

                .. versionadded:: 13.8

        Returns:
            :class:`telegram.ChatInviteLink`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        link = invite_link.invite_link if isinstance(invite_link, ChatInviteLink) else invite_link
        data: JSONDict = {
            "chat_id": chat_id,
            "invite_link": link,
            "expire_date": expire_date,
            "member_limit": member_limit,
            "name": name,
            "creates_join_request": creates_join_request,
        }

        result = await self._post(
            "editChatInviteLink",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return ChatInviteLink.de_json(result, self)

    async def revoke_chat_invite_link(
        self,
        chat_id: str | int,
        invite_link: "str | ChatInviteLink",
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ChatInviteLink:
        """
        Use this method to revoke an invite link created by the bot. If the primary link is
        revoked, a new link is automatically generated. The bot must be an administrator in the
        chat for this to work and must have the appropriate admin rights.

        .. versionadded:: 13.4

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            invite_link (:obj:`str` | :class:`telegram.ChatInviteLink`): The invite link to revoke.

                .. versionchanged:: 20.0
                    Now also accepts :class:`telegram.ChatInviteLink` instances.

        Returns:
            :class:`telegram.ChatInviteLink`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        link = invite_link.invite_link if isinstance(invite_link, ChatInviteLink) else invite_link
        data: JSONDict = {"chat_id": chat_id, "invite_link": link}

        result = await self._post(
            "revokeChatInviteLink",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return ChatInviteLink.de_json(result, self)

    async def approve_chat_join_request(
        self,
        chat_id: str | int,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to approve a chat join request.

        The bot must be an administrator in the chat for this to work and must have the
        :attr:`telegram.ChatPermissions.can_invite_users` administrator right.

        .. versionadded:: 13.8

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            user_id (:obj:`int`): Unique identifier of the target user.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"chat_id": chat_id, "user_id": user_id}

        return await self._post(
            "approveChatJoinRequest",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def decline_chat_join_request(
        self,
        chat_id: str | int,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to decline a chat join request.

        The bot must be an administrator in the chat for this to work and must have the
        :attr:`telegram.ChatPermissions.can_invite_users` administrator right.

        .. versionadded:: 13.8

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            user_id (:obj:`int`): Unique identifier of the target user.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"chat_id": chat_id, "user_id": user_id}

        return await self._post(
            "declineChatJoinRequest",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_chat_photo(
        self,
        chat_id: str | int,
        photo: FileInput,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to set a new profile photo for the chat.

        Photos can't be changed for private chats. The bot must be an administrator in the chat
        for this to work and must have the appropriate admin rights.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            photo (:term:`file object` | :obj:`bytes` | :class:`pathlib.Path`): New chat photo.
                |uploadinput|

                .. versionchanged:: 13.2
                   Accept :obj:`bytes` as input.

                .. versionchanged:: 20.0
                    File paths as input is also accepted for bots *not* running in
                    :paramref:`~telegram.Bot.local_mode`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "photo": self._parse_file_input(photo)}
        return await self._post(
            "setChatPhoto",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_chat_photo(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to delete a chat photo. Photos can't be changed for private chats. The bot
        must be an administrator in the chat for this to work and must have the appropriate admin
        rights.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}
        return await self._post(
            "deleteChatPhoto",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_chat_title(
        self,
        chat_id: str | int,
        title: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the title of a chat. Titles can't be changed for private chats.
        The bot must be an administrator in the chat for this to work and must have the appropriate
        admin rights.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            title (:obj:`str`): New chat title,
                :tg-const:`telegram.constants.ChatLimit.MIN_CHAT_TITLE_LENGTH`-
                :tg-const:`telegram.constants.ChatLimit.MAX_CHAT_TITLE_LENGTH` characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "title": title}
        return await self._post(
            "setChatTitle",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_chat_description(
        self,
        chat_id: str | int,
        description: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the description of a group, a supergroup or a channel. The bot
        must be an administrator in the chat for this to work and must have the appropriate admin
        rights.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            description (:obj:`str`, optional): New chat description,
                0-:tg-const:`telegram.constants.ChatLimit.CHAT_DESCRIPTION_LENGTH`
                characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "description": description}

        return await self._post(
            "setChatDescription",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_user_emoji_status(
        self,
        user_id: int,
        emoji_status_custom_emoji_id: str | None = None,
        emoji_status_expiration_date: int | dtm.datetime | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Changes the emoji status for a given user that previously allowed the bot to manage
        their emoji status via the Mini App method
        `requestEmojiStatusAccess <https://core.telegram.org/bots/webapps#initializing-mini-apps>`_
        .

        .. versionadded:: 21.8

        Args:
            user_id (:obj:`int`): Unique identifier of the target user
            emoji_status_custom_emoji_id (:obj:`str`, optional): Custom emoji identifier of the
                emoji status to set. Pass an empty string to remove the status.
            emoji_status_expiration_date (:obj:`int` | :obj:`datetime.datetime`, optional):
                Expiration date of the emoji status, if any, as unix timestamp or
                :class:`datetime.datetime` object.
                |tz-naive-dtms|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "user_id": user_id,
            "emoji_status_custom_emoji_id": emoji_status_custom_emoji_id,
            "emoji_status_expiration_date": emoji_status_expiration_date,
        }
        return await self._post(
            "setUserEmojiStatus",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def pin_chat_message(
        self,
        chat_id: str | int,
        message_id: int,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to add a message to the list of pinned messages in a chat. If the
        chat is not a private chat, the bot must be an administrator in the chat for this to work
        and must have the :paramref:`~telegram.ChatAdministratorRights.can_pin_messages` admin
        right in a supergroup or :attr:`~telegram.ChatMemberAdministrator.can_edit_messages` admin
        right in a channel.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            message_id (:obj:`int`): Identifier of a message to pin.
            disable_notification (:obj:`bool`, optional): Pass :obj:`True`, if it is not necessary
                to send a notification to all chat members about the new pinned message.
                Notifications are always disabled in channels and private chats.
            business_connection_id (:obj:`str`, optional): Unique identifier of the business
                connection on behalf of which the message will be pinned.

                .. versionadded:: 21.5

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": disable_notification,
            "business_connection_id": business_connection_id,
        }

        return await self._post(
            "pinChatMessage",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin_chat_message(
        self,
        chat_id: str | int,
        message_id: int | None = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to remove a message from the list of pinned messages in a chat. If the
        chat is not a private chat, the bot must be an administrator in the chat for this to work
        and must have the :paramref:`~telegram.ChatAdministratorRights.can_pin_messages` admin
        right in a supergroup or :attr:`~telegram.ChatMemberAdministrator.can_edit_messages` admin
        right in a channel.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            message_id (:obj:`int`, optional): Identifier of the message to unpin. Required if
                :paramref:`business_connection_id` is specified. If not specified,
                the most recent pinned message (by sending date) will be unpinned.
            business_connection_id (:obj:`str`, optional): Unique identifier of the business
                connection on behalf of which the message will be unpinned.

                .. versionadded:: 21.5

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "business_connection_id": business_connection_id,
        }

        return await self._post(
            "unpinChatMessage",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin_all_chat_messages(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to clear the list of pinned messages in a chat. If the
        chat is not a private chat, the bot must be an administrator in the chat for this
        to work and must have the :paramref:`~telegram.ChatAdministratorRights.can_pin_messages`
        admin right in a supergroup or :attr:`~telegram.ChatMemberAdministrator.can_edit_messages`
        admin right in a channel.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}
        return await self._post(
            "unpinAllChatMessages",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_sticker_set(
        self,
        name: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> StickerSet:
        """Use this method to get a sticker set.

        Args:
            name (:obj:`str`): Name of the sticker set.

        Returns:
            :class:`telegram.StickerSet`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"name": name}
        result = await self._post(
            "getStickerSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return StickerSet.de_json(result, self)

    async def get_custom_emoji_stickers(
        self,
        custom_emoji_ids: Sequence[str],
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple[Sticker, ...]:
        """
        Use this method to get information about emoji stickers by their identifiers.

        .. versionchanged:: 20.0
            Returns a tuple instead of a list.

        Args:
            custom_emoji_ids (Sequence[:obj:`str`]): Sequence of custom emoji identifiers.
                At most :tg-const:`telegram.constants.CustomEmojiStickerLimit.\
CUSTOM_EMOJI_IDENTIFIER_LIMIT` custom emoji identifiers can be specified.

                .. versionchanged:: 20.0
                    |sequenceargs|

        Returns:
            tuple[:class:`telegram.Sticker`]

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"custom_emoji_ids": custom_emoji_ids}
        result = await self._post(
            "getCustomEmojiStickers",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return Sticker.de_list(result, self)

    async def upload_sticker_file(
        self,
        user_id: int,
        sticker: FileInput,
        sticker_format: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> File:
        """
        Use this method to upload a file with a sticker for later use in the
        :meth:`create_new_sticker_set` and :meth:`add_sticker_to_set` methods (can be used multiple
        times).

        .. versionchanged:: 20.5
           Removed deprecated parameter ``png_sticker``.

        Args:
            user_id (:obj:`int`): User identifier of sticker file owner.
            sticker (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | \
                :obj:`bytes` | :class:`pathlib.Path`): A file with the sticker in the
                ``".WEBP"``, ``".PNG"``, ``".TGS"`` or ``".WEBM"``
                format. See `here <https://core.telegram.org/stickers>`_ for technical requirements
                . |uploadinput|

                .. versionadded:: 20.2

            sticker_format (:obj:`str`): Format of the sticker. Must be one of
                :attr:`telegram.constants.StickerFormat.STATIC`,
                :attr:`telegram.constants.StickerFormat.ANIMATED`,
                :attr:`telegram.constants.StickerFormat.VIDEO`.

                .. versionadded:: 20.2

        Returns:
            :class:`telegram.File`: On success, the uploaded File is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "user_id": user_id,
            "sticker": self._parse_file_input(sticker),
            "sticker_format": sticker_format,
        }
        result = await self._post(
            "uploadStickerFile",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return File.de_json(result, self)

    async def add_sticker_to_set(
        self,
        user_id: int,
        name: str,
        sticker: "InputSticker",
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to add a new sticker to a set created by the bot. The format of the added
        sticker must match the format of the other stickers in the set. Emoji sticker sets can have
        up to :tg-const:`telegram.constants.StickerSetLimit.MAX_EMOJI_STICKERS` stickers. Other
        sticker sets can have up to
        :tg-const:`telegram.constants.StickerSetLimit.MAX_STATIC_STICKERS` stickers.

        .. versionchanged:: 20.2
            Since Bot API 6.6, the parameter :paramref:`sticker` replace the parameters
            ``png_sticker``, ``tgs_sticker``, ``webm_sticker``, ``emojis``, and ``mask_position``.

        .. versionchanged:: 20.5
           Removed deprecated parameters ``png_sticker``, ``tgs_sticker``, ``webm_sticker``,
           ``emojis``, and ``mask_position``.

        Args:
            user_id (:obj:`int`): User identifier of created sticker set owner.
            name (:obj:`str`): Sticker set name.
            sticker (:class:`telegram.InputSticker`): An object with information about the added
                sticker. If exactly the same sticker had already been added to the set, then the
                set isn't changed.

                .. versionadded:: 20.2

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "user_id": user_id,
            "name": name,
            "sticker": sticker,
        }

        return await self._post(
            "addStickerToSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_sticker_position_in_set(
        self,
        sticker: "str | Sticker",
        position: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to move a sticker in a set created by the bot to a specific position.

        Args:
            sticker (:obj:`str` | :class:`~telegram.Sticker`): File identifier of the sticker or
                the sticker object.

                .. versionchanged:: 21.10
                   Accepts also :class:`telegram.Sticker` instances.
            position (:obj:`int`): New sticker position in the set, zero-based.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "sticker": sticker if isinstance(sticker, str) else sticker.file_id,
            "position": position,
        }
        return await self._post(
            "setStickerPositionInSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def create_new_sticker_set(
        self,
        user_id: int,
        name: str,
        title: str,
        stickers: Sequence["InputSticker"],
        sticker_type: str | None = None,
        needs_repainting: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to create new sticker set owned by a user.
        The bot will be able to edit the created sticker set thus created.

        .. versionchanged:: 20.0
            The parameter ``contains_masks`` has been removed. Use :paramref:`sticker_type`
            instead.

        .. versionchanged:: 20.2
            Since Bot API 6.6, the parameters :paramref:`stickers` and :paramref:`sticker_format`
            replace the parameters ``png_sticker``, ``tgs_sticker``,``webm_sticker``, ``emojis``,
            and ``mask_position``.

        .. versionchanged:: 20.5
            Removed the deprecated parameters mentioned above and adjusted the order of the
            parameters.

        .. versionremoved:: 21.2
           Removed the deprecated parameter ``sticker_format``.

        Args:
            user_id (:obj:`int`): User identifier of created sticker set owner.
            name (:obj:`str`): Short name of sticker set, to be used in t.me/addstickers/ URLs
                (e.g., animals). Can contain only english letters, digits and underscores.
                Must begin with a letter, can't contain consecutive underscores and
                must end in "_by_<bot username>". <bot_username> is case insensitive.
                :tg-const:`telegram.constants.StickerLimit.MIN_NAME_AND_TITLE`-
                :tg-const:`telegram.constants.StickerLimit.MAX_NAME_AND_TITLE` characters.
            title (:obj:`str`): Sticker set title,
                :tg-const:`telegram.constants.StickerLimit.MIN_NAME_AND_TITLE`-
                :tg-const:`telegram.constants.StickerLimit.MAX_NAME_AND_TITLE` characters.

            stickers (Sequence[:class:`telegram.InputSticker`]): A sequence of
                :tg-const:`telegram.constants.StickerSetLimit.MIN_INITIAL_STICKERS`-
                :tg-const:`telegram.constants.StickerSetLimit.MAX_INITIAL_STICKERS` initial
                stickers to be added to the sticker set.

                .. versionadded:: 20.2

            sticker_type (:obj:`str`, optional): Type of stickers in the set, pass
                :attr:`telegram.Sticker.REGULAR` or :attr:`telegram.Sticker.MASK`, or
                :attr:`telegram.Sticker.CUSTOM_EMOJI`. By default, a regular sticker set is created

                .. versionadded:: 20.0

            needs_repainting (:obj:`bool`, optional): Pass :obj:`True` if stickers in the sticker
                set must be repainted to the color of text when used in messages, the accent color
                if used as emoji status, white on chat photos, or another appropriate color based
                on context; for custom emoji sticker sets only.

                .. versionadded:: 20.2

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
            "name": name,
            "title": title,
            "stickers": stickers,
            "sticker_type": sticker_type,
            "needs_repainting": needs_repainting,
        }

        return await self._post(
            "createNewStickerSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_sticker_from_set(
        self,
        sticker: "str | Sticker",
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to delete a sticker from a set created by the bot.

        Args:
            sticker (:obj:`str` | :class:`telegram.Sticker`): File identifier of the sticker or
                the sticker object.

                .. versionchanged:: 21.10
                   Accepts also :class:`telegram.Sticker` instances.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"sticker": sticker if isinstance(sticker, str) else sticker.file_id}
        return await self._post(
            "deleteStickerFromSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_sticker_set(
        self,
        name: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to delete a sticker set that was created by the bot.

        .. versionadded:: 20.2

        Args:
            name (:obj:`str`): Sticker set name.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"name": name}
        return await self._post(
            "deleteStickerSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_sticker_set_thumbnail(
        self,
        name: str,
        user_id: int,
        format: str,  # pylint: disable=redefined-builtin
        thumbnail: "FileInput | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to set the thumbnail of a regular or mask sticker set. The format of the
        thumbnail file must match the format of the stickers in the set.

        .. versionadded:: 20.2

        .. versionchanged:: 21.1
            As per Bot API 7.2, the new argument :paramref:`format` will be required, and thus the
            order of the arguments had to be changed.

        Args:
            name (:obj:`str`): Sticker set name
            user_id (:obj:`int`): User identifier of created sticker set owner.
            format (:obj:`str`): Format of the added sticker, must be one of
                :tg-const:`telegram.constants.StickerFormat.STATIC` for a
                ``.WEBP`` or ``.PNG`` image, :tg-const:`telegram.constants.StickerFormat.ANIMATED`
                for a ``.TGS`` animation, :tg-const:`telegram.constants.StickerFormat.VIDEO` for a
                ``.WEBM`` video.

                .. versionadded:: 21.1

            thumbnail (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | \
                :obj:`bytes` | :class:`pathlib.Path`, optional): A **.WEBP** or **.PNG** image
                with the thumbnail, must
                be up to :tg-const:`telegram.constants.StickerSetLimit.MAX_STATIC_THUMBNAIL_SIZE`
                kilobytes in size and have width and height of exactly
                :tg-const:`telegram.constants.StickerSetLimit.STATIC_THUMB_DIMENSIONS` px, or a
                **.TGS** animation with the thumbnail up to
                :tg-const:`telegram.constants.StickerSetLimit.MAX_ANIMATED_THUMBNAIL_SIZE`
                kilobytes in size; see
                `the docs <https://core.telegram.org/stickers#animated-stickers-and-emoji>`_ for
                animated sticker technical requirements, or a ``.WEBM`` video with the thumbnail up
                to :tg-const:`telegram.constants.StickerSetLimit.MAX_ANIMATED_THUMBNAIL_SIZE`
                kilobytes in size; see
                `this <https://core.telegram.org/stickers#video-stickers-and-emoji>`_ for video
                sticker technical requirements.

                |fileinput|

                Animated and video sticker set thumbnails can't be uploaded via HTTP URL. If
                omitted, then the thumbnail is dropped and the first sticker is used as the
                thumbnail.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "name": name,
            "user_id": user_id,
            "thumbnail": self._parse_file_input(thumbnail) if thumbnail else None,
            "format": format,
        }

        return await self._post(
            "setStickerSetThumbnail",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_sticker_set_title(
        self,
        name: str,
        title: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to set the title of a created sticker set.

        .. versionadded:: 20.2

        Args:
            name (:obj:`str`): Sticker set name.
            title (:obj:`str`): Sticker set title,
                :tg-const:`telegram.constants.StickerLimit.MIN_NAME_AND_TITLE`-
                :tg-const:`telegram.constants.StickerLimit.MAX_NAME_AND_TITLE` characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"name": name, "title": title}
        return await self._post(
            "setStickerSetTitle",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_sticker_emoji_list(
        self,
        sticker: "str | Sticker",
        emoji_list: Sequence[str],
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the list of emoji assigned to a regular or custom emoji sticker.
        The sticker must belong to a sticker set created by the bot.

        .. versionadded:: 20.2

        Args:
            sticker (:obj:`str` | :class:`~telegram.Sticker`): File identifier of the sticker or
                the sticker object.

                .. versionchanged:: 21.10
                   Accepts also :class:`telegram.Sticker` instances.
            emoji_list (Sequence[:obj:`str`]): A sequence of
                :tg-const:`telegram.constants.StickerLimit.MIN_STICKER_EMOJI`-
                :tg-const:`telegram.constants.StickerLimit.MAX_STICKER_EMOJI` emoji associated with
                the sticker.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "sticker": sticker if isinstance(sticker, str) else sticker.file_id,
            "emoji_list": emoji_list,
        }
        return await self._post(
            "setStickerEmojiList",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_sticker_keywords(
        self,
        sticker: "str | Sticker",
        keywords: Sequence[str] | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change search keywords assigned to a regular or custom emoji sticker.
        The sticker must belong to a sticker set created by the bot.

        .. versionadded:: 20.2

        Args:
            sticker (:obj:`str` | :class:`~telegram.Sticker`): File identifier of the sticker or
                the sticker object.

                .. versionchanged:: 21.10
                   Accepts also :class:`telegram.Sticker` instances.
            keywords (Sequence[:obj:`str`]): A sequence of
                0-:tg-const:`telegram.constants.StickerLimit.MAX_SEARCH_KEYWORDS` search keywords
                for the sticker with total length up to
                :tg-const:`telegram.constants.StickerLimit.MAX_KEYWORD_LENGTH` characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "sticker": sticker if isinstance(sticker, str) else sticker.file_id,
            "keywords": keywords,
        }
        return await self._post(
            "setStickerKeywords",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_sticker_mask_position(
        self,
        sticker: "str | Sticker",
        mask_position: MaskPosition | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the mask position of a mask sticker.
        The sticker must belong to a sticker set that was created by the bot.

        .. versionadded:: 20.2

        Args:
            sticker (:obj:`str` | :class:`~telegram.Sticker`): File identifier of the sticker or
                the sticker object.

                .. versionchanged:: 21.10
                   Accepts also :class:`telegram.Sticker` instances.
            mask_position (:class:`telegram.MaskPosition`, optional): A object with the position
                where the mask should be placed on faces. Omit the parameter to remove the mask
                position.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "sticker": sticker if isinstance(sticker, str) else sticker.file_id,
            "mask_position": mask_position,
        }
        return await self._post(
            "setStickerMaskPosition",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_custom_emoji_sticker_set_thumbnail(
        self,
        name: str,
        custom_emoji_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to set the thumbnail of a custom emoji sticker set.

        .. versionadded:: 20.2

        Args:
            name (:obj:`str`): Sticker set name.
            custom_emoji_id (:obj:`str`, optional): Custom emoji identifier of a sticker from the
                sticker set; pass an empty string to drop the thumbnail and use the first sticker
                as the thumbnail.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"name": name, "custom_emoji_id": custom_emoji_id}

        return await self._post(
            "setCustomEmojiStickerSetThumbnail",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_passport_data_errors(
        self,
        user_id: int,
        errors: Sequence["PassportElementError"],
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Informs a user that some of the Telegram Passport elements they provided contains errors.
        The user will not be able to re-submit their Passport to you until the errors are fixed
        (the contents of the field for which you returned the error must change).

        Use this if the data submitted by the user doesn't satisfy the standards your service
        requires for any reason. For example, if a birthday date seems invalid, a submitted
        document is blurry, a scan shows evidence of tampering, etc. Supply some details in the
        error message to make sure the user knows how to correct the issues.

        Args:
            user_id (:obj:`int`): User identifier
            errors (Sequence[:class:`PassportElementError`]): A Sequence describing the errors.

                .. versionchanged:: 20.0
                    |sequenceargs|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"user_id": user_id, "errors": errors}
        return await self._post(
            "setPassportDataErrors",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_poll(
        self,
        chat_id: int | str,
        question: str,
        options: Sequence["str | InputPollOption"],
        is_anonymous: bool | None = None,
        type: str | None = None,  # pylint: disable=redefined-builtin
        allows_multiple_answers: bool | None = None,
        correct_option_id: CorrectOptionID | None = None,
        is_closed: bool | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        explanation: str | None = None,
        explanation_parse_mode: ODVInput[str] = DEFAULT_NONE,
        open_period: TimePeriod | None = None,
        close_date: int | dtm.datetime | None = None,
        explanation_entities: Sequence["MessageEntity"] | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        question_parse_mode: ODVInput[str] = DEFAULT_NONE,
        question_entities: Sequence["MessageEntity"] | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to send a native poll.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            question (:obj:`str`): Poll question, :tg-const:`telegram.Poll.MIN_QUESTION_LENGTH`-
                :tg-const:`telegram.Poll.MAX_QUESTION_LENGTH` characters.
            options (Sequence[:obj:`str` | :class:`telegram.InputPollOption`]): Sequence of
                :tg-const:`telegram.Poll.MIN_OPTION_NUMBER`-
                :tg-const:`telegram.Poll.MAX_OPTION_NUMBER` answer options. Each option may either
                be a string with
                :tg-const:`telegram.Poll.MIN_OPTION_LENGTH`-
                :tg-const:`telegram.Poll.MAX_OPTION_LENGTH` characters or an
                :class:`~telegram.InputPollOption` object. Strings are converted to
                :class:`~telegram.InputPollOption` objects automatically.

                .. versionchanged:: 20.0
                    |sequenceargs|

                .. versionchanged:: 21.2
                   Bot API 7.3 adds support for :class:`~telegram.InputPollOption` objects.
            is_anonymous (:obj:`bool`, optional): :obj:`True`, if the poll needs to be anonymous,
                defaults to :obj:`True`.
            type (:obj:`str`, optional): Poll type, :tg-const:`telegram.Poll.QUIZ` or
                :tg-const:`telegram.Poll.REGULAR`, defaults to :tg-const:`telegram.Poll.REGULAR`.
            allows_multiple_answers (:obj:`bool`, optional): :obj:`True`, if the poll allows
                multiple answers, ignored for polls in quiz mode, defaults to :obj:`False`.
            correct_option_id (:obj:`int`, optional): 0-based identifier of the correct answer
                option, required for polls in quiz mode.
            explanation (:obj:`str`, optional): Text that is shown when a user chooses an incorrect
                answer or taps on the lamp icon in a quiz-style poll,
                0-:tg-const:`telegram.Poll.MAX_EXPLANATION_LENGTH` characters with at most
                :tg-const:`telegram.Poll.MAX_EXPLANATION_LINE_FEEDS` line feeds after entities
                parsing.
            explanation_parse_mode (:obj:`str`, optional): Mode for parsing entities in the
                explanation. See the constants in :class:`telegram.constants.ParseMode` for the
                available modes.
            explanation_entities (Sequence[:class:`telegram.MessageEntity`], optional): Sequence of
                special entities that appear in message text, which can be specified instead of
                :paramref:`explanation_parse_mode`.

                .. versionchanged:: 20.0
                    |sequenceargs|
            open_period (:obj:`int` | :class:`datetime.timedelta`, optional): Amount of time in
                seconds the poll will be active
                after creation, :tg-const:`telegram.Poll.MIN_OPEN_PERIOD`-
                :tg-const:`telegram.Poll.MAX_OPEN_PERIOD`. Can't be used together with
                :paramref:`close_date`.

                .. versionchanged:: 21.11
                    |time-period-input|
            close_date (:obj:`int` | :obj:`datetime.datetime`, optional): Point in time (Unix
                timestamp) when the poll will be automatically closed. Must be at least
                :tg-const:`telegram.Poll.MIN_OPEN_PERIOD` and no more than
                :tg-const:`telegram.Poll.MAX_OPEN_PERIOD` seconds in the future.
                Can't be used together with :paramref:`open_period`.
                |tz-naive-dtms|
            is_closed (:obj:`bool`, optional): Pass :obj:`True`, if the poll needs to be
                immediately closed. This can be useful for poll preview.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            question_parse_mode (:obj:`str`, optional): Mode for parsing entities in the question.
                See the constants in :class:`telegram.constants.ParseMode` for the available modes.
                Currently, only custom emoji entities are allowed.

                .. versionadded:: 21.2
            question_entities (Sequence[:class:`telegram.Message`], optional): Special entities
                that appear in the poll :paramref:`question`. It can be specified instead of
                :paramref:`question_parse_mode`.

                .. versionadded:: 21.2
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "question": question,
            "options": [
                InputPollOption(option) if isinstance(option, str) else option
                for option in options
            ],
            "explanation_parse_mode": explanation_parse_mode,
            "is_anonymous": is_anonymous,
            "type": type,
            "allows_multiple_answers": allows_multiple_answers,
            "correct_option_id": correct_option_id,
            "is_closed": is_closed,
            "explanation": explanation,
            "explanation_entities": explanation_entities,
            "open_period": open_period,
            "close_date": close_date,
            "question_parse_mode": question_parse_mode,
            "question_entities": question_entities,
        }

        return await self._send_message(
            "sendPoll",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
        )

    async def stop_poll(
        self,
        chat_id: int | str,
        message_id: int,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Poll:
        """
        Use this method to stop a poll which was sent by the bot.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            message_id (:obj:`int`): Identifier of the original message with the poll.
            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional): An object for a new
                message inline keyboard.
            business_connection_id (:obj:`str`, optional): |business_id_str_edit|

                .. versionadded:: 21.4

        Returns:
            :class:`telegram.Poll`: On success, the stopped Poll is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup,
            "business_connection_id": business_connection_id,
        }

        result = await self._post(
            "stopPoll",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return Poll.de_json(result, self)

    async def send_checklist(
        self,
        business_connection_id: str,
        chat_id: int,
        checklist: InputChecklist,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_effect_id: str | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to send a checklist on behalf of a connected business account.

        .. versionadded:: 22.3

        Args:
            business_connection_id (:obj:`str`):
                |business_id_str|
            chat_id (:obj:`int`):
                Unique identifier for the target chat.
            checklist (:class:`telegram.InputChecklist`):
                The checklist to send.
            disable_notification (:obj:`bool`, optional):
                |disable_notification|
            protect_content (:obj:`bool`, optional):
                |protect_content|
            message_effect_id (:obj:`str`, optional):
                |message_effect_id|
            reply_parameters (:class:`telegram.ReplyParameters`, optional):
                |reply_parameters|
            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional):
                An object for an inline keyboard

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "checklist": checklist,
        }

        return await self._send_message(
            "sendChecklist",
            data,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            protect_content=protect_content,
            reply_parameters=reply_parameters,
            message_effect_id=message_effect_id,
            business_connection_id=business_connection_id,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_to_message_id=reply_to_message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_message_checklist(
        self,
        business_connection_id: str,
        chat_id: int,
        message_id: int,
        checklist: InputChecklist,
        reply_markup: "InlineKeyboardMarkup | None" = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to edit a checklist on behalf of a connected business account.

        .. versionadded:: 22.3

        Args:
            business_connection_id (:obj:`str`):
                |business_id_str|
            chat_id (:obj:`int`):
                Unique identifier for the target chat.
            message_id (:obj:`int`):
                Unique identifier for the target message.
            checklist (:class:`telegram.InputChecklist`):
                The new checklist.
            reply_markup (:class:`telegram.InlineKeyboardMarkup`, optional):
                An object for the new inline keyboard for the message.

        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "checklist": checklist,
        }

        return await self._send_message(
            "editMessageChecklist",
            data,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_dice(
        self,
        chat_id: int | str,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        emoji: str | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """
        Use this method to send an animated emoji that will display a random value.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            disable_notification (:obj:`bool`, optional): |disable_notification|
            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user
            emoji (:obj:`str`, optional): Emoji on which the dice throw animation is based.
                Currently, must be one of :class:`telegram.constants.DiceEmoji`. Dice can have
                values
                :tg-const:`telegram.Dice.MIN_VALUE`-:tg-const:`telegram.Dice.MAX_VALUE_BOWLING`
                for :tg-const:`telegram.Dice.DICE`, :tg-const:`telegram.Dice.DARTS` and
                :tg-const:`telegram.Dice.BOWLING`, values
                :tg-const:`telegram.Dice.MIN_VALUE`-:tg-const:`telegram.Dice.MAX_VALUE_BASKETBALL`
                for :tg-const:`telegram.Dice.BASKETBALL` and :tg-const:`telegram.Dice.FOOTBALL`,
                and values :tg-const:`telegram.Dice.MIN_VALUE`-
                :tg-const:`telegram.Dice.MAX_VALUE_SLOT_MACHINE`
                for :tg-const:`telegram.Dice.SLOT_MACHINE`. Defaults to
                :tg-const:`telegram.Dice.DICE`.

                .. versionchanged:: 13.4
                   Added the :tg-const:`telegram.Dice.BOWLING` emoji.
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.1
            message_effect_id (:obj:`str`, optional): |message_effect_id|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|


        Returns:
            :class:`telegram.Message`: On success, the sent Message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "emoji": emoji}

        return await self._send_message(
            "sendDice",
            data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

    async def get_my_default_administrator_rights(
        self,
        for_channels: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ChatAdministratorRights:
        """Use this method to get the current default administrator rights of the bot.

        .. seealso:: :meth:`set_my_default_administrator_rights`

        .. versionadded:: 20.0

        Args:
            for_channels (:obj:`bool`, optional): Pass :obj:`True` to get default administrator
                rights of the bot in channels. Otherwise, default administrator rights of the bot
                for groups and supergroups will be returned.

        Returns:
            :class:`telegram.ChatAdministratorRights`: On success.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"for_channels": for_channels}

        result = await self._post(
            "getMyDefaultAdministratorRights",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return ChatAdministratorRights.de_json(result, self)

    async def set_my_default_administrator_rights(
        self,
        rights: ChatAdministratorRights | None = None,
        for_channels: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to change the default administrator rights requested by the bot when
        it's added as an administrator to groups or channels. These rights will be suggested to
        users, but they are free to modify the list before adding the bot.

        .. seealso:: :meth:`get_my_default_administrator_rights`

        .. versionadded:: 20.0

        Args:
            rights (:class:`telegram.ChatAdministratorRights`, optional): A
                :class:`telegram.ChatAdministratorRights` object describing new default
                administrator
                rights. If not specified, the default administrator rights will be cleared.
            for_channels (:obj:`bool`, optional): Pass :obj:`True` to change the default
                administrator rights of the bot in channels. Otherwise, the default administrator
                rights of the bot for groups and supergroups will be changed.

        Returns:
            :obj:`bool`: Returns :obj:`True` on success.

        Raises:
            :exc:`telegram.error.TelegramError`
        """
        data: JSONDict = {"rights": rights, "for_channels": for_channels}

        return await self._post(
            "setMyDefaultAdministratorRights",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_my_commands(
        self,
        scope: BotCommandScope | None = None,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple[BotCommand, ...]:
        """
        Use this method to get the current list of the bot's commands for the given scope and user
        language.

        .. seealso:: :meth:`set_my_commands`, :meth:`delete_my_commands`

        .. versionchanged:: 20.0
            Returns a tuple instead of a list.

        Args:
            scope (:class:`telegram.BotCommandScope`, optional): An object,
                describing scope of users. Defaults to :class:`telegram.BotCommandScopeDefault`.

                .. versionadded:: 13.7

            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code or an empty
                string.

                .. versionadded:: 13.7

        Returns:
            tuple[:class:`telegram.BotCommand`]: On success, the commands set for the bot. An empty
            tuple is returned if commands are not set.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"scope": scope, "language_code": language_code}

        result = await self._post(
            "getMyCommands",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return BotCommand.de_list(result, self)

    async def set_my_commands(
        self,
        commands: Sequence[BotCommand | tuple[str, str]],
        scope: BotCommandScope | None = None,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the list of the bot's commands. See the
        `Telegram docs <https://core.telegram.org/bots/features#commands>`_ for more details about
        bot commands.

        .. seealso:: :meth:`get_my_commands`, :meth:`delete_my_commands`

        Args:
            commands (Sequence[:class:`BotCommand` | (:obj:`str`, :obj:`str`)]): A sequence
                of bot commands to be set as the list of the bot's commands. At most
                :tg-const:`telegram.constants.BotCommandLimit.MAX_COMMAND_NUMBER` commands can be
                specified.

                Note:
                    If you pass in a sequence of :obj:`tuple`, the order of elements in each
                    :obj:`tuple` must correspond to the order of positional arguments to create a
                    :class:`BotCommand` instance.

                .. versionchanged:: 20.0
                    |sequenceargs|
            scope (:class:`telegram.BotCommandScope`, optional): An object,
                describing scope of users for which the commands are relevant. Defaults to
                :class:`telegram.BotCommandScopeDefault`.

                .. versionadded:: 13.7

            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code. If empty,
                commands will be applied to all users from the given scope, for whose language
                there are no dedicated commands.

                .. versionadded:: 13.7

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        cmds = [c if isinstance(c, BotCommand) else BotCommand(c[0], c[1]) for c in commands]
        data: JSONDict = {"commands": cmds, "scope": scope, "language_code": language_code}

        return await self._post(
            "setMyCommands",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_my_commands(
        self,
        scope: BotCommandScope | None = None,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to delete the list of the bot's commands for the given scope and user
        language. After deletion,
        `higher level commands <https://core.telegram.org/bots/api#determining-list-of-commands>`_
        will be shown to affected users.

        .. versionadded:: 13.7

        .. seealso:: :meth:`get_my_commands`, :meth:`set_my_commands`

        Args:
            scope (:class:`telegram.BotCommandScope`, optional): An object,
                describing scope of users for which the commands are relevant. Defaults to
                :class:`telegram.BotCommandScopeDefault`.
            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code. If empty,
                commands will be applied to all users from the given scope, for whose language
                there are no dedicated commands.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"scope": scope, "language_code": language_code}

        return await self._post(
            "deleteMyCommands",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def log_out(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to log out from the cloud Bot API server before launching the bot locally.
        You *must* log out the bot before running it locally, otherwise there is no guarantee that
        the bot will receive updates. After a successful call, you can immediately log in on a
        local server, but will not be able to log in back to the cloud Bot API server for 10
        minutes.

        Returns:
            :obj:`True`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        return await self._post(
            "logOut",
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def close(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to close the bot instance before moving it from one local server to
        another. You need to delete the webhook before calling this method to ensure that the bot
        isn't launched again after server restart. The method will return error 429 in the first
        10 minutes after the bot is launched.

        Returns:
            :obj:`True`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        return await self._post(
            "close",
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def copy_message(
        self,
        chat_id: int | str,
        from_chat_id: str | int,
        message_id: int,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        show_caption_above_media: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        video_start_timestamp: int | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_effect_id: str | None = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> MessageId:
        """Use this method to copy messages of any kind. Service messages, paid media messages,
        giveaway messages, giveaway winners messages, and invoice messages
        can't be copied. The method is analogous to the method :meth:`forward_message`, but the
        copied message doesn't have a link to the original message.

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            from_chat_id (:obj:`int` | :obj:`str`): Unique identifier for the chat where the
                original message was sent (or channel username in the format ``@channelusername``).
            message_id (:obj:`int`): Message identifier in the chat specified in from_chat_id.
            video_start_timestamp (:obj:`int`, optional): New start timestamp for the
                copied video in the message

                .. versionadded:: 21.11
            caption (:obj:`str`, optional): New caption for media,
                0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters after
                entities parsing. If not specified, the original caption is kept.
            parse_mode (:obj:`str`, optional): Mode for parsing entities in the new caption. See
                the constants in :class:`telegram.constants.ParseMode` for the available modes.
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|

                .. versionchanged:: 20.0
                    |sequenceargs|
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|

                .. versionadded:: 13.10
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 20.0

            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|

                .. versionadded:: 20.8
            show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|

                .. versionadded:: 21.3
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4
            message_effect_id (:obj:`str`, optional): Unique identifier of the message effect to be
                added to the message; only available when copying to private chats

                .. versionadded:: 22.6

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|
            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

                .. versionchanged:: 20.8
                    Bot API 7.0 introduced :paramref:`reply_parameters` |rtm_aswr_deprecated|

                .. versionchanged:: 21.0
                    |keyword_only_arg|

        Returns:
            :class:`telegram.MessageId`: On success, the :class:`telegram.MessageId` of the sent
                message is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        if allow_sending_without_reply is not DEFAULT_NONE and reply_parameters is not None:
            raise ValueError(
                "`allow_sending_without_reply` and `reply_parameters` are mutually exclusive."
            )

        if reply_to_message_id is not None and reply_parameters is not None:
            raise ValueError(
                "`reply_to_message_id` and `reply_parameters` are mutually exclusive."
            )

        if reply_to_message_id is not None:
            reply_parameters = ReplyParameters(
                message_id=reply_to_message_id,
                allow_sending_without_reply=allow_sending_without_reply,
            )

        data: JSONDict = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "caption": caption,
            "caption_entities": caption_entities,
            "reply_markup": reply_markup,
            "message_thread_id": message_thread_id,
            "reply_parameters": reply_parameters,
            "show_caption_above_media": show_caption_above_media,
            "allow_paid_broadcast": allow_paid_broadcast,
            "direct_messages_topic_id": direct_messages_topic_id,
            "video_start_timestamp": video_start_timestamp,
            "suggested_post_parameters": suggested_post_parameters,
            "message_effect_id": message_effect_id,
        }

        result = await self._post(
            "copyMessage",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return MessageId.de_json(result, self)

    async def copy_messages(
        self,
        chat_id: int | str,
        from_chat_id: str | int,
        message_ids: Sequence[int],
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        remove_caption: bool | None = None,
        direct_messages_topic_id: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple["MessageId", ...]:
        """
        Use this method to copy messages of any kind. If some of the specified messages can't be
        found or copied, they are skipped. Service messages, paid media messages, giveaway
        messages, giveaway winners messages, and invoice messages can't be copied. A quiz poll can
        be copied only if the value
        of the field :attr:`telegram.Poll.correct_option_id` is known to the bot. The method is
        analogous to the method :meth:`forward_messages`, but the copied messages don't have a
        link to the original message. Album grouping is kept for copied messages.

        .. versionadded:: 20.8

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            from_chat_id (:obj:`int` | :obj:`str`): Unique identifier for the chat where the
                original message was sent (or channel username in the format ``@channelusername``).
            message_ids (Sequence[:obj:`int`]): A list of
                :tg-const:`telegram.constants.BulkRequestLimit.MIN_LIMIT` -
                :tg-const:`telegram.constants.BulkRequestLimit.MAX_LIMIT` identifiers of messages
                in the chat :paramref:`from_chat_id` to copy. The identifiers must be
                specified in a strictly increasing order.
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|
            remove_caption (:obj:`bool`, optional): Pass :obj:`True` to copy the messages without
                their captions.
            direct_messages_topic_id (:obj:`int`, optional): Identifier of the direct messages
                topic to which the message will be sent; required if the message is sent to a
                direct messages chat.

                .. versionadded:: 22.4


        Returns:
            tuple[:class:`telegram.MessageId`]: On success, a tuple of :class:`~telegram.MessageId`
            of the sent messages is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_ids": message_ids,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "message_thread_id": message_thread_id,
            "remove_caption": remove_caption,
            "direct_messages_topic_id": direct_messages_topic_id,
        }

        result = await self._post(
            "copyMessages",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return MessageId.de_list(result, self)

    async def set_chat_menu_button(
        self,
        chat_id: int | None = None,
        menu_button: MenuButton | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to change the bot's menu button in a private chat, or the default menu
        button.

        .. seealso:: :meth:`get_chat_menu_button`, :meth:`telegram.Chat.get_menu_button`
            :meth:`telegram.User.get_menu_button`

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int`, optional): Unique identifier for the target private chat. If not
                specified, default bot's menu button will be changed
            menu_button (:class:`telegram.MenuButton`, optional): An object for the new bot's menu
                button. Defaults to :class:`telegram.MenuButtonDefault`.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        """
        data: JSONDict = {"chat_id": chat_id, "menu_button": menu_button}

        return await self._post(
            "setChatMenuButton",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_chat_menu_button(
        self,
        chat_id: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> MenuButton:
        """Use this method to get the current value of the bot's menu button in a private chat, or
        the default menu button.

        .. seealso:: :meth:`set_chat_menu_button`, :meth:`telegram.Chat.set_menu_button`,
            :meth:`telegram.User.set_menu_button`

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int`, optional): Unique identifier for the target private chat. If not
                specified, default bot's menu button will be returned.

        Returns:
            :class:`telegram.MenuButton`: On success, the current menu button is returned.

        """
        data = {"chat_id": chat_id}

        result = await self._post(
            "getChatMenuButton",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return MenuButton.de_json(result, bot=self)

    async def create_invoice_link(
        self,
        title: str,
        description: str,
        payload: str,
        currency: str,
        prices: Sequence["LabeledPrice"],
        provider_token: str | None = None,
        max_tip_amount: int | None = None,
        suggested_tip_amounts: Sequence[int] | None = None,
        provider_data: str | object | None = None,
        photo_url: str | None = None,
        photo_size: int | None = None,
        photo_width: int | None = None,
        photo_height: int | None = None,
        need_name: bool | None = None,
        need_phone_number: bool | None = None,
        need_email: bool | None = None,
        need_shipping_address: bool | None = None,
        send_phone_number_to_provider: bool | None = None,
        send_email_to_provider: bool | None = None,
        is_flexible: bool | None = None,
        subscription_period: TimePeriod | None = None,
        business_connection_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> str:
        """Use this method to create a link for an invoice.

        .. versionadded:: 20.0

        Args:
            business_connection_id (:obj:`str`, optional): |business_id_str|
                For payments in |tg_stars| only.

                .. versionadded:: 21.8
            title (:obj:`str`): Product name. :tg-const:`telegram.Invoice.MIN_TITLE_LENGTH`-
                :tg-const:`telegram.Invoice.MAX_TITLE_LENGTH` characters.
            description (:obj:`str`): Product description.
                :tg-const:`telegram.Invoice.MIN_DESCRIPTION_LENGTH`-
                :tg-const:`telegram.Invoice.MAX_DESCRIPTION_LENGTH` characters.
            payload (:obj:`str`): Bot-defined invoice payload.
                :tg-const:`telegram.Invoice.MIN_PAYLOAD_LENGTH`-
                :tg-const:`telegram.Invoice.MAX_PAYLOAD_LENGTH` bytes. This will not be
                displayed to the user, use it for your internal processes.
            provider_token (:obj:`str`, optional): Payments provider token, obtained via
                `@BotFather <https://t.me/BotFather>`_. Pass an empty string for payments in
                |tg_stars|.

                .. versionchanged:: 21.11
                    Bot API 7.4 made this parameter is optional and this is now reflected in the
                    function signature.

            currency (:obj:`str`): Three-letter ISO 4217 currency code, see `more on currencies
                <https://core.telegram.org/bots/payments#supported-currencies>`_. Pass ``XTR`` for
                payments in |tg_stars|.
            prices (Sequence[:class:`telegram.LabeledPrice`)]: Price breakdown, a sequence
                of components (e.g. product price, tax, discount, delivery cost, delivery tax,
                bonus, etc.). Must contain exactly one item for payments in |tg_stars|.

                .. versionchanged:: 20.0
                    |sequenceargs|
            subscription_period (:obj:`int` | :class:`datetime.timedelta`, optional): The time the
                subscription will be active for before the next payment, either as number of
                seconds or as :class:`datetime.timedelta` object. The currency must be set to
                ``“XTR”`` (Telegram Stars) if the parameter is used. Currently, it must always be
                :tg-const:`telegram.constants.InvoiceLimit.SUBSCRIPTION_PERIOD` if specified. Any
                number of subscriptions can be active for a given bot at the same time, including
                multiple concurrent subscriptions from the same user. Subscription price must
                not exceed
                :tg-const:`telegram.constants.InvoiceLimit.SUBSCRIPTION_MAX_PRICE`
                Telegram Stars.

                .. versionadded:: 21.8
            max_tip_amount (:obj:`int`, optional): The maximum accepted amount for tips in the
                *smallest units* of the currency (integer, **not** float/double). For example, for
                a maximum tip of ``US$ 1.45`` pass ``max_tip_amount = 145``. See the ``exp``
                parameter in `currencies.json
                <https://core.telegram.org/bots/payments/currencies.json>`_, it shows the number of
                digits past the decimal point for each currency (2 for the majority of currencies).
                Defaults to ``0``. Not supported for payments in |tg_stars|.
            suggested_tip_amounts (Sequence[:obj:`int`], optional): An array of
                suggested amounts of tips in the *smallest units* of the currency (integer, **not**
                float/double). At most :tg-const:`telegram.Invoice.MAX_TIP_AMOUNTS` suggested tip
                amounts can be specified. The suggested tip amounts must be positive, passed in a
                strictly increased order and must not exceed :paramref:`max_tip_amount`.

                .. versionchanged:: 20.0
                    |sequenceargs|
            provider_data (:obj:`str` | :obj:`object`, optional): Data about the
                invoice, which will be shared with the payment provider. A detailed description of
                required fields should be provided by the payment provider. When an object is
                passed, it will be encoded as JSON.
            photo_url (:obj:`str`, optional): URL of the product photo for the invoice. Can be a
                photo of the goods or a marketing image for a service.
            photo_size (:obj:`int`, optional): Photo size in bytes.
            photo_width (:obj:`int`, optional): Photo width.
            photo_height (:obj:`int`, optional): Photo height.
            need_name (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's full
                name to complete the order. Ignored for payments in |tg_stars|.
            need_phone_number (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's
                phone number to complete the order. Ignored for payments in |tg_stars|.
            need_email (:obj:`bool`, optional): Pass :obj:`True`, if you require the user's email
                address to complete the order. Ignored for payments in |tg_stars|.
            need_shipping_address (:obj:`bool`, optional): Pass :obj:`True`, if you require the
                user's shipping address to complete the order. Ignored for payments in
                |tg_stars|.
            send_phone_number_to_provider (:obj:`bool`, optional): Pass :obj:`True`, if user's
                phone number should be sent to provider. Ignored for payments in |tg_stars|.
            send_email_to_provider (:obj:`bool`, optional): Pass :obj:`True`, if user's email
                address should be sent to provider. Ignored for payments in |tg_stars|.
            is_flexible (:obj:`bool`, optional): Pass :obj:`True`, if the final price depends on
                the shipping method. Ignored for payments in |tg_stars|.

        Returns:
            :class:`str`: On success, the created invoice link is returned.

        """
        data: JSONDict = {
            "title": title,
            "description": description,
            "payload": payload,
            "provider_token": provider_token,
            "currency": currency,
            "prices": prices,
            "max_tip_amount": max_tip_amount,
            "suggested_tip_amounts": suggested_tip_amounts,
            "provider_data": provider_data,
            "photo_url": photo_url,
            "photo_size": photo_size,
            "photo_width": photo_width,
            "photo_height": photo_height,
            "need_name": need_name,
            "need_phone_number": need_phone_number,
            "need_email": need_email,
            "need_shipping_address": need_shipping_address,
            "is_flexible": is_flexible,
            "send_phone_number_to_provider": send_phone_number_to_provider,
            "send_email_to_provider": send_email_to_provider,
            "subscription_period": subscription_period,
            "business_connection_id": business_connection_id,
        }

        return await self._post(
            "createInvoiceLink",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_forum_topic_icon_stickers(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> tuple[Sticker, ...]:
        """Use this method to get custom emoji stickers, which can be used as a forum topic
        icon by any user. Requires no parameters.

        .. versionadded:: 20.0

        Returns:
            tuple[:class:`telegram.Sticker`]

        Raises:
            :class:`telegram.error.TelegramError`

        """
        result = await self._post(
            "getForumTopicIconStickers",
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return Sticker.de_list(result, self)

    async def create_forum_topic(
        self,
        chat_id: str | int,
        name: str,
        icon_color: int | None = None,
        icon_custom_emoji_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ForumTopic:
        """
        Use this method to create a topic in a forum supergroup chat. The bot must be
        an administrator in the chat for this to work and must have
        :paramref:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            name (:obj:`str`): New topic name,
                :tg-const:`telegram.constants.ForumTopicLimit.MIN_NAME_LENGTH`-
                :tg-const:`telegram.constants.ForumTopicLimit.MAX_NAME_LENGTH` characters.
            icon_color (:obj:`int`, optional): Color of the topic icon in RGB format. Currently,
                must be one of :attr:`telegram.constants.ForumIconColor.BLUE`,
                :attr:`telegram.constants.ForumIconColor.YELLOW`,
                :attr:`telegram.constants.ForumIconColor.PURPLE`,
                :attr:`telegram.constants.ForumIconColor.GREEN`,
                :attr:`telegram.constants.ForumIconColor.PINK`, or
                :attr:`telegram.constants.ForumIconColor.RED`.
            icon_custom_emoji_id (:obj:`str`, optional): New unique identifier of the custom emoji
                shown as the topic icon. Use :meth:`~telegram.Bot.get_forum_topic_icon_stickers`
                to get all allowed custom emoji identifiers.

        Returns:
            :class:`telegram.ForumTopic`

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "chat_id": chat_id,
            "name": name,
            "icon_color": icon_color,
            "icon_custom_emoji_id": icon_custom_emoji_id,
        }
        result = await self._post(
            "createForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return ForumTopic.de_json(result, self)

    async def edit_forum_topic(
        self,
        chat_id: str | int,
        message_thread_id: int,
        name: str | None = None,
        icon_custom_emoji_id: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to edit name and icon of a topic in a forum supergroup chat or a private
        chat with a user. In the case of a supergroup chat the bot must be an administrator in the
        chat for this to work and must have the
        :paramref:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights,
        unless it is the creator of the topic.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            message_thread_id (:obj:`int`): |message_thread_id|
            name (:obj:`str`, optional): New topic name,
                :tg-const:`telegram.constants.ForumTopicLimit.MIN_NAME_LENGTH`-
                :tg-const:`telegram.constants.ForumTopicLimit.MAX_NAME_LENGTH` characters. If
                not specified or empty, the current name of the topic will be kept.
            icon_custom_emoji_id (:obj:`str`, optional): New unique identifier of the custom emoji
                shown as the topic icon. Use :meth:`~telegram.Bot.get_forum_topic_icon_stickers`
                to get all allowed custom emoji identifiers.Pass an empty string to remove the
                icon. If not specified, the current icon will be kept.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
            "name": name,
            "icon_custom_emoji_id": icon_custom_emoji_id,
        }
        return await self._post(
            "editForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def close_forum_topic(
        self,
        chat_id: str | int,
        message_thread_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to close an open topic in a forum supergroup chat. The bot must
        be an administrator in the chat for this to work and must have
        :paramref:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights,
        unless it is the creator of the topic.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            message_thread_id (:obj:`int`): |message_thread_id|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
        }
        return await self._post(
            "closeForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def reopen_forum_topic(
        self,
        chat_id: str | int,
        message_thread_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to reopen a closed topic in a forum supergroup chat. The bot must
        be an administrator in the chat for this to work and must have
        :paramref:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights,
        unless it is the creator of the topic.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            message_thread_id (:obj:`int`): |message_thread_id|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
        }
        return await self._post(
            "reopenForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_forum_topic(
        self,
        chat_id: str | int,
        message_thread_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to delete a forum topic along with all its messages in a forum supergroup
        chat or a private chat with a user. In the case of a supergroup chat the bot must be an
        administrator in the chat for this to work and must have the
        :paramref:`~telegram.ChatAdministratorRights.can_delete_messages` administrator rights.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            message_thread_id (:obj:`int`): |message_thread_id|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
        }
        return await self._post(
            "deleteForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin_all_forum_topic_messages(
        self,
        chat_id: str | int,
        message_thread_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to clear the list of pinned messages in a forum topic in a forum supergroup
        chat or a private chat with a user. In the case of a supergroup chat the bot must be an
        administrator in the chat for this to work and must have the
        :paramref:`~telegram.ChatAdministratorRights.can_pin_messages` administrator right in
        the supergroup.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            message_thread_id (:obj:`int`): |message_thread_id|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
        }
        return await self._post(
            "unpinAllForumTopicMessages",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unpin_all_general_forum_topic_messages(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to clear the list of pinned messages in a General forum topic. The bot must
        be an administrator in the chat for this to work and must have
        :paramref:`~telegram.ChatAdministratorRights.can_pin_messages` administrator rights in the
        supergroup.

        .. versionadded:: 20.5

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"chat_id": chat_id}

        return await self._post(
            "unpinAllGeneralForumTopicMessages",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def edit_general_forum_topic(
        self,
        chat_id: str | int,
        name: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to edit the name of the 'General' topic in a forum supergroup chat. The bot
        must be an administrator in the chat for this to work and must have the
        :attr:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|
            name (:obj:`str`): New topic name,
                :tg-const:`telegram.constants.ForumTopicLimit.MIN_NAME_LENGTH`-
                :tg-const:`telegram.constants.ForumTopicLimit.MAX_NAME_LENGTH` characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id, "name": name}

        return await self._post(
            "editGeneralForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def close_general_forum_topic(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to close an open 'General' topic in a forum supergroup chat. The bot must
        be an administrator in the chat for this to work and must have
        :attr:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}

        return await self._post(
            "closeGeneralForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def reopen_general_forum_topic(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to reopen a closed 'General' topic in a forum supergroup chat. The bot must
        be an administrator in the chat for this to work and must have
        :attr:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights.
        The topic will be automatically unhidden if it was hidden.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}

        return await self._post(
            "reopenGeneralForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def hide_general_forum_topic(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to hide the 'General' topic in a forum supergroup chat. The bot must
        be an administrator in the chat for this to work and must have
        :attr:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights.
        The topic will be automatically closed if it was open.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}

        return await self._post(
            "hideGeneralForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def unhide_general_forum_topic(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to unhide the 'General' topic in a forum supergroup chat. The bot must
        be an administrator in the chat for this to work and must have
        :attr:`~telegram.ChatAdministratorRights.can_manage_topics` administrator rights.

        .. versionadded:: 20.0

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_group|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"chat_id": chat_id}

        return await self._post(
            "unhideGeneralForumTopic",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_my_description(
        self,
        description: str | None = None,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the bot's description, which is shown in the chat with the bot
        if the chat is empty.

        .. versionadded:: 20.2

        Args:
            description (:obj:`str`, optional): New bot description;
                0-:tg-const:`telegram.constants.BotDescriptionLimit.MAX_DESCRIPTION_LENGTH`
                characters. Pass an empty string to remove the dedicated description for the given
                language.
            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code. If empty,
                the description will be applied to all users for whose language there is no
                dedicated description.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"description": description, "language_code": language_code}

        return await self._post(
            "setMyDescription",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_my_short_description(
        self,
        short_description: str | None = None,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the bot's short description, which is shown on the bot's profile
        page and is sent together with the link when users share the bot.

        .. versionadded:: 20.2

        Args:
            short_description (:obj:`str`, optional): New short description for the bot;
                0-:tg-const:`telegram.constants.BotDescriptionLimit.MAX_SHORT_DESCRIPTION_LENGTH`
                characters. Pass an empty string to remove the dedicated description for the given
                language.
            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code. If empty,
                the description will be applied to all users for whose language there is no
                dedicated description.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"short_description": short_description, "language_code": language_code}

        return await self._post(
            "setMyShortDescription",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_my_description(
        self,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> BotDescription:
        """
        Use this method to get the current bot description for the given user language.

        Args:
            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code or an empty
                string.

        Returns:
            :class:`telegram.BotDescription`: On success, the bot description is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data = {"language_code": language_code}
        return BotDescription.de_json(
            await self._post(
                "getMyDescription",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            bot=self,
        )

    async def get_my_short_description(
        self,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> BotShortDescription:
        """
        Use this method to get the current bot short description for the given user language.

        Args:
            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code or an empty
                string.

        Returns:
            :class:`telegram.BotShortDescription`: On success, the bot short description is
                returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data = {"language_code": language_code}
        return BotShortDescription.de_json(
            await self._post(
                "getMyShortDescription",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            bot=self,
        )

    async def set_my_name(
        self,
        name: str | None = None,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the bot's name.

        .. versionadded:: 20.3

        Args:
            name (:obj:`str`, optional): New bot name;
                0-:tg-const:`telegram.constants.BotNameLimit.MAX_NAME_LENGTH`
                characters. Pass an empty string to remove the dedicated name for the given
                language.

                Caution:
                    If :paramref:`language_code` is not specified, a :paramref:`name` *must*
                    be specified.
            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code. If empty,
                the name will be applied to all users for whose language there is no
                dedicated name.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {"name": name, "language_code": language_code}

        return await self._post(
            "setMyName",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_my_name(
        self,
        language_code: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> BotName:
        """
        Use this method to get the current bot name for the given user language.

        Args:
            language_code (:obj:`str`, optional): A two-letter ISO 639-1 language code or an empty
                string.

        Returns:
            :class:`telegram.BotName`: On success, the bot name is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data = {"language_code": language_code}
        return BotName.de_json(
            await self._post(
                "getMyName",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            bot=self,
        )

    async def get_user_chat_boosts(
        self,
        chat_id: str | int,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> UserChatBoosts:
        """
        Use this method to get the list of boosts added to a chat by a user. Requires
        administrator rights in the chat.

        .. versionadded:: 20.8

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            user_id (:obj:`int`): Unique identifier of the target user.

        Returns:
            :class:`telegram.UserChatBoosts`: On success, the object containing the list of boosts
                is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"chat_id": chat_id, "user_id": user_id}
        return UserChatBoosts.de_json(
            await self._post(
                "getUserChatBoosts",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            bot=self,
        )

    async def set_message_reaction(
        self,
        chat_id: str | int,
        message_id: int,
        reaction: Sequence[ReactionType | str] | ReactionType | str | None = None,
        is_big: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to change the chosen reactions on a message. Service messages of some types
        can't be
        reacted to. Automatically forwarded messages from a channel to its discussion group have
        the same available reactions as messages in the channel. Bots can't use paid reactions.

        .. versionadded:: 20.8

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            message_id (:obj:`int`): Identifier of the target message. If the message belongs to a
                media group, the reaction is set to the first non-deleted message in the group
                instead.
            reaction (Sequence[:class:`telegram.ReactionType` | :obj:`str`] | \
                :class:`telegram.ReactionType` | :obj:`str`, optional): A list of reaction
                types to set on the message. Currently, as non-premium users, bots can set up to
                one reaction per message. A custom emoji reaction can be used if it is either
                already present on the message or explicitly allowed by chat administrators. Paid
                reactions can't be used by bots.

                Tip:
                    Passed :obj:`str` values will be converted to either
                    :class:`telegram.ReactionTypeEmoji` or
                    :class:`telegram.ReactionTypeCustomEmoji`
                    depending on whether they are listed in
                    :class:`~telegram.constants.ReactionEmoji`.

            is_big (:obj:`bool`, optional): Pass :obj:`True` to set the reaction with a big
                animation.

        Returns:
            :obj:`bool` On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        allowed_reactions: set[str] = set(ReactionEmoji)
        parsed_reaction = (
            [
                (
                    entry
                    if isinstance(entry, ReactionType)
                    else (
                        ReactionTypeEmoji(emoji=entry)
                        if entry in allowed_reactions
                        else ReactionTypeCustomEmoji(custom_emoji_id=entry)
                    )
                )
                for entry in ([reaction] if isinstance(reaction, ReactionType | str) else reaction)
            ]
            if reaction is not None
            else None
        )

        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": parsed_reaction,
            "is_big": is_big,
        }

        return await self._post(
            "setMessageReaction",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def gift_premium_subscription(
        self,
        user_id: int,
        month_count: int,
        star_count: int,
        text: str | None = None,
        text_parse_mode: ODVInput[str] = DEFAULT_NONE,
        text_entities: Sequence["MessageEntity"] | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Gifts a Telegram Premium subscription to the given user.

        .. versionadded:: 22.1

        Args:
            user_id (:obj:`int`): Unique identifier of the target user who will receive a Telegram
                Premium subscription.
            month_count (:obj:`int`): Number of months the Telegram Premium subscription will be
                active for the user; must be one of
                :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_THREE`,
                :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_SIX`,
                or :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_TWELVE`.
            star_count (:obj:`int`): Number of Telegram Stars to pay for the Telegram Premium
               subscription; must be
               :tg-const:`telegram.constants.PremiumSubscription.STARS_THREE_MONTHS`
               for :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_THREE` months,
               :tg-const:`telegram.constants.PremiumSubscription.STARS_SIX_MONTHS`
               for :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_SIX` months,
               and :tg-const:`telegram.constants.PremiumSubscription.STARS_TWELVE_MONTHS`
               for :tg-const:`telegram.constants.PremiumSubscription.MONTH_COUNT_TWELVE` months.
            text (:obj:`str`, optional): Text that will be shown along with the service message
                about the subscription;
                0-:tg-const:`telegram.constants.PremiumSubscription.MAX_TEXT_LENGTH` characters.
            text_parse_mode (:obj:`str`, optional): Mode for parsing entities.
                See :class:`telegram.constants.ParseMode` and
                `formatting options <https://core.telegram.org/bots/api#formatting-options>`__ for
                more details. Entities other than :attr:`~MessageEntity.BOLD`,
                :attr:`~MessageEntity.ITALIC`, :attr:`~MessageEntity.UNDERLINE`,
                :attr:`~MessageEntity.STRIKETHROUGH`, :attr:`~MessageEntity.SPOILER`, and
                :attr:`~MessageEntity.CUSTOM_EMOJI` are ignored.
            text_entities (Sequence[:class:`telegram.MessageEntity`], optional): A list of special
                entities that appear in the gift text. It can be specified instead of
                :paramref:`text_parse_mode`. Entities other than :attr:`~MessageEntity.BOLD`,
                :attr:`~MessageEntity.ITALIC`, :attr:`~MessageEntity.UNDERLINE`,
                :attr:`~MessageEntity.STRIKETHROUGH`, :attr:`~MessageEntity.SPOILER`, and
                :attr:`~MessageEntity.CUSTOM_EMOJI` are ignored.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
            "month_count": month_count,
            "star_count": star_count,
            "text": text,
            "text_entities": text_entities,
            "text_parse_mode": text_parse_mode,
        }
        return await self._post(
            "giftPremiumSubscription",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_business_connection(
        self,
        business_connection_id: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> BusinessConnection:
        """
        Use this method to get information about the connection of the bot with a business account.

        .. versionadded:: 21.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.

        Returns:
            :class:`telegram.BusinessConnection`: On success, the object containing the business
                connection information is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"business_connection_id": business_connection_id}
        return BusinessConnection.de_json(
            await self._post(
                "getBusinessConnection",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            bot=self,
        )

    async def get_business_account_gifts(
        self,
        business_connection_id: str,
        exclude_unsaved: bool | None = None,
        exclude_saved: bool | None = None,
        exclude_unlimited: bool | None = None,
        # tags: deprecated 22.6; bot api 9.3
        exclude_limited: bool | None = None,
        exclude_unique: bool | None = None,
        sort_by_price: bool | None = None,
        offset: str | None = None,
        limit: int | None = None,
        exclude_limited_upgradable: bool | None = None,
        exclude_limited_non_upgradable: bool | None = None,
        exclude_from_blockchain: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> OwnedGifts:
        """
        Returns the gifts received and owned by a managed business account. Requires the
        :attr:`~telegram.BusinessBotRights.can_view_gifts_and_stars` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.
            exclude_unsaved (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that aren't
                saved to the account's profile page.
            exclude_saved (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that are saved
                to the account's profile page.
            exclude_unlimited (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that can
                be purchased an unlimited number of times.
            exclude_limited (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that can be
                purchased a limited number of times.

                .. deprecated:: 22.6
                    Bot API 9.3 deprecated this parameter in favor of
                    :paramref:`exclude_limited_upgradabale` and
                    :paramref:`exclude_limited_non_upgradable`.
            exclude_limited_upgradable (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts
                that can be purchased a limited number of times and can be upgraded to unique.

                .. versionadded:: 22.6
            exclude_limited_non_upgradable (:obj:`bool`, optional): Pass :obj:`True` to exclude
                gifts that can be purchased a limited number of times and can't be upgraded to
                unique

                .. versionadded:: 22.6
            exclude_unique (:obj:`bool`, optional): Pass :obj:`True` to exclude unique gifts.
            exclude_from_blockchain (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts
                that were assigned from the TON blockchain and can't be resold or transferred in
                Telegram.

                .. versionadded:: 22.6
            sort_by_price (:obj:`bool`, optional): Pass :obj:`True` to sort results by gift price
                instead of send date. Sorting is applied before pagination.
            offset (:obj:`str`, optional): Offset of the first entry to return as received from
                the previous request; use empty string to get the first chunk of results.
            limit (:obj:`int`, optional): The maximum number of gifts to be returned;
                :tg-const:`telegram.constants.BusinessLimit.MIN_GIFT_RESULTS`-\
                :tg-const:`telegram.constants.BusinessLimit.MAX_GIFT_RESULTS`.
                Defaults to :tg-const:`telegram.constants.BusinessLimit.MAX_GIFT_RESULTS`.

        Returns:
            :class:`telegram.OwnedGifts`

        Raises:
            :class:`telegram.error.TelegramError`
        """
        if exclude_limited is not None:
            self._warn(
                PTBDeprecationWarning(
                    version="22.6",
                    message=build_deprecation_warning_message(
                        deprecated_name="exclude_limited",
                        new_name="exclude_limited_(non_)upgradable",
                        bot_api_version="9.3",
                        object_type="parameter",
                    ),
                ),
                stacklevel=2,
            )
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "exclude_unsaved": exclude_unsaved,
            "exclude_saved": exclude_saved,
            "exclude_unlimited": exclude_unlimited,
            "exclude_limited": exclude_limited,
            "exclude_limited_upgradable": exclude_limited_upgradable,
            "exclude_limited_non_upgradable": exclude_limited_non_upgradable,
            "exclude_unique": exclude_unique,
            "exclude_from_blockchain": exclude_from_blockchain,
            "sort_by_price": sort_by_price,
            "offset": offset,
            "limit": limit,
        }

        return OwnedGifts.de_json(
            await self._post(
                "getBusinessAccountGifts",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            )
        )

    async def get_business_account_star_balance(
        self,
        business_connection_id: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> StarAmount:
        """
        Returns the amount of Telegram Stars owned by a managed business account. Requires the
        :attr:`~telegram.BusinessBotRights.can_view_gifts_and_stars` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.

        Returns:
            :class:`telegram.StarAmount`

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {"business_connection_id": business_connection_id}
        return StarAmount.de_json(
            await self._post(
                "getBusinessAccountStarBalance",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            bot=self,
        )

    async def read_business_message(
        self,
        business_connection_id: str,
        chat_id: int,
        message_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Marks incoming message as read on behalf of a business account.
        Requires the :attr:`~telegram.BusinessBotRights.can_read_messages` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection on
                behalf of which to read the message.
            chat_id (:obj:`int`): Unique identifier of the chat in which the message was received.
                The chat must have been active in the last
                :tg-const:`~telegram.constants.BusinessLimit.\
CHAT_ACTIVITY_TIMEOUT` seconds.
            message_id (:obj:`int`): Unique identifier of the message to mark as read.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "chat_id": chat_id,
            "message_id": message_id,
        }
        return await self._post(
            "readBusinessMessage",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def delete_business_messages(
        self,
        business_connection_id: str,
        message_ids: Sequence[int],
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Delete messages on behalf of a business account. Requires the
        :attr:`~telegram.BusinessBotRights.can_delete_sent_messages` business bot right to
        delete messages sent by the bot itself, or the
        :attr:`~telegram.BusinessBotRights.can_delete_all_messages` business bot right to delete
        any message.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`int` | :obj:`str`): Unique identifier of the business
                connection on behalf of which to delete the messages
            message_ids (Sequence[:obj:`int`]):  A list of
                :tg-const:`telegram.constants.BulkRequestLimit.MIN_LIMIT`-
                :tg-const:`telegram.constants.BulkRequestLimit.MAX_LIMIT` identifiers of messages
                to delete. See :meth:`delete_message` for limitations on which messages can be
                deleted.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "message_ids": message_ids,
        }
        return await self._post(
            "deleteBusinessMessages",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def post_story(
        self,
        business_connection_id: str,
        content: "InputStoryContent",
        active_period: TimePeriod,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        areas: Sequence["StoryArea"] | None = None,
        post_to_chat_page: bool | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Story:
        """
        Posts a story on behalf of a managed business account. Requires the
        :attr:`~telegram.BusinessBotRights.can_manage_stories` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.
            content (:class:`telegram.InputStoryContent`): Content of the story.
            active_period (:obj:`int` | :class:`datetime.timedelta`, optional): Period after which
                the story is moved to the archive, in seconds; must be one of
                :tg-const:`~telegram.constants.StoryLimit.ACTIVITY_SIX_HOURS`,
                :tg-const:`~telegram.constants.StoryLimit.ACTIVITY_TWELVE_HOURS`,
                :tg-const:`~telegram.constants.StoryLimit.ACTIVITY_ONE_DAY`,
                or :tg-const:`~telegram.constants.StoryLimit.ACTIVITY_TWO_DAYS`.
            caption (:obj:`str`, optional): Caption of the story,
                0-:tg-const:`~telegram.constants.StoryLimit.CAPTION_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`, optional): Mode for parsing entities in the story caption.
                See the constants in :class:`telegram.constants.ParseMode` for the
                available modes.
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|
            areas (Sequence[:class:`telegram.StoryArea`], optional): Sequence of clickable areas to
                be shown on the story.

                Note:
                    Each type of clickable area in :paramref:`areas` has its own maximum limit:

                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_LOCATION_AREAS`
                      of :class:`telegram.StoryAreaTypeLocation`.
                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.\
MAX_SUGGESTED_REACTION_AREAS` of :class:`telegram.StoryAreaTypeSuggestedReaction`.
                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_LINK_AREAS`
                      of :class:`telegram.StoryAreaTypeLink`.
                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_WEATHER_AREAS`
                      of :class:`telegram.StoryAreaTypeWeather`.
                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.\
MAX_UNIQUE_GIFT_AREAS` of :class:`telegram.StoryAreaTypeUniqueGift`.
            post_to_chat_page (:class:`telegram.InputStoryContent`, optional): Pass :obj:`True` to
                keep the story accessible after it expires.
            protect_content (:obj:`bool`, optional): Pass :obj:`True` if the content of the story
                must be protected from forwarding and screenshotting

        Returns:
            :class:`Story`

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "content": content,
            "active_period": active_period,
            "caption": caption,
            "parse_mode": parse_mode,
            "caption_entities": caption_entities,
            "areas": areas,
            "post_to_chat_page": post_to_chat_page,
            "protect_content": protect_content,
        }
        return Story.de_json(
            await self._post(
                "postStory",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            )
        )

    async def edit_story(
        self,
        business_connection_id: str,
        story_id: int,
        content: "InputStoryContent",
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        areas: Sequence["StoryArea"] | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Story:
        """
        Edits a story previously posted by the bot on behalf of a managed business account.
        Requires the :attr:`~telegram.BusinessBotRights.can_manage_stories` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.
            story_id (:obj:`int`): Unique identifier of the story to edit.
            content (:class:`telegram.InputStoryContent`): Content of the story.
            caption (:obj:`str`, optional): Caption of the story,
                0-:tg-const:`~telegram.constants.StoryLimit.CAPTION_LENGTH` characters after
                entities parsing.
            parse_mode (:obj:`str`, optional): Mode for parsing entities in the story caption.
                See the constants in :class:`telegram.constants.ParseMode` for the
                available modes.
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|
            areas (Sequence[:class:`telegram.StoryArea`], optional): Sequence of clickable areas to
                be shown on the story.

                Note:
                    Each type of clickable area in :paramref:`areas` has its own maximum limit:

                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_LOCATION_AREAS`
                      of :class:`telegram.StoryAreaTypeLocation`.
                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.\
MAX_SUGGESTED_REACTION_AREAS` of :class:`telegram.StoryAreaTypeSuggestedReaction`.
                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_LINK_AREAS`
                      of :class:`telegram.StoryAreaTypeLink`.
                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.MAX_WEATHER_AREAS`
                      of :class:`telegram.StoryAreaTypeWeather`.
                    * Up to :tg-const:`~telegram.constants.StoryAreaTypeLimit.\
MAX_UNIQUE_GIFT_AREAS` of :class:`telegram.StoryAreaTypeUniqueGift`.

        Returns:
            :class:`Story`

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "story_id": story_id,
            "content": content,
            "caption": caption,
            "parse_mode": parse_mode,
            "caption_entities": caption_entities,
            "areas": areas,
        }
        return Story.de_json(
            await self._post(
                "editStory",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            )
        )

    async def delete_story(
        self,
        business_connection_id: str,
        story_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Deletes a story previously posted by the bot on behalf of a managed business account.
        Requires the :attr:`~telegram.BusinessBotRights.can_manage_stories` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.
            story_id (:obj:`int`): Unique identifier of the story to delete.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "story_id": story_id,
        }
        return await self._post(
            "deleteStory",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_business_account_name(
        self,
        business_connection_id: str,
        first_name: str,
        last_name: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Changes the first and last name of a managed business account. Requires the
        :attr:`~telegram.BusinessBotRights.can_edit_name` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`int` | :obj:`str`): Unique identifier of the business
                connection
            first_name (:obj:`str`): New first name of the business account;
                :tg-const:`telegram.constants.BusinessLimit.MIN_NAME_LENGTH`-
                :tg-const:`telegram.constants.BusinessLimit.MAX_NAME_LENGTH` characters.
            last_name (:obj:`str`, optional): New last name of the business account;
                0-:tg-const:`telegram.constants.BusinessLimit.MAX_NAME_LENGTH` characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "first_name": first_name,
            "last_name": last_name,
        }
        return await self._post(
            "setBusinessAccountName",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_business_account_username(
        self,
        business_connection_id: str,
        username: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Changes the username of a managed business account. Requires the
        :attr:`~telegram.BusinessBotRights.can_edit_username` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.
            username (:obj:`str`, optional): New business account username;
                0-:tg-const:`telegram.constants.BusinessLimit.MAX_USERNAME_LENGTH` characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "username": username,
        }
        return await self._post(
            "setBusinessAccountUsername",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_business_account_bio(
        self,
        business_connection_id: str,
        bio: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Changes the bio of a managed business account. Requires the
        :attr:`~telegram.BusinessBotRights.can_edit_bio` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.
            bio (:obj:`str`, optional): The new value of the bio for the business account;
                0-:tg-const:`telegram.constants.BusinessLimit.MAX_BIO_LENGTH` characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "bio": bio,
        }
        return await self._post(
            "setBusinessAccountBio",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_business_account_gift_settings(
        self,
        business_connection_id: str,
        show_gift_button: bool,
        accepted_gift_types: AcceptedGiftTypes,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Changes the privacy settings pertaining to incoming gifts in a managed business account.
        Requires the :attr:`~telegram.BusinessBotRights.can_change_gift_settings` business
        bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business
                connection
            show_gift_button (:obj:`bool`): Pass :obj:`True`, if a button for sending a gift to the
                user or by the business account must always be shown in the input field.
            accepted_gift_types (:class:`telegram.AcceptedGiftTypes`): Types of gifts accepted by
                the business account.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "show_gift_button": show_gift_button,
            "accepted_gift_types": accepted_gift_types,
        }
        return await self._post(
            "setBusinessAccountGiftSettings",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def set_business_account_profile_photo(
        self,
        business_connection_id: str,
        photo: "InputProfilePhoto",
        is_public: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Changes the profile photo of a managed business account.
        Requires the :attr:`~telegram.BusinessBotRights.can_edit_profile_photo` business
        bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.
            photo (:class:`telegram.InputProfilePhoto`): The new profile photo to set.
            is_public (:obj:`bool`, optional): Pass :obj:`True` to set the public photo, which will
                be visible even if the main photo is hidden by the business account's privacy
                settings. An account can have only one public photo.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "photo": photo,
            "is_public": is_public,
        }
        return await self._post(
            "setBusinessAccountProfilePhoto",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def remove_business_account_profile_photo(
        self,
        business_connection_id: str,
        is_public: bool | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Removes the current profile photo of a managed business account.
        Requires the :attr:`~telegram.BusinessBotRights.can_edit_profile_photo` business
        bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business connection.
            is_public (:obj:`bool`, optional): Pass :obj:`True` to remove the public photo, which
                will be visible even if the main photo is hidden by the business account's privacy
                settings. After the main photo is removed, the previous profile photo (if present)
                becomes the main photo.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "is_public": is_public,
        }
        return await self._post(
            "removeBusinessAccountProfilePhoto",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def convert_gift_to_stars(
        self,
        business_connection_id: str,
        owned_gift_id: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Converts a given regular gift to Telegram Stars. Requires the
        :attr:`~telegram.BusinessBotRights.can_convert_gifts_to_stars` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business
                connection
            owned_gift_id (:obj:`str`): Unique identifier of the regular gift that should be
                converted to Telegram Stars.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "owned_gift_id": owned_gift_id,
        }
        return await self._post(
            "convertGiftToStars",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def upgrade_gift(
        self,
        business_connection_id: str,
        owned_gift_id: str,
        keep_original_details: bool | None = None,
        star_count: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Upgrades a given regular gift to a unique gift. Requires the
        :attr:`~telegram.BusinessBotRights.can_transfer_and_upgrade_gifts` business bot right.
        Additionally requires the :attr:`~telegram.BusinessBotRights.can_transfer_stars` business
        bot right if the upgrade is paid.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business
                connection
            owned_gift_id (:obj:`str`): Unique identifier of the regular gift that should be
                upgraded to a unique one.
            keep_original_details (:obj:`bool`, optional): Pass :obj:`True` to keep the original
                gift text, sender and receiver in the upgraded gift
            star_count (:obj:`int`, optional): The amount of Telegram Stars that will
                be paid for the upgrade from the business account balance. If
                ``gift.prepaid_upgrade_star_count > 0``, then pass ``0``, otherwise,
                the :attr:`~telegram.BusinessBotRights.can_transfer_stars`
                business bot right is required and :attr:`telegram.Gift.upgrade_star_count`
                must be passed.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "owned_gift_id": owned_gift_id,
            "keep_original_details": keep_original_details,
            "star_count": star_count,
        }
        return await self._post(
            "upgradeGift",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def transfer_gift(
        self,
        business_connection_id: str,
        owned_gift_id: str,
        new_owner_chat_id: int,
        star_count: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Transfers an owned unique gift to another user. Requires the
        :attr:`~telegram.BusinessBotRights.can_transfer_and_upgrade_gifts` business bot right.
        Requires :attr:`~telegram.BusinessBotRights.can_transfer_stars` business bot right if the
        transfer is paid.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business
                connection
            owned_gift_id (:obj:`str`): Unique identifier of the regular gift that should be
                transferred.
            new_owner_chat_id (:obj:`int`): Unique identifier of the chat which will
                own the gift. The chat must be active in the last
                :tg-const:`~telegram.constants.BusinessLimit.\
CHAT_ACTIVITY_TIMEOUT` seconds.
            star_count (:obj:`int`, optional): The amount of Telegram Stars that will be paid for
                the transfer from the business account balance. If positive, then
                the :attr:`~telegram.BusinessBotRights.can_transfer_stars` business bot
                right is required.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "owned_gift_id": owned_gift_id,
            "new_owner_chat_id": new_owner_chat_id,
            "star_count": star_count,
        }
        return await self._post(
            "transferGift",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def transfer_business_account_stars(
        self,
        business_connection_id: str,
        star_count: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Transfers Telegram Stars from the business account balance to the bot's balance. Requires
        the :attr:`~telegram.BusinessBotRights.can_transfer_stars` business bot right.

        .. versionadded:: 22.1

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business
                connection
            star_count (:obj:`int`): Number of Telegram Stars to transfer;
                :tg-const:`~telegram.constants.BusinessLimit.MIN_STAR_COUNT`\
-:tg-const:`~telegram.constants.BusinessLimit.MAX_STAR_COUNT`

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "star_count": star_count,
        }
        return await self._post(
            "transferBusinessAccountStars",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def replace_sticker_in_set(
        self,
        user_id: int,
        name: str,
        old_sticker: "str | Sticker",
        sticker: "InputSticker",
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Use this method to replace an existing sticker in a sticker set with a new one.
        The method is equivalent to calling :meth:`delete_sticker_from_set`,
        then :meth:`add_sticker_to_set`, then :meth:`set_sticker_position_in_set`.

        .. versionadded:: 21.1

        Args:
            user_id (:obj:`int`): User identifier of the sticker set owner.
            name (:obj:`str`): Sticker set name.
            old_sticker (:obj:`str` | :class:`~telegram.Sticker`): File identifier of the replaced
                sticker or the sticker object itself.

                .. versionchanged:: 21.10
                   Accepts also :class:`telegram.Sticker` instances.
            sticker (:class:`telegram.InputSticker`): An object with information about the added
                sticker. If exactly the same sticker had already been added to the set, then the
                set remains unchanged.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
            "name": name,
            "old_sticker": old_sticker if isinstance(old_sticker, str) else old_sticker.file_id,
            "sticker": sticker,
        }

        return await self._post(
            "replaceStickerInSet",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def refund_star_payment(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Refunds a successful payment in |tg_stars|.

        .. versionadded:: 21.3

        Args:
            user_id (:obj:`int`): User identifier of the user whose payment will be refunded.
            telegram_payment_charge_id (:obj:`str`): Telegram payment identifier.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "user_id": user_id,
            "telegram_payment_charge_id": telegram_payment_charge_id,
        }

        return await self._post(
            "refundStarPayment",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_star_transactions(
        self,
        offset: int | None = None,
        limit: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> StarTransactions:
        """Returns the bot's Telegram Star transactions in chronological order.

        .. versionadded:: 21.4

        Args:
            offset (:obj:`int`, optional): Number of transactions to skip in the response.
            limit (:obj:`int`, optional): The maximum number of transactions to be retrieved.
                Values between :tg-const:`telegram.constants.StarTransactionsLimit.MIN_LIMIT`-
                :tg-const:`telegram.constants.StarTransactionsLimit.MAX_LIMIT` are accepted.
                Defaults to :tg-const:`telegram.constants.StarTransactionsLimit.MAX_LIMIT`.

        Returns:
            :class:`telegram.StarTransactions`: On success.

        Raises:
            :class:`telegram.error.TelegramError`
        """

        data: JSONDict = {"offset": offset, "limit": limit}

        return StarTransactions.de_json(
            await self._post(
                "getStarTransactions",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            bot=self,
        )

    async def edit_user_star_subscription(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        is_canceled: bool,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Allows the bot to cancel or re-enable extension of a subscription paid in Telegram
        Stars.

        .. versionadded:: 21.8

        Args:
            user_id (:obj:`int`): Identifier of the user whose subscription will be edited.
            telegram_payment_charge_id (:obj:`str`): Telegram payment identifier for the
                subscription.
            is_canceled (:obj:`bool`): Pass :obj:`True` to cancel extension of the user
                subscription; the subscription must be active up to the end of the current
                subscription period. Pass :obj:`False` to allow the user to re-enable a
                subscription that was previously canceled by the bot.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
            "telegram_payment_charge_id": telegram_payment_charge_id,
            "is_canceled": is_canceled,
        }
        return await self._post(
            "editUserStarSubscription",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def send_paid_media(
        self,
        chat_id: str | int,
        star_count: int,
        media: Sequence["InputPaidMedia"],
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        show_caption_above_media: bool | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        reply_markup: "ReplyMarkup | None" = None,
        business_connection_id: str | None = None,
        payload: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_thread_id: int | None = None,
        *,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        reply_to_message_id: int | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Message:
        """Use this method to send paid media.

        .. versionadded:: 21.4

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel| If the chat is a channel, all
                Telegram Star proceeds from this media will be credited to the chat's balance.
                Otherwise, they will be credited to the bot's balance.
            star_count (:obj:`int`): The number of Telegram Stars that must be paid to buy access
                to the media; :tg-const:`telegram.constants.InvoiceLimit.MIN_STAR_COUNT` -
                :tg-const:`telegram.constants.InvoiceLimit.MAX_STAR_COUNT`.
            media (Sequence[:class:`telegram.InputPaidMedia`]): A list describing the media to be
                sent; up to :tg-const:`telegram.constants.MediaGroupLimit.MAX_MEDIA_LENGTH` items.
            payload (:obj:`str`, optional): Bot-defined paid media payload,
                0-:tg-const:`telegram.constants.InvoiceLimit.MAX_PAYLOAD_LENGTH` bytes. This will
                not be displayed to the user, use it for your internal processes.

                .. versionadded:: 21.6
            caption (:obj:`str`, optional): Caption of the media to be sent,
                0-:tg-const:`telegram.constants.MessageLimit.CAPTION_LENGTH` characters.
            parse_mode (:obj:`str`, optional): |parse_mode|
            caption_entities (Sequence[:class:`telegram.MessageEntity`], optional):
                |caption_entities|
            show_caption_above_media (:obj:`bool`, optional): Pass |show_cap_above_med|
            disable_notification (:obj:`bool`, optional): |disable_notification|
            protect_content (:obj:`bool`, optional): |protect_content|
            reply_parameters (:class:`telegram.ReplyParameters`, optional): |reply_parameters|
            reply_markup (:class:`InlineKeyboardMarkup` | :class:`ReplyKeyboardMarkup` | \
                :class:`ReplyKeyboardRemove` | :class:`ForceReply`, optional):
                Additional interface options. An object for an inline keyboard, custom reply
                keyboard, instructions to remove reply keyboard or to force a reply from the user.
            business_connection_id (:obj:`str`, optional): |business_id_str|

                .. versionadded:: 21.5
            allow_paid_broadcast (:obj:`bool`, optional): |allow_paid_broadcast|

                .. versionadded:: 21.7
            suggested_post_parameters (:class:`telegram.SuggestedPostParameters`, optional):
                |suggested_post_parameters|

                .. versionadded:: 22.4
            direct_messages_topic_id (:obj:`int`, optional): |direct_messages_topic_id|

                .. versionadded:: 22.4
            message_thread_id (:obj:`int`, optional): |message_thread_id_arg|

                .. versionadded:: 22.4

        Keyword Args:
            allow_sending_without_reply (:obj:`bool`, optional): |allow_sending_without_reply|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

            reply_to_message_id (:obj:`int`, optional): |reply_to_msg_id|
                Mutually exclusive with :paramref:`reply_parameters`, which this is a convenience
                parameter for

        Returns:
            :class:`telegram.Message`: On success, the sent message is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """

        data: JSONDict = {
            "chat_id": chat_id,
            "star_count": star_count,
            "media": media,
            "show_caption_above_media": show_caption_above_media,
            "payload": payload,
        }

        return await self._send_message(
            "sendPaidMedia",
            data,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            disable_notification=disable_notification,
            protect_content=protect_content,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_to_message_id=reply_to_message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            message_thread_id=message_thread_id,
        )

    async def create_chat_subscription_invite_link(
        self,
        chat_id: str | int,
        subscription_period: TimePeriod,
        subscription_price: int,
        name: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ChatInviteLink:
        """
        Use this method to create a `subscription invite link <https://telegram.org/blog/\
        superchannels-star-reactions-subscriptions#star-subscriptions>`_ for a channel chat.
        The bot must have the :attr:`~telegram.ChatPermissions.can_invite_users` administrator
        right. The link can be edited using the :meth:`edit_chat_subscription_invite_link` or
        revoked using the :meth:`revoke_chat_invite_link`.

        .. versionadded:: 21.5

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            subscription_period (:obj:`int` | :class:`datetime.timedelta`): The number of seconds
                the subscription will be
                active for before the next payment. Currently, it must always be
                :tg-const:`telegram.constants.ChatSubscriptionLimit.SUBSCRIPTION_PERIOD` (30 days).

                .. versionchanged:: 21.11
                    |time-period-input|
            subscription_price (:obj:`int`): The number of Telegram Stars a user must pay initially
                and after each subsequent subscription period to be a member of the chat;
                :tg-const:`telegram.constants.ChatSubscriptionLimit.MIN_PRICE`-
                :tg-const:`telegram.constants.ChatSubscriptionLimit.MAX_PRICE`.
            name (:obj:`str`, optional): Invite link name;
                0-:tg-const:`telegram.constants.ChatInviteLinkLimit.NAME_LENGTH` characters.

        Returns:
            :class:`telegram.ChatInviteLink`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        data: JSONDict = {
            "chat_id": chat_id,
            "subscription_period": subscription_period,
            "subscription_price": subscription_price,
            "name": name,
        }

        result = await self._post(
            "createChatSubscriptionInviteLink",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return ChatInviteLink.de_json(result, self)

    async def edit_chat_subscription_invite_link(
        self,
        chat_id: str | int,
        invite_link: "str | ChatInviteLink",
        name: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> ChatInviteLink:
        """
        Use this method to edit a subscription invite link created by the bot. The bot must have
        :attr:`telegram.ChatPermissions.can_invite_users` administrator right.

        .. versionadded:: 21.5

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            invite_link (:obj:`str` | :obj:`telegram.ChatInviteLink`): The invite link to edit.
            name (:obj:`str`, optional): Invite link name;
                0-:tg-const:`telegram.constants.ChatInviteLinkLimit.NAME_LENGTH` characters.

                Tip:
                    Omitting this argument removes the name of the invite link.

        Returns:
            :class:`telegram.ChatInviteLink`

        Raises:
            :class:`telegram.error.TelegramError`

        """
        link = invite_link.invite_link if isinstance(invite_link, ChatInviteLink) else invite_link
        data: JSONDict = {
            "chat_id": chat_id,
            "invite_link": link,
            "name": name,
        }

        result = await self._post(
            "editChatSubscriptionInviteLink",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        return ChatInviteLink.de_json(result, self)

    async def get_available_gifts(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Gifts:
        """Returns the list of gifts that can be sent by the bot to users and channel chats.
        Requires no parameters.

        .. versionadded:: 21.8

        Returns:
            :class:`telegram.Gifts`

        Raises:
            :class:`telegram.error.TelegramError`
        """
        return Gifts.de_json(
            await self._post(
                "getAvailableGifts",
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            )
        )

    async def send_gift(
        self,
        gift_id: "str | Gift",
        text: str | None = None,
        text_parse_mode: ODVInput[str] = DEFAULT_NONE,
        text_entities: Sequence["MessageEntity"] | None = None,
        pay_for_upgrade: bool | None = None,
        chat_id: str | int | None = None,
        user_id: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Sends a gift to the given user or channel chat.
        The gift can't be converted to Telegram Stars by the receiver.

        .. versionadded:: 21.8
        .. versionchanged:: 22.1
           Bot API 8.3 made :paramref:`user_id` optional. In version 22.1, the methods
           signature was changed accordingly.

        Args:
            gift_id (:obj:`str` | :class:`~telegram.Gift`): Identifier of the gift or a
                :class:`~telegram.Gift` object; limited gifts can't be sent to channel chats
            user_id (:obj:`int`, optional): Required if :paramref:`chat_id` is not specified.
                Unique identifier of the target user that will receive the gift.

                .. versionchanged:: 21.11
                    Now optional.
            chat_id (:obj:`int` | :obj:`str`, optional): Required if :paramref:`user_id`
                is not specified. |chat_id_channel| It will receive the gift.

                .. versionadded:: 21.11
            text (:obj:`str`, optional): Text that will be shown along with the gift;
                0- :tg-const:`telegram.constants.GiftLimit.MAX_TEXT_LENGTH` characters
            text_parse_mode (:obj:`str`, optional): Mode for parsing entities.
                See :class:`telegram.constants.ParseMode` and
                `formatting options <https://core.telegram.org/bots/api#formatting-options>`__ for
                more details. Entities other than :attr:`~MessageEntity.BOLD`,
                :attr:`~MessageEntity.ITALIC`, :attr:`~MessageEntity.UNDERLINE`,
                :attr:`~MessageEntity.STRIKETHROUGH`, :attr:`~MessageEntity.SPOILER`, and
                :attr:`~MessageEntity.CUSTOM_EMOJI` are ignored.
            text_entities (Sequence[:class:`telegram.MessageEntity`], optional): A list of special
                entities that appear in the gift text. It can be specified instead of
                :paramref:`text_parse_mode`. Entities other than :attr:`~MessageEntity.BOLD`,
                :attr:`~MessageEntity.ITALIC`, :attr:`~MessageEntity.UNDERLINE`,
                :attr:`~MessageEntity.STRIKETHROUGH`, :attr:`~MessageEntity.SPOILER`, and
                :attr:`~MessageEntity.CUSTOM_EMOJI` are ignored.
            pay_for_upgrade (:obj:`bool`, optional): Pass :obj:`True` to pay for the gift upgrade
                from the bot's balance, thereby making the upgrade free for the receiver.

                .. versionadded:: 21.10

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
            "gift_id": gift_id.id if isinstance(gift_id, Gift) else gift_id,
            "text": text,
            "text_parse_mode": text_parse_mode,
            "text_entities": text_entities,
            "pay_for_upgrade": pay_for_upgrade,
            "chat_id": chat_id,
        }
        return await self._post(
            "sendGift",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def verify_chat(
        self,
        chat_id: int | str,
        custom_description: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Verifies a chat |org-verify| which is represented by the bot.

        .. versionadded:: 21.10

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
            custom_description (:obj:`str`, optional): Custom description for the verification;
                0- :tg-const:`telegram.constants.VerifyLimit.MAX_TEXT_LENGTH` characters. Must be
                empty if the organization isn't allowed to provide a custom verification
                description.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "chat_id": chat_id,
            "custom_description": custom_description,
        }
        return await self._post(
            "verifyChat",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def verify_user(
        self,
        user_id: int,
        custom_description: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Verifies a user |org-verify| which is represented by the bot.

        .. versionadded:: 21.10

        Args:
            user_id (:obj:`int`): Unique identifier of the target user.
            custom_description (:obj:`str`, optional): Custom description for the verification;
                0- :tg-const:`telegram.constants.VerifyLimit.MAX_TEXT_LENGTH` characters. Must be
                empty if the organization isn't allowed to provide a custom verification
                description.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
            "custom_description": custom_description,
        }
        return await self._post(
            "verifyUser",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def remove_chat_verification(
        self,
        chat_id: int | str,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Removes verification from a chat that is currently verified |org-verify|
        represented by the bot.

        .. versionadded:: 21.10

        Args:
            chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "chat_id": chat_id,
        }
        return await self._post(
            "removeChatVerification",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def remove_user_verification(
        self,
        user_id: int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """Removes verification from a user who is currently verified |org-verify|
        represented by the bot.

        .. versionadded:: 21.10

        Args:
            user_id (:obj:`int`): Unique identifier of the target user.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
        }
        return await self._post(
            "removeUserVerification",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def get_my_star_balance(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> StarAmount:
        """A method to get the current Telegram Stars balance of the bot. Requires no parameters.

        .. versionadded:: 22.3

        Returns:
            :class:`telegram.StarAmount`

        Raises:
            :class:`telegram.error.TelegramError`
        """
        return StarAmount.de_json(
            await self._post(
                "getMyStarBalance",
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            )
        )

    async def approve_suggested_post(
        self,
        chat_id: int,
        message_id: int,
        send_date: int | dtm.datetime | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to approve a suggested post in a direct messages chat.
        The bot must have the :attr:`~telegram.ChatMemberAdministrator.can_post_messages`
        administrator right in the corresponding channel chat.

        .. versionadded:: 22.4

        Args:
            chat_id (:obj:`int`): Unique identifier of the target direct messages chat.
            message_id (:obj:`int`): Identifier of a suggested post message to approve.
            send_date (:obj:`int` | :obj:`datetime.datetime`, optional): Date when the post is
                expected to be published; omit if the date has already been specified when the
                suggested post was created. If specified, then the date must be not more than
                :tg-const:`telegram.constants.SuggestedPost.MAX_SEND_DATE` seconds (30 days)
                in the future.

                |tz-naive-dtms|

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "send_date": send_date,
        }

        return await self._post(
            "approveSuggestedPost",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def decline_suggested_post(
        self,
        chat_id: int,
        message_id: int,
        comment: str | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> bool:
        """
        Use this method to decline a suggested post in a direct messages chat.
        The bot must have the :attr:`~telegram.ChatMemberAdministrator.can_manage_direct_messages`
        administrator right in the corresponding channel chat.

        .. versionadded:: 22.4

        Args:
            chat_id (:obj:`int`): Unique identifier of the target direct messages chat.
            message_id (:obj:`int`): Identifier of a suggested post message to decline.
            comment (:obj:`str`, optional): Comment for the creator of the suggested post.
                0-:tg-const:`telegram.constants.SuggestedPost.MAX_COMMENT_LENGTH` characters.

        Returns:
            :obj:`bool`: On success, :obj:`True` is returned.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "comment": comment,
        }

        return await self._post(
            "declineSuggestedPost",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    async def repost_story(
        self,
        business_connection_id: str,
        from_chat_id: int,
        from_story_id: int,
        active_period: TimePeriod,
        post_to_chat_page: bool | None = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Story:
        """
        Reposts a story on behalf of a business account from another business account.
        Both business accounts must be managed by the same bot, and the story on the source account
        must have been posted (or reposted) by the bot. Requires the
        :attr:`~telegram.BusinessBotRight.can_manage_stories` business bot right for both
        business accounts.

        .. versionadded:: 22.6

        Args:
            business_connection_id (:obj:`str`): Unique identifier of the business
            from_chat_id (:obj:`int`): Unique identifier of the chat which posted the story that
                should be reposted
            from_story_id (:obj:`int`): Unique identifier of the story that should be reposted
            active_period (:obj:`int` | :class:`datetime.timedelta`): Period after which the story
                is moved to the archive, in seconds; must be one of
                :tg-const:`telegram.constants.StoryLimit.SIX_HOURS`,
                :tg-const:`telegram.constants.StoryLimit.TWELVE_HOURS`,
                :tg-const:`telegram.constants.StoryLimit.ONE_DAY`, or
                :tg-const:`telegram.constants.StoryLimit.TWO_DAYS`.
            post_to_chat_page (:obj:`bool`, optional): Pass :obj:`True` to keep the story
                accessible after it expires.
            protect_content (:obj:`bool`, optional): Pass :obj:`True` if the content of the story
                must be protected from forwarding and screenshotting

        Returns:
            :class:`telegram.Story`

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "business_connection_id": business_connection_id,
            "from_chat_id": from_chat_id,
            "from_story_id": from_story_id,
            "active_period": active_period,
            "post_to_chat_page": post_to_chat_page,
            "protect_content": protect_content,
        }
        return Story.de_json(
            data=await self._post(
                "repostStory",
                data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                api_kwargs=api_kwargs,
            ),
            bot=self,
        )

    async def get_user_gifts(
        self,
        user_id: int,
        exclude_unlimited: bool | None = None,
        exclude_limited_upgradable: bool | None = None,
        exclude_limited_non_upgradable: bool | None = None,
        exclude_from_blockchain: bool | None = None,
        exclude_unique: bool | None = None,
        sort_by_price: bool | None = None,
        offset: str | None = None,
        limit: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> OwnedGifts:
        """Returns the gifts owned and hosted by a user.

        .. versionadded:: 22.6

        user_id (:obj:`int`): Unique identifier of the user
        exclude_unlimited (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that can be
            purchased an unlimited number of times
        exclude_limited_upgradable (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that
            can be purchased a limited number of times and can be upgraded to unique
        exclude_limited_non_upgradable (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts
            that can be purchased a limited number of times and can't be upgraded to unique
        exclude_from_blockchain (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that
            were assigned from the TON blockchain and can't be resold or transferred in Telegram
        exclude_unique (:obj:`bool`, optional): Pass :obj:`True` to exclude unique gifts
        sort_by_price (:obj:`bool`, optional): Pass :obj:`True` to sort results by gift price
            instead of send date. Sorting is applied before pagination.
        offset (:obj:`str`, optional): Offset of the first entry to return as received from the
            previous request; use an empty string to get the first chunk of results
        limit (:obj:`int`, optional): The maximum number of gifts to be returned;
            :tg-const:`~telegram.constants.BusinessLimit.MIN_GIFT_RESULTS` -
            :tg-const:`~telegram.constants.BusinessLimit.MAX_GIFT_RESLUTS`.
            Defaults to :tg-const:`~telegram.constants.BusinessLimit.MAX_GIFT_RESLUTS`

        Returns:
            :class:`telegram.OwnedGifts`: The owned gifts for the user.

        Raises:
            :class:`telegram.error.TelegramError`
        """
        data: JSONDict = {
            "user_id": user_id,
            "exclude_unlimited": exclude_unlimited,
            "exclude_limited_upgradable": exclude_limited_upgradable,
            "exclude_limited_non_upgradable": exclude_limited_non_upgradable,
            "exclude_from_blockchain": exclude_from_blockchain,
            "exclude_unique": exclude_unique,
            "sort_by_price": sort_by_price,
            "offset": offset,
            "limit": limit,
        }

        result = await self._post(
            "getUserGifts",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return OwnedGifts.de_json(result, self)

    async def get_chat_gifts(
        self,
        chat_id: int | str,
        exclude_unsaved: bool | None = None,
        exclude_saved: bool | None = None,
        exclude_unlimited: bool | None = None,
        exclude_limited_upgradable: bool | None = None,
        exclude_limited_non_upgradable: bool | None = None,
        exclude_from_blockchain: bool | None = None,
        exclude_unique: bool | None = None,
        sort_by_price: bool | None = None,
        offset: str | None = None,
        limit: int | None = None,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> OwnedGifts:
        """Use this method to get gifts owned by a chat.

        .. versionadded:: 22.6

        Args:
        chat_id (:obj:`int` | :obj:`str`): |chat_id_channel|
        exclude_unsaved (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that aren't
            saved to the chat's profile page. Always :obj:`True`, unless the bot has the
            :attr:`~telegram.ChatAdministratorRights..can_post_messages` administrator right in the
                channel.
        exclude_saved (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that are saved to
            the chat's profile page. Always :obj:`False`, unless the bot has the
            :attr:`~telegram.ChatAdministratorRights..can_post_messages` administrator right in the
                channel.
        exclude_unlimited (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that can be
            purchased an unlimited number of times
        exclude_limited_upgradable (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that
            can be purchased a limited number of times and can be upgraded to unique
        exclude_limited_non_upgradable (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts
            that can be purchased a limited number of times and can't be upgraded to unique
        exclude_from_blockchain (:obj:`bool`, optional): Pass :obj:`True` to exclude gifts that
            were assigned from the TON blockchain and can't be resold or transferred in Telegram
        exclude_unique (:obj:`bool`, optional): Pass :obj:`True` to exclude unique gifts
        sort_by_price (:obj:`bool`, optional): Pass :obj:`True` to sort results by gift price
            instead of send date. Sorting is applied before pagination.
        offset (:obj:`str`, optional): Offset of the first entry to return as received from the
            previous request; use an empty string to get the first chunk of results
        limit (:obj:`int`, optional): The maximum number of gifts to be returned;
            :tg-const:`~telegram.constants.BusinessLimit.MIN_GIFT_RESULTS` -
            :tg-const:`~telegram.constants.BusinessLimit.MAX_GIFT_RESLUTS`.
            Defaults to :tg-const:`~telegram.constants.BusinessLimit.MAX_GIFT_RESLUTS`

        Returns:
            :class:`telegram.OwnedGifts`: The owned gifts for the chat.

        Raises:
            :class:`telegram.error.TelegramError`
        """

        data: JSONDict = {
            "chat_id": chat_id,
            "exclude_unsaved": exclude_unsaved,
            "exclude_saved": exclude_saved,
            "exclude_unlimited": exclude_unlimited,
            "exclude_limited_upgradable": exclude_limited_upgradable,
            "exclude_limited_non_upgradable": exclude_limited_non_upgradable,
            "exclude_from_blockchain": exclude_from_blockchain,
            "exclude_unique": exclude_unique,
            "sort_by_price": sort_by_price,
            "offset": offset,
            "limit": limit,
        }

        result = await self._post(
            "getChatGifts",
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )
        return OwnedGifts.de_json(result, self)

    def to_dict(self, recursive: bool = True) -> JSONDict:  # noqa: ARG002
        """See :meth:`telegram.TelegramObject.to_dict`."""
        data: JSONDict = {"id": self.id, "username": self.username, "first_name": self.first_name}

        if self.last_name:
            data["last_name"] = self.last_name

        return data

    # camelCase aliases
    getMe = get_me
    """Alias for :meth:`get_me`"""
    sendMessage = send_message
    """Alias for :meth:`send_message`"""
    sendMessageDraft = send_message_draft
    """Alias for :meth:`send_message_draft`"""
    deleteMessage = delete_message
    """Alias for :meth:`delete_message`"""
    deleteMessages = delete_messages
    """Alias for :meth:`delete_messages`"""
    forwardMessage = forward_message
    """Alias for :meth:`forward_message`"""
    forwardMessages = forward_messages
    """Alias for :meth:`forward_messages`"""
    sendPhoto = send_photo
    """Alias for :meth:`send_photo`"""
    sendAudio = send_audio
    """Alias for :meth:`send_audio`"""
    sendDocument = send_document
    """Alias for :meth:`send_document`"""
    sendSticker = send_sticker
    """Alias for :meth:`send_sticker`"""
    sendVideo = send_video
    """Alias for :meth:`send_video`"""
    sendAnimation = send_animation
    """Alias for :meth:`send_animation`"""
    sendVoice = send_voice
    """Alias for :meth:`send_voice`"""
    sendVideoNote = send_video_note
    """Alias for :meth:`send_video_note`"""
    sendMediaGroup = send_media_group
    """Alias for :meth:`send_media_group`"""
    sendLocation = send_location
    """Alias for :meth:`send_location`"""
    editMessageLiveLocation = edit_message_live_location
    """Alias for :meth:`edit_message_live_location`"""
    stopMessageLiveLocation = stop_message_live_location
    """Alias for :meth:`stop_message_live_location`"""
    sendVenue = send_venue
    """Alias for :meth:`send_venue`"""
    sendContact = send_contact
    """Alias for :meth:`send_contact`"""
    sendGame = send_game
    """Alias for :meth:`send_game`"""
    sendChatAction = send_chat_action
    """Alias for :meth:`send_chat_action`"""
    answerInlineQuery = answer_inline_query
    """Alias for :meth:`answer_inline_query`"""
    savePreparedInlineMessage = save_prepared_inline_message
    """Alias for :meth:`save_prepared_inline_message`"""
    getUserProfilePhotos = get_user_profile_photos
    """Alias for :meth:`get_user_profile_photos`"""
    getFile = get_file
    """Alias for :meth:`get_file`"""
    banChatMember = ban_chat_member
    """Alias for :meth:`ban_chat_member`"""
    banChatSenderChat = ban_chat_sender_chat
    """Alias for :meth:`ban_chat_sender_chat`"""
    unbanChatMember = unban_chat_member
    """Alias for :meth:`unban_chat_member`"""
    unbanChatSenderChat = unban_chat_sender_chat
    """Alias for :meth:`unban_chat_sender_chat`"""
    answerCallbackQuery = answer_callback_query
    """Alias for :meth:`answer_callback_query`"""
    editMessageText = edit_message_text
    """Alias for :meth:`edit_message_text`"""
    editMessageCaption = edit_message_caption
    """Alias for :meth:`edit_message_caption`"""
    editMessageMedia = edit_message_media
    """Alias for :meth:`edit_message_media`"""
    editMessageReplyMarkup = edit_message_reply_markup
    """Alias for :meth:`edit_message_reply_markup`"""
    getUpdates = get_updates
    """Alias for :meth:`get_updates`"""
    setWebhook = set_webhook
    """Alias for :meth:`set_webhook`"""
    deleteWebhook = delete_webhook
    """Alias for :meth:`delete_webhook`"""
    leaveChat = leave_chat
    """Alias for :meth:`leave_chat`"""
    getChat = get_chat
    """Alias for :meth:`get_chat`"""
    getChatAdministrators = get_chat_administrators
    """Alias for :meth:`get_chat_administrators`"""
    getChatMember = get_chat_member
    """Alias for :meth:`get_chat_member`"""
    setChatStickerSet = set_chat_sticker_set
    """Alias for :meth:`set_chat_sticker_set`"""
    deleteChatStickerSet = delete_chat_sticker_set
    """Alias for :meth:`delete_chat_sticker_set`"""
    getChatMemberCount = get_chat_member_count
    """Alias for :meth:`get_chat_member_count`"""
    getWebhookInfo = get_webhook_info
    """Alias for :meth:`get_webhook_info`"""
    setGameScore = set_game_score
    """Alias for :meth:`set_game_score`"""
    getGameHighScores = get_game_high_scores
    """Alias for :meth:`get_game_high_scores`"""
    sendInvoice = send_invoice
    """Alias for :meth:`send_invoice`"""
    answerShippingQuery = answer_shipping_query
    """Alias for :meth:`answer_shipping_query`"""
    answerPreCheckoutQuery = answer_pre_checkout_query
    """Alias for :meth:`answer_pre_checkout_query`"""
    answerWebAppQuery = answer_web_app_query
    """Alias for :meth:`answer_web_app_query`"""
    restrictChatMember = restrict_chat_member
    """Alias for :meth:`restrict_chat_member`"""
    promoteChatMember = promote_chat_member
    """Alias for :meth:`promote_chat_member`"""
    setChatPermissions = set_chat_permissions
    """Alias for :meth:`set_chat_permissions`"""
    setChatAdministratorCustomTitle = set_chat_administrator_custom_title
    """Alias for :meth:`set_chat_administrator_custom_title`"""
    exportChatInviteLink = export_chat_invite_link
    """Alias for :meth:`export_chat_invite_link`"""
    createChatInviteLink = create_chat_invite_link
    """Alias for :meth:`create_chat_invite_link`"""
    editChatInviteLink = edit_chat_invite_link
    """Alias for :meth:`edit_chat_invite_link`"""
    revokeChatInviteLink = revoke_chat_invite_link
    """Alias for :meth:`revoke_chat_invite_link`"""
    approveChatJoinRequest = approve_chat_join_request
    """Alias for :meth:`approve_chat_join_request`"""
    declineChatJoinRequest = decline_chat_join_request
    """Alias for :meth:`decline_chat_join_request`"""
    setChatPhoto = set_chat_photo
    """Alias for :meth:`set_chat_photo`"""
    deleteChatPhoto = delete_chat_photo
    """Alias for :meth:`delete_chat_photo`"""
    setChatTitle = set_chat_title
    """Alias for :meth:`set_chat_title`"""
    setChatDescription = set_chat_description
    """Alias for :meth:`set_chat_description`"""
    setUserEmojiStatus = set_user_emoji_status
    """Alias for :meth:`set_user_emoji_status`"""
    pinChatMessage = pin_chat_message
    """Alias for :meth:`pin_chat_message`"""
    unpinChatMessage = unpin_chat_message
    """Alias for :meth:`unpin_chat_message`"""
    unpinAllChatMessages = unpin_all_chat_messages
    """Alias for :meth:`unpin_all_chat_messages`"""
    getCustomEmojiStickers = get_custom_emoji_stickers
    """Alias for :meth:`get_custom_emoji_stickers`"""
    getStickerSet = get_sticker_set
    """Alias for :meth:`get_sticker_set`"""
    uploadStickerFile = upload_sticker_file
    """Alias for :meth:`upload_sticker_file`"""
    createNewStickerSet = create_new_sticker_set
    """Alias for :meth:`create_new_sticker_set`"""
    addStickerToSet = add_sticker_to_set
    """Alias for :meth:`add_sticker_to_set`"""
    setStickerPositionInSet = set_sticker_position_in_set
    """Alias for :meth:`set_sticker_position_in_set`"""
    deleteStickerFromSet = delete_sticker_from_set
    """Alias for :meth:`delete_sticker_from_set`"""
    setStickerSetThumbnail = set_sticker_set_thumbnail
    """Alias for :meth:`set_sticker_set_thumbnail`"""
    setPassportDataErrors = set_passport_data_errors
    """Alias for :meth:`set_passport_data_errors`"""
    sendPoll = send_poll
    """Alias for :meth:`send_poll`"""
    stopPoll = stop_poll
    """Alias for :meth:`stop_poll`"""
    sendChecklist = send_checklist
    """Alias for :meth:`send_checklist`"""
    editMessageChecklist = edit_message_checklist
    """Alias for :meth:`edit_message_checklist`"""
    sendDice = send_dice
    """Alias for :meth:`send_dice`"""
    getMyCommands = get_my_commands
    """Alias for :meth:`get_my_commands`"""
    setMyCommands = set_my_commands
    """Alias for :meth:`set_my_commands`"""
    deleteMyCommands = delete_my_commands
    """Alias for :meth:`delete_my_commands`"""
    logOut = log_out
    """Alias for :meth:`log_out`"""
    copyMessage = copy_message
    """Alias for :meth:`copy_message`"""
    copyMessages = copy_messages
    """Alias for :meth:`copy_messages`"""
    getChatMenuButton = get_chat_menu_button
    """Alias for :meth:`get_chat_menu_button`"""
    setChatMenuButton = set_chat_menu_button
    """Alias for :meth:`set_chat_menu_button`"""
    getMyDefaultAdministratorRights = get_my_default_administrator_rights
    """Alias for :meth:`get_my_default_administrator_rights`"""
    setMyDefaultAdministratorRights = set_my_default_administrator_rights
    """Alias for :meth:`set_my_default_administrator_rights`"""
    createInvoiceLink = create_invoice_link
    """Alias for :meth:`create_invoice_link`"""
    getForumTopicIconStickers = get_forum_topic_icon_stickers
    """Alias for :meth:`get_forum_topic_icon_stickers`"""
    createForumTopic = create_forum_topic
    """Alias for :meth:`create_forum_topic`"""
    editForumTopic = edit_forum_topic
    """Alias for :meth:`edit_forum_topic`"""
    closeForumTopic = close_forum_topic
    """Alias for :meth:`close_forum_topic`"""
    reopenForumTopic = reopen_forum_topic
    """Alias for :meth:`reopen_forum_topic`"""
    deleteForumTopic = delete_forum_topic
    """Alias for :meth:`delete_forum_topic`"""
    unpinAllForumTopicMessages = unpin_all_forum_topic_messages
    """Alias for :meth:`unpin_all_forum_topic_messages`"""
    editGeneralForumTopic = edit_general_forum_topic
    """Alias for :meth:`edit_general_forum_topic`"""
    closeGeneralForumTopic = close_general_forum_topic
    """Alias for :meth:`close_general_forum_topic`"""
    reopenGeneralForumTopic = reopen_general_forum_topic
    """Alias for :meth:`reopen_general_forum_topic`"""
    hideGeneralForumTopic = hide_general_forum_topic
    """Alias for :meth:`hide_general_forum_topic`"""
    unhideGeneralForumTopic = unhide_general_forum_topic
    """Alias for :meth:`unhide_general_forum_topic`"""
    setMyDescription = set_my_description
    """Alias for :meth:`set_my_description`"""
    setMyShortDescription = set_my_short_description
    """Alias for :meth:`set_my_short_description`"""
    getMyDescription = get_my_description
    """Alias for :meth:`get_my_description`"""
    getMyShortDescription = get_my_short_description
    """Alias for :meth:`get_my_short_description`"""
    setCustomEmojiStickerSetThumbnail = set_custom_emoji_sticker_set_thumbnail
    """Alias for :meth:`set_custom_emoji_sticker_set_thumbnail`"""
    setStickerSetTitle = set_sticker_set_title
    """Alias for :meth:`set_sticker_set_title`"""
    deleteStickerSet = delete_sticker_set
    """Alias for :meth:`delete_sticker_set`"""
    setStickerEmojiList = set_sticker_emoji_list
    """Alias for :meth:`set_sticker_emoji_list`"""
    setStickerKeywords = set_sticker_keywords
    """Alias for :meth:`set_sticker_keywords`"""
    setStickerMaskPosition = set_sticker_mask_position
    """Alias for :meth:`set_sticker_mask_position`"""
    setMyName = set_my_name
    """Alias for :meth:`set_my_name`"""
    getMyName = get_my_name
    """Alias for :meth:`get_my_name`"""
    unpinAllGeneralForumTopicMessages = unpin_all_general_forum_topic_messages
    """Alias for :meth:`unpin_all_general_forum_topic_messages`"""
    getUserChatBoosts = get_user_chat_boosts
    """Alias for :meth:`get_user_chat_boosts`"""
    setMessageReaction = set_message_reaction
    """Alias for :meth:`set_message_reaction`"""
    giftPremiumSubscription = gift_premium_subscription
    """Alias for :meth:`gift_premium_subscription`"""
    getBusinessAccountGifts = get_business_account_gifts
    """Alias for :meth:`get_business_account_gifts`"""
    getBusinessAccountStarBalance = get_business_account_star_balance
    """Alias for :meth:`get_business_account_star_balance`"""
    getBusinessConnection = get_business_connection
    """Alias for :meth:`get_business_connection`"""
    readBusinessMessage = read_business_message
    """Alias for :meth:`read_business_message`"""
    deleteBusinessMessages = delete_business_messages
    """Alias for :meth:`delete_business_messages`"""
    postStory = post_story
    """Alias for :meth:`post_story`"""
    editStory = edit_story
    """Alias for :meth:`edit_story`"""
    deleteStory = delete_story
    """Alias for :meth:`delete_story`"""
    setBusinessAccountName = set_business_account_name
    """Alias for :meth:`set_business_account_name`"""
    setBusinessAccountUsername = set_business_account_username
    """Alias for :meth:`set_business_account_username`"""
    setBusinessAccountBio = set_business_account_bio
    """Alias for :meth:`set_business_account_bio`"""
    setBusinessAccountGiftSettings = set_business_account_gift_settings
    """Alias for :meth:`set_business_account_gift_settings`"""
    setBusinessAccountProfilePhoto = set_business_account_profile_photo
    """Alias for :meth:`set_business_account_profile_photo`"""
    removeBusinessAccountProfilePhoto = remove_business_account_profile_photo
    """Alias for :meth:`remove_business_account_profile_photo`"""
    convertGiftToStars = convert_gift_to_stars
    """Alias for :meth:`convert_gift_to_stars`"""
    upgradeGift = upgrade_gift
    """Alias for :meth:`upgrade_gift`"""
    transferGift = transfer_gift
    """Alias for :meth:`transfer_gift`"""
    transferBusinessAccountStars = transfer_business_account_stars
    """Alias for :meth:`transfer_business_account_stars`"""
    replaceStickerInSet = replace_sticker_in_set
    """Alias for :meth:`replace_sticker_in_set`"""
    refundStarPayment = refund_star_payment
    """Alias for :meth:`refund_star_payment`"""
    getStarTransactions = get_star_transactions
    """Alias for :meth:`get_star_transactions`"""
    editUserStarSubscription = edit_user_star_subscription
    """Alias for :meth:`edit_user_star_subscription`"""
    sendPaidMedia = send_paid_media
    """Alias for :meth:`send_paid_media`"""
    createChatSubscriptionInviteLink = create_chat_subscription_invite_link
    """Alias for :meth:`create_chat_subscription_invite_link`"""
    editChatSubscriptionInviteLink = edit_chat_subscription_invite_link
    """Alias for :meth:`edit_chat_subscription_invite_link`"""
    getAvailableGifts = get_available_gifts
    """Alias for :meth:`get_available_gifts`"""
    sendGift = send_gift
    """Alias for :meth:`send_gift`"""
    verifyChat = verify_chat
    """Alias for :meth:`verify_chat`"""
    verifyUser = verify_user
    """Alias for :meth:`verify_user`"""
    removeChatVerification = remove_chat_verification
    """Alias for :meth:`remove_chat_verification`"""
    removeUserVerification = remove_user_verification
    """Alias for :meth:`remove_user_verification`"""
    getMyStarBalance = get_my_star_balance
    """Alias for :meth:`get_my_star_balance`"""
    approveSuggestedPost = approve_suggested_post
    """Alias for :meth:`approve_suggested_post`"""
    declineSuggestedPost = decline_suggested_post
    """Alias for :meth:`decline_suggested_post`"""
    repostStory = repost_story
    """Alias for :meth:`repost_story`"""
    getUserGifts = get_user_gifts
    """Alias for :meth:`get_user_gifts`"""
    getChatGifts = get_chat_gifts
    """Alias for :meth:`get_chat_gifts`"""
