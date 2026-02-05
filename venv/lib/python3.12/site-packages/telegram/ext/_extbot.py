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
"""This module contains an object that represents a Telegram Bot with convenience extensions."""

import datetime as dtm
from collections.abc import Callable, Sequence
from copy import copy
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    TypeVar,
    cast,
    no_type_check,
    overload,
)
from uuid import uuid4

from telegram import (
    AcceptedGiftTypes,
    Animation,
    Audio,
    Bot,
    BotCommand,
    BotCommandScope,
    BotDescription,
    BotName,
    BotShortDescription,
    BusinessConnection,
    CallbackQuery,
    ChatAdministratorRights,
    ChatFullInfo,
    ChatInviteLink,
    ChatMember,
    ChatPermissions,
    ChatPhoto,
    Document,
    File,
    ForumTopic,
    GameHighScore,
    Gifts,
    InlineKeyboardMarkup,
    InlineQueryResultsButton,
    InputChecklist,
    InputMedia,
    InputPaidMedia,
    InputPollOption,
    InputProfilePhoto,
    LinkPreviewOptions,
    MaskPosition,
    MenuButton,
    Message,
    MessageId,
    OwnedGifts,
    PhotoSize,
    Poll,
    PreparedInlineMessage,
    ReactionType,
    ReplyParameters,
    SentWebAppMessage,
    StarAmount,
    StarTransactions,
    Sticker,
    StickerSet,
    Story,
    TelegramObject,
    Update,
    User,
    UserChatBoosts,
    UserProfilePhotos,
    Video,
    VideoNote,
    Voice,
    WebhookInfo,
)
from telegram._utils.datetime import to_timestamp
from telegram._utils.defaultvalue import DEFAULT_NONE, DefaultValue
from telegram._utils.logging import get_logger
from telegram._utils.repr import build_repr_with_selected_attrs
from telegram._utils.types import (
    BaseUrl,
    CorrectOptionID,
    FileInput,
    JSONDict,
    ODVInput,
    ReplyMarkup,
    TimePeriod,
)
from telegram.ext._callbackdatacache import CallbackDataCache
from telegram.ext._utils.types import RLARGS
from telegram.request import BaseRequest
from telegram.warnings import PTBUserWarning

if TYPE_CHECKING:
    from telegram import (
        Contact,
        Gift,
        InlineQueryResult,
        InputMediaAudio,
        InputMediaDocument,
        InputMediaPhoto,
        InputMediaVideo,
        InputSticker,
        InputStoryContent,
        LabeledPrice,
        Location,
        MessageEntity,
        PassportElementError,
        ShippingOption,
        StoryArea,
        SuggestedPostParameters,
        Venue,
    )
    from telegram.ext import BaseRateLimiter, Defaults

HandledTypes = TypeVar("HandledTypes", bound=Message | CallbackQuery | ChatFullInfo)
KT = TypeVar("KT", bound=ReplyMarkup)


class ExtBot(Bot, Generic[RLARGS]):
    """This object represents a Telegram Bot with convenience extensions.

    Warning:
        Not to be confused with :class:`telegram.Bot`.

    For the documentation of the arguments, methods and attributes, please see
    :class:`telegram.Bot`.

    All API methods of this class have an additional keyword argument ``rate_limit_args``.
    This can be used to pass additional information to the rate limiter, specifically to
    :paramref:`telegram.ext.BaseRateLimiter.process_request.rate_limit_args`.

    This class is a :class:`~typing.Generic` class and accepts one type variable that specifies
    the generic type of the :attr:`rate_limiter` used by the bot. Use :obj:`None` if no rate
    limiter is used.

    Warning:
        * The keyword argument ``rate_limit_args`` can `not` be used, if :attr:`rate_limiter`
          is :obj:`None`.
        * The method :meth:`~telegram.Bot.get_updates` is the only method that does not have the
          additional argument, as this method will never be rate limited.

    Examples:
        :any:`Arbitrary Callback Data Bot <examples.arbitrarycallbackdatabot>`

    .. seealso:: :wiki:`Arbitrary callback_data <Arbitrary-callback_data>`

    .. versionadded:: 13.6

    .. versionchanged:: 20.0
        Removed the attribute ``arbitrary_callback_data``. You can instead use
        :attr:`bot.callback_data_cache.maxsize <telegram.ext.CallbackDataCache.maxsize>` to
        access the size of the cache.

    .. versionchanged:: 20.5
        Removed deprecated methods ``set_sticker_set_thumb`` and ``setStickerSetThumb``.

    Args:
        defaults (:class:`telegram.ext.Defaults`, optional): An object containing default values to
            be used if not set explicitly in the bot methods.
        arbitrary_callback_data (:obj:`bool` | :obj:`int`, optional): Whether to
            allow arbitrary objects as callback data for :class:`telegram.InlineKeyboardButton`.
            Pass an integer to specify the maximum number of objects cached in memory.
            Defaults to :obj:`False`.

            .. seealso:: :wiki:`Arbitrary callback_data <Arbitrary-callback_data>`
        rate_limiter (:class:`telegram.ext.BaseRateLimiter`, optional): A rate limiter to use for
            limiting the number of requests made by the bot per time interval.

            .. versionadded:: 20.0

    """

    __slots__ = ("_callback_data_cache", "_defaults", "_rate_limiter")

    _LOGGER = get_logger(__name__, class_name="ExtBot")

    # using object() would be a tiny bit safer, but a string plays better with the typing setup
    __RL_KEY = uuid4().hex

    @overload
    def __init__(
        self: "ExtBot[None]",
        token: str,
        base_url: BaseUrl = "https://api.telegram.org/bot",
        base_file_url: BaseUrl = "https://api.telegram.org/file/bot",
        request: BaseRequest | None = None,
        get_updates_request: BaseRequest | None = None,
        private_key: bytes | None = None,
        private_key_password: bytes | None = None,
        defaults: "Defaults | None" = None,
        arbitrary_callback_data: bool | int = False,
        local_mode: bool = False,
    ): ...

    @overload
    def __init__(
        self: "ExtBot[RLARGS]",
        token: str,
        base_url: BaseUrl = "https://api.telegram.org/bot",
        base_file_url: BaseUrl = "https://api.telegram.org/file/bot",
        request: BaseRequest | None = None,
        get_updates_request: BaseRequest | None = None,
        private_key: bytes | None = None,
        private_key_password: bytes | None = None,
        defaults: "Defaults | None" = None,
        arbitrary_callback_data: bool | int = False,
        local_mode: bool = False,
        rate_limiter: "BaseRateLimiter[RLARGS] | None" = None,
    ): ...

    def __init__(
        self,
        token: str,
        base_url: BaseUrl = "https://api.telegram.org/bot",
        base_file_url: BaseUrl = "https://api.telegram.org/file/bot",
        request: BaseRequest | None = None,
        get_updates_request: BaseRequest | None = None,
        private_key: bytes | None = None,
        private_key_password: bytes | None = None,
        defaults: "Defaults | None" = None,
        arbitrary_callback_data: bool | int = False,
        local_mode: bool = False,
        rate_limiter: "BaseRateLimiter[RLARGS] | None" = None,
    ):
        super().__init__(
            token=token,
            base_url=base_url,
            base_file_url=base_file_url,
            request=request,
            get_updates_request=get_updates_request,
            private_key=private_key,
            private_key_password=private_key_password,
            local_mode=local_mode,
        )
        with self._unfrozen():
            self._defaults: Defaults | None = defaults
            self._rate_limiter: BaseRateLimiter | None = rate_limiter
            self._callback_data_cache: CallbackDataCache | None = None

            # set up callback_data
            if arbitrary_callback_data is False:
                return

            if not isinstance(arbitrary_callback_data, bool):
                maxsize = cast("int", arbitrary_callback_data)
            else:
                maxsize = 1024

            self._callback_data_cache = CallbackDataCache(bot=self, maxsize=maxsize)

    def __repr__(self) -> str:
        """Give a string representation of the bot in the form ``ExtBot[token=...]``.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        return build_repr_with_selected_attrs(self, token=self.token)

    @classmethod
    def _warn(
        cls,
        message: str | PTBUserWarning,
        category: type[Warning] = PTBUserWarning,
        stacklevel: int = 0,
    ) -> None:
        """We override this method to add one more level to the stacklevel, so that the warning
        points to the user's code, not to the PTB code.
        """
        super()._warn(message=message, category=category, stacklevel=stacklevel + 2)

    @property
    def callback_data_cache(self) -> CallbackDataCache | None:
        """:class:`telegram.ext.CallbackDataCache`: Optional. The cache for
        objects passed as callback data for :class:`telegram.InlineKeyboardButton`.

        Examples:
            :any:`Arbitrary Callback Data Bot <examples.arbitrarycallbackdatabot>`

        .. versionchanged:: 20.0
           * This property is now read-only.
           * This property is now optional and can be :obj:`None` if
             :paramref:`~telegram.ext.ExtBot.arbitrary_callback_data` is set to :obj:`False`.
        """
        return self._callback_data_cache

    async def initialize(self) -> None:
        """See :meth:`telegram.Bot.initialize`. Also initializes the
        :paramref:`ExtBot.rate_limiter` (if set)
        by calling :meth:`telegram.ext.BaseRateLimiter.initialize`.
        """
        # Initialize before calling super, because super calls get_me
        if self.rate_limiter:
            await self.rate_limiter.initialize()
        await super().initialize()

    async def shutdown(self) -> None:
        """See :meth:`telegram.Bot.shutdown`. Also shuts down the
        :paramref:`ExtBot.rate_limiter` (if set) by
        calling :meth:`telegram.ext.BaseRateLimiter.shutdown`.
        """
        # Shut down the rate limiter before shutting down the request objects!
        if self.rate_limiter:
            await self.rate_limiter.shutdown()
        await super().shutdown()

    @classmethod
    def _merge_api_rl_kwargs(
        cls, api_kwargs: JSONDict | None, rate_limit_args: RLARGS | None
    ) -> JSONDict | None:
        """Inserts the `rate_limit_args` into `api_kwargs` with the special key `__RL_KEY` so
        that we can extract them later without having to modify the `telegram.Bot` class.
        """
        if not rate_limit_args:
            return api_kwargs
        if api_kwargs is None:
            api_kwargs = {}
        api_kwargs[cls.__RL_KEY] = rate_limit_args
        return api_kwargs

    @classmethod
    def _extract_rl_kwargs(cls, data: JSONDict | None) -> RLARGS | None:
        """Extracts the `rate_limit_args` from `data` if it exists."""
        if not data:
            return None
        return data.pop(cls.__RL_KEY, None)

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
        """Order of method calls is: Bot.some_method -> Bot._post -> Bot._do_post.
        So we can override Bot._do_post to add rate limiting.
        """
        rate_limit_args = self._extract_rl_kwargs(data)
        if not self.rate_limiter and rate_limit_args is not None:
            raise ValueError(
                "`rate_limit_args` can only be used if a `ExtBot.rate_limiter` is set."
            )

        # getting updates should not be rate limited!
        if endpoint == "getUpdates" or not self.rate_limiter:
            return await super()._do_post(
                endpoint=endpoint,
                data=data,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                read_timeout=read_timeout,
            )

        kwargs = {
            "read_timeout": read_timeout,
            "write_timeout": write_timeout,
            "connect_timeout": connect_timeout,
            "pool_timeout": pool_timeout,
        }
        self._LOGGER.debug(
            "Passing request through rate limiter of type %s with rate_limit_args %s",
            type(self.rate_limiter),
            rate_limit_args,
        )
        return await self.rate_limiter.process_request(
            callback=super()._do_post,
            args=(endpoint, data),
            kwargs=kwargs,
            endpoint=endpoint,
            data=data,
            rate_limit_args=rate_limit_args,
        )

    @property
    def defaults(self) -> "Defaults | None":
        """The :class:`telegram.ext.Defaults` used by this bot, if any."""
        # This is a property because defaults shouldn't be changed at runtime
        return self._defaults

    @property
    def rate_limiter(self) -> "BaseRateLimiter[RLARGS] | None":
        """The :class:`telegram.ext.BaseRateLimiter` used by this bot, if any.

        .. versionadded:: 20.0
        """
        # This is a property because the rate limiter shouldn't be changed at runtime
        return self._rate_limiter

    def _merge_lpo_defaults(self, lpo: ODVInput[LinkPreviewOptions]) -> LinkPreviewOptions | None:
        # This is a standalone method because both _insert_defaults and
        # _insert_defaults_for_ilq_results need this logic
        #
        # If Defaults.LPO is set, and LPO is passed in the bot method we should fuse
        # them, giving precedence to passed values.
        # Defaults.LPO(True, "google.com", True) & LPO=LPO(True, ..., False) ->
        # LPO(True, "google.com", False)
        if self.defaults is None or (defaults_lpo := self.defaults.link_preview_options) is None:
            return DefaultValue.get_value(lpo)
        return LinkPreviewOptions(
            **{
                attr: (
                    getattr(defaults_lpo, attr)
                    # only use the default value
                    # if the value was explicitly passed to the LPO object
                    if isinstance(orig_attr := getattr(lpo, attr), DefaultValue)
                    else orig_attr
                )
                for attr in defaults_lpo.__slots__
            }
        )

    def _insert_defaults(self, data: dict[str, object]) -> None:
        """Inserts the defaults values for optional kwargs for which tg.ext.Defaults provides
        convenience functionality, i.e. the kwargs with a tg.utils.helpers.DefaultValue default

        data is edited in-place. As timeout is not passed via the kwargs, it needs to be passed
        separately and gets returned.

        This can only work, if all kwargs that may have defaults are passed in data!
        """
        if self.defaults is None:
            # If we have no defaults to insert, the behavior is the same as in `tg.Bot`
            super()._insert_defaults(data)
            return

        # if we have Defaults, we
        # 1) replace all DefaultValue instances with the relevant Defaults value. If there is none,
        #    we fall back to the default value of the bot method
        # 2) convert all datetime.datetime objects to timestamps wrt the correct default timezone
        # 3) set the correct parse_mode for all InputMedia objects
        # 4) handle the LinkPreviewOptions case (see below)
        # 5) handle the ReplyParameters case (see below)
        # 6) handle text_parse_mode in InputPollOption
        for key, val in data.items():
            # 1)
            if isinstance(val, DefaultValue):
                data[key] = self.defaults.api_defaults.get(key, val.value)

            # 2)
            elif isinstance(val, dtm.datetime):
                data[key] = to_timestamp(val, tzinfo=self.defaults.tzinfo)

            # 3)
            elif isinstance(val, InputMedia) and val.parse_mode is DEFAULT_NONE:
                # Copy object as not to edit it in-place
                copied_val = copy(val)
                with copied_val._unfrozen():
                    copied_val.parse_mode = self.defaults.parse_mode
                data[key] = copied_val
            elif (
                key == "media"
                and isinstance(val, Sequence)
                and not isinstance(val[0], InputPaidMedia)
            ):
                # Copy objects as not to edit them in-place
                copy_list = [copy(media) for media in val]
                for media in copy_list:
                    if media.parse_mode is DEFAULT_NONE:
                        with media._unfrozen():
                            media.parse_mode = self.defaults.parse_mode

                data[key] = copy_list

            # 4) LinkPreviewOptions:
            elif isinstance(val, LinkPreviewOptions):
                data[key] = self._merge_lpo_defaults(val)

            # 5)
            # Similar to LinkPreviewOptions, but only two of the arguments of RPs have a default
            elif isinstance(val, ReplyParameters) and (
                (defaults_aswr := self.defaults.allow_sending_without_reply) is not None
                or self.defaults.quote_parse_mode is not None
            ):
                new_value = copy(val)
                with new_value._unfrozen():
                    new_value.allow_sending_without_reply = (
                        defaults_aswr
                        if isinstance(val.allow_sending_without_reply, DefaultValue)
                        else val.allow_sending_without_reply
                    )
                    new_value.quote_parse_mode = (
                        self.defaults.quote_parse_mode
                        if isinstance(val.quote_parse_mode, DefaultValue)
                        else val.quote_parse_mode
                    )

                data[key] = new_value

            # 6)
            elif isinstance(val, Sequence) and all(
                isinstance(obj, InputPollOption) for obj in val
            ):
                new_val = []
                for option in val:
                    if not isinstance(option.text_parse_mode, DefaultValue):
                        new_val.append(option)
                    else:
                        new_option = copy(option)
                        with new_option._unfrozen():
                            new_option.text_parse_mode = self.defaults.text_parse_mode
                        new_val.append(new_option)
                data[key] = new_val

    def _replace_keyboard(self, reply_markup: KT | None) -> KT | None:
        # If the reply_markup is an inline keyboard and we allow arbitrary callback data, let the
        # CallbackDataCache build a new keyboard with the data replaced. Otherwise return the input
        if isinstance(reply_markup, InlineKeyboardMarkup) and self.callback_data_cache is not None:
            # for some reason mypy doesn't understand that IKB is a subtype of KT | None
            return self.callback_data_cache.process_keyboard(  # type: ignore[return-value]
                reply_markup
            )

        return reply_markup

    def insert_callback_data(self, update: Update) -> None:
        """If this bot allows for arbitrary callback data, this inserts the cached data into all
        corresponding buttons within this update.

        Note:
            Checks :attr:`telegram.Message.via_bot` and :attr:`telegram.Message.from_user`
            to figure out if a) a reply markup exists and b) it was actually sent by this
            bot. If not, the message will be returned unchanged.

            Note that this will fail for channel posts, as :attr:`telegram.Message.from_user` is
            :obj:`None` for those! In the corresponding reply markups, the callback data will be
            replaced by :class:`telegram.ext.InvalidCallbackData`.

        Warning:
            *In place*, i.e. the passed :class:`telegram.Message` will be changed!

        Args:
            update (:class:`telegram.Update`): The update.

        """
        # The only incoming updates that can directly contain a message sent by the bot itself are:
        # * CallbackQueries
        # * Messages where the pinned_message is sent by the bot
        # * Messages where the reply_to_message is sent by the bot
        # * Messages where via_bot is the bot
        # Finally there is effective_chat.pinned message, but that's only returned in get_chat
        if update.callback_query:
            self._insert_callback_data(update.callback_query)
        # elif instead of if, as effective_message includes callback_query.message
        # and that has already been processed
        elif update.effective_message:
            self._insert_callback_data(update.effective_message)

    def _insert_callback_data(self, obj: HandledTypes) -> HandledTypes:
        if self.callback_data_cache is None:
            return obj

        if isinstance(obj, CallbackQuery):
            self.callback_data_cache.process_callback_query(obj)
            return obj

        if isinstance(obj, Message):
            if obj.reply_to_message:
                # reply_to_message can't contain further reply_to_messages, so no need to check
                self.callback_data_cache.process_message(obj.reply_to_message)
                if isinstance(obj.reply_to_message.pinned_message, Message):
                    # pinned messages can't contain reply_to_message, no need to check
                    self.callback_data_cache.process_message(obj.reply_to_message.pinned_message)
            if isinstance(obj.pinned_message, Message):
                # pinned messages can't contain reply_to_message, no need to check
                self.callback_data_cache.process_message(obj.pinned_message)

            # Finally, handle the message itself
            self.callback_data_cache.process_message(message=obj)
            return obj

        if isinstance(obj, ChatFullInfo) and obj.pinned_message:
            self.callback_data_cache.process_message(obj.pinned_message)

        return obj

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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Any:
        # We override this method to call self._replace_keyboard and self._insert_callback_data.
        # This covers most methods that have a reply_markup
        result = await super()._send_message(
            endpoint=endpoint,
            data=data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=self._replace_keyboard(reply_markup),
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            link_preview_options=link_preview_options,
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
        if isinstance(result, Message):
            self._insert_callback_data(result)
        return result

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
        updates = await super().get_updates(
            offset=offset,
            limit=limit,
            timeout=timeout,
            allowed_updates=allowed_updates,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

        for update in updates:
            self.insert_callback_data(update)

        return updates

    def _effective_inline_results(
        self,
        results: (
            Sequence["InlineQueryResult"] | Callable[[int], Sequence["InlineQueryResult"] | None]
        ),
        next_offset: str | None = None,
        current_offset: str | None = None,
    ) -> tuple[Sequence["InlineQueryResult"], str | None]:
        """This method is called by Bot.answer_inline_query to build the actual results list.
        Overriding this to call self._replace_keyboard suffices
        """
        effective_results, next_offset = super()._effective_inline_results(
            results=results, next_offset=next_offset, current_offset=current_offset
        )

        # Process arbitrary callback
        if self.callback_data_cache is None:
            return effective_results, next_offset
        results = []
        for result in effective_results:
            # All currently existingInlineQueryResults have a reply_markup, but future ones
            # might not have. Better be save than sorry
            if not hasattr(result, "reply_markup"):
                results.append(result)
            else:
                # We build a new result in case the user wants to use the same object in
                # different places
                new_result = copy(result)
                with new_result._unfrozen():
                    markup = self._replace_keyboard(result.reply_markup)
                    new_result.reply_markup = markup

                results.append(new_result)

        return results, next_offset

    @no_type_check  # mypy doesn't play too well with hasattr
    def _insert_defaults_for_ilq_results(self, res: "InlineQueryResult") -> "InlineQueryResult":
        """This method is called by Bot.answer_inline_query to replace `DefaultValue(obj)` with
        `obj`.
        Overriding this to call insert the actual desired default values.
        """
        if self.defaults is None:
            # If we have no defaults to insert, the behavior is the same as in `tg.Bot`
            return super()._insert_defaults_for_ilq_results(res)

        # Copy the objects that need modification to avoid modifying the original object
        copied = False
        if hasattr(res, "parse_mode") and res.parse_mode is DEFAULT_NONE:
            res = copy(res)
            with res._unfrozen():
                copied = True
                res.parse_mode = self.defaults.parse_mode
        if hasattr(res, "input_message_content") and res.input_message_content:
            if (
                hasattr(res.input_message_content, "parse_mode")
                and res.input_message_content.parse_mode is DEFAULT_NONE
            ):
                if not copied:
                    res = copy(res)
                    copied = True
                with res.input_message_content._unfrozen():
                    res.input_message_content.parse_mode = self.defaults.parse_mode
            if hasattr(res.input_message_content, "link_preview_options"):
                if not copied:
                    res = copy(res)
                with res.input_message_content._unfrozen():
                    if res.input_message_content.link_preview_options is DEFAULT_NONE:
                        res.input_message_content.link_preview_options = (
                            self.defaults.link_preview_options
                        )
                    else:
                        # merge the existing options with the defaults
                        res.input_message_content.link_preview_options = self._merge_lpo_defaults(
                            res.input_message_content.link_preview_options
                        )

        return res

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
        rate_limit_args: RLARGS | None = None,
    ) -> Any:
        return await super().do_api_request(
            endpoint=endpoint,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            return_type=return_type,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
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
        rate_limit_args: RLARGS | None = None,
    ) -> Poll:
        # We override this method to call self._replace_keyboard
        return await super().stop_poll(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=self._replace_keyboard(reply_markup),
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> MessageId:
        # We override this method to call self._replace_keyboard
        return await super().copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            caption=caption,
            video_start_timestamp=video_start_timestamp,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_markup=self._replace_keyboard(reply_markup),
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            show_caption_above_media=show_caption_above_media,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> tuple["MessageId", ...]:
        # We override this method to call self._replace_keyboard
        return await super().copy_messages(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_ids=message_ids,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            remove_caption=remove_caption,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            direct_messages_topic_id=direct_messages_topic_id,
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
        rate_limit_args: RLARGS | None = None,
    ) -> ChatFullInfo:
        # We override this method to call self._insert_callback_data
        result = await super().get_chat(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )
        return self._insert_callback_data(result)

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().add_sticker_to_set(
            user_id=user_id,
            name=name,
            sticker=sticker,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().answer_callback_query(
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
            url=url,
            cache_time=cache_time,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def answer_inline_query(
        self,
        inline_query_id: str,
        results: (
            Sequence["InlineQueryResult"] | Callable[[int], Sequence["InlineQueryResult"] | None]
        ),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().answer_inline_query(
            inline_query_id=inline_query_id,
            results=results,
            cache_time=cache_time,
            is_personal=is_personal,
            next_offset=next_offset,
            current_offset=current_offset,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            button=button,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> PreparedInlineMessage:
        return await super().save_prepared_inline_message(
            user_id=user_id,
            result=result,
            allow_user_chats=allow_user_chats,
            allow_bot_chats=allow_bot_chats,
            allow_group_chats=allow_group_chats,
            allow_channel_chats=allow_channel_chats,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().answer_pre_checkout_query(
            pre_checkout_query_id=pre_checkout_query_id,
            ok=ok,
            error_message=error_message,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().answer_shipping_query(
            shipping_query_id=shipping_query_id,
            ok=ok,
            shipping_options=shipping_options,
            error_message=error_message,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> SentWebAppMessage:
        return await super().answer_web_app_query(
            web_app_query_id=web_app_query_id,
            result=result,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().approve_chat_join_request(
            chat_id=chat_id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().ban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            until_date=until_date,
            revoke_messages=revoke_messages,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().ban_chat_sender_chat(
            chat_id=chat_id,
            sender_chat_id=sender_chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> ChatInviteLink:
        return await super().create_chat_invite_link(
            chat_id=chat_id,
            expire_date=expire_date,
            member_limit=member_limit,
            name=name,
            creates_join_request=creates_join_request,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> str:
        return await super().create_invoice_link(
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency=currency,
            prices=prices,
            max_tip_amount=max_tip_amount,
            suggested_tip_amounts=suggested_tip_amounts,
            provider_data=provider_data,
            photo_url=photo_url,
            photo_size=photo_size,
            photo_width=photo_width,
            photo_height=photo_height,
            need_name=need_name,
            need_phone_number=need_phone_number,
            need_email=need_email,
            need_shipping_address=need_shipping_address,
            send_phone_number_to_provider=send_phone_number_to_provider,
            send_email_to_provider=send_email_to_provider,
            is_flexible=is_flexible,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            subscription_period=subscription_period,
            business_connection_id=business_connection_id,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().create_new_sticker_set(
            user_id=user_id,
            name=name,
            title=title,
            stickers=stickers,
            sticker_type=sticker_type,
            needs_repainting=needs_repainting,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().decline_chat_join_request(
            chat_id=chat_id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_chat_photo(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_chat_sticker_set(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_forum_topic(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_message(
            chat_id=chat_id,
            message_id=message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def delete_messages(
        self,
        chat_id: str | int,
        message_ids: Sequence[int],
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_messages(
            chat_id=chat_id,
            message_ids=message_ids,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_my_commands(
            scope=scope,
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_sticker_from_set(
            sticker=sticker,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_webhook(
            drop_pending_updates=drop_pending_updates,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> ChatInviteLink:
        return await super().edit_chat_invite_link(
            chat_id=chat_id,
            invite_link=invite_link,
            expire_date=expire_date,
            member_limit=member_limit,
            name=name,
            creates_join_request=creates_join_request,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().edit_forum_topic(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            name=name,
            icon_custom_emoji_id=icon_custom_emoji_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().edit_general_forum_topic(
            chat_id=chat_id,
            name=name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> "Message | bool":
        return await super().edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            show_caption_above_media=show_caption_above_media,
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
        rate_limit_args: RLARGS | None = None,
    ) -> "Message | bool":
        return await super().edit_message_live_location(
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            latitude=latitude,
            longitude=longitude,
            reply_markup=reply_markup,
            horizontal_accuracy=horizontal_accuracy,
            heading=heading,
            proximity_alert_radius=proximity_alert_radius,
            live_period=live_period,
            location=location,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> "Message | bool":
        return await super().edit_message_media(
            media=media,
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> "Message | bool":
        return await super().edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> "Message | bool":
        return await super().edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=reply_markup,
            entities=entities,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            link_preview_options=link_preview_options,
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
        rate_limit_args: RLARGS | None = None,
    ) -> str:
        return await super().export_chat_invite_link(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().forward_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            video_start_timestamp=video_start_timestamp,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            suggested_post_parameters=suggested_post_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> tuple[MessageId, ...]:
        return await super().forward_messages(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_ids=message_ids,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            direct_messages_topic_id=direct_messages_topic_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_chat_administrators(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> tuple[ChatMember, ...]:
        return await super().get_chat_administrators(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> ChatMember:
        return await super().get_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_chat_member_count(
        self,
        chat_id: str | int,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> int:
        return await super().get_chat_member_count(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> MenuButton:
        return await super().get_chat_menu_button(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> File:
        return await super().get_file(
            file_id=file_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_forum_topic_icon_stickers(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> tuple[Sticker, ...]:
        return await super().get_forum_topic_icon_stickers(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> tuple[GameHighScore, ...]:
        return await super().get_game_high_scores(
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_me(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> User:
        return await super().get_me(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> tuple[BotCommand, ...]:
        return await super().get_my_commands(
            scope=scope,
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> ChatAdministratorRights:
        return await super().get_my_default_administrator_rights(
            for_channels=for_channels,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> StickerSet:
        return await super().get_sticker_set(
            name=name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_custom_emoji_stickers(
        self,
        custom_emoji_ids: Sequence[str],
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> tuple[Sticker, ...]:
        return await super().get_custom_emoji_stickers(
            custom_emoji_ids=custom_emoji_ids,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> "UserProfilePhotos":
        return await super().get_user_profile_photos(
            user_id=user_id,
            offset=offset,
            limit=limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_webhook_info(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> WebhookInfo:
        return await super().get_webhook_info(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().leave_chat(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def log_out(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().log_out(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def close(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().close(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().close_forum_topic(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().close_general_forum_topic(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> ForumTopic:
        return await super().create_forum_topic(
            chat_id=chat_id,
            name=name,
            icon_color=icon_color,
            icon_custom_emoji_id=icon_custom_emoji_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().reopen_general_forum_topic(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().hide_general_forum_topic(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().unhide_general_forum_topic(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().pin_chat_message(
            chat_id=chat_id,
            message_id=message_id,
            disable_notification=disable_notification,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            business_connection_id=business_connection_id,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().promote_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            can_change_info=can_change_info,
            can_post_messages=can_post_messages,
            can_edit_messages=can_edit_messages,
            can_delete_messages=can_delete_messages,
            can_invite_users=can_invite_users,
            can_restrict_members=can_restrict_members,
            can_pin_messages=can_pin_messages,
            can_promote_members=can_promote_members,
            is_anonymous=is_anonymous,
            can_manage_chat=can_manage_chat,
            can_manage_video_chats=can_manage_video_chats,
            can_manage_topics=can_manage_topics,
            can_post_stories=can_post_stories,
            can_edit_stories=can_edit_stories,
            can_delete_stories=can_delete_stories,
            can_manage_direct_messages=can_manage_direct_messages,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().reopen_forum_topic(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date,
            use_independent_chat_permissions=use_independent_chat_permissions,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> ChatInviteLink:
        return await super().revoke_chat_invite_link(
            chat_id=chat_id,
            invite_link=invite_link,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_animation(
            chat_id=chat_id,
            animation=animation,
            duration=duration,
            width=width,
            height=height,
            caption=caption,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            has_spoiler=has_spoiler,
            thumbnail=thumbnail,
            reply_parameters=reply_parameters,
            filename=filename,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            business_connection_id=business_connection_id,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_audio(
            chat_id=chat_id,
            audio=audio,
            duration=duration,
            performer=performer,
            business_connection_id=business_connection_id,
            title=title,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            thumbnail=thumbnail,
            reply_parameters=reply_parameters,
            filename=filename,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().send_chat_action(
            chat_id=chat_id,
            business_connection_id=business_connection_id,
            action=action,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        contact: "Contact | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_contact(
            chat_id=chat_id,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            vcard=vcard,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            contact=contact,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            business_connection_id=business_connection_id,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            message_effect_id=message_effect_id,
            direct_messages_topic_id=direct_messages_topic_id,
            allow_paid_broadcast=allow_paid_broadcast,
            suggested_post_parameters=suggested_post_parameters,
        )

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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_checklist(
            business_connection_id=business_connection_id,
            chat_id=chat_id,
            checklist=checklist,
            disable_notification=disable_notification,
            protect_content=protect_content,
            message_effect_id=message_effect_id,
            reply_parameters=reply_parameters,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=allow_sending_without_reply,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().edit_message_checklist(
            business_connection_id=business_connection_id,
            chat_id=chat_id,
            message_id=message_id,
            checklist=checklist,
            reply_markup=reply_markup,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_dice(
            chat_id=chat_id,
            disable_notification=disable_notification,
            business_connection_id=business_connection_id,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            emoji=emoji,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_document(
            chat_id=chat_id,
            document=document,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_content_type_detection=disable_content_type_detection,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            protect_content=protect_content,
            business_connection_id=business_connection_id,
            message_thread_id=message_thread_id,
            thumbnail=thumbnail,
            reply_parameters=reply_parameters,
            filename=filename,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_game(
            chat_id=chat_id,
            game_short_name=game_short_name,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
        )

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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency=currency,
            prices=prices,
            start_parameter=start_parameter,
            photo_url=photo_url,
            photo_size=photo_size,
            photo_width=photo_width,
            photo_height=photo_height,
            need_name=need_name,
            need_phone_number=need_phone_number,
            need_email=need_email,
            need_shipping_address=need_shipping_address,
            is_flexible=is_flexible,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            provider_data=provider_data,
            send_phone_number_to_provider=send_phone_number_to_provider,
            send_email_to_provider=send_email_to_provider,
            allow_sending_without_reply=allow_sending_without_reply,
            max_tip_amount=max_tip_amount,
            suggested_tip_amounts=suggested_tip_amounts,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )

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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        location: "Location | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_location(
            chat_id=chat_id,
            latitude=latitude,
            longitude=longitude,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            live_period=live_period,
            horizontal_accuracy=horizontal_accuracy,
            heading=heading,
            proximity_alert_radius=proximity_alert_radius,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            location=location,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            business_connection_id=business_connection_id,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
    ) -> tuple[Message, ...]:
        return await super().send_media_group(
            chat_id=chat_id,
            media=media,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            caption=caption,
            business_connection_id=business_connection_id,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
        )

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
        disable_web_page_preview: bool | None = None,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            entities=entities,
            disable_web_page_preview=disable_web_page_preview,
            disable_notification=disable_notification,
            business_connection_id=business_connection_id,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_markup=reply_markup,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            link_preview_options=link_preview_options,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().send_message_draft(
            chat_id=chat_id,
            draft_id=draft_id,
            text=text,
            message_thread_id=message_thread_id,
            parse_mode=parse_mode,
            entities=entities,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            has_spoiler=has_spoiler,
            reply_parameters=reply_parameters,
            filename=filename,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_poll(
            chat_id=chat_id,
            question=question,
            options=options,
            is_anonymous=is_anonymous,
            type=type,
            allows_multiple_answers=allows_multiple_answers,
            correct_option_id=correct_option_id,
            is_closed=is_closed,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            explanation=explanation,
            explanation_parse_mode=explanation_parse_mode,
            open_period=open_period,
            close_date=close_date,
            allow_sending_without_reply=allow_sending_without_reply,
            explanation_entities=explanation_entities,
            business_connection_id=business_connection_id,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            question_parse_mode=question_parse_mode,
            question_entities=question_entities,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_sticker(
            chat_id=chat_id,
            sticker=sticker,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            emoji=emoji,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        venue: "Venue | None" = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_venue(
            chat_id=chat_id,
            latitude=latitude,
            longitude=longitude,
            title=title,
            address=address,
            foursquare_id=foursquare_id,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            foursquare_type=foursquare_type,
            google_place_id=google_place_id,
            google_place_type=google_place_type,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            business_connection_id=business_connection_id,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            venue=venue,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_video(
            chat_id=chat_id,
            video=video,
            duration=duration,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            width=width,
            height=height,
            parse_mode=parse_mode,
            supports_streaming=supports_streaming,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            business_connection_id=business_connection_id,
            has_spoiler=has_spoiler,
            thumbnail=thumbnail,
            cover=cover,
            start_timestamp=start_timestamp,
            filename=filename,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            show_caption_above_media=show_caption_above_media,
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_video_note(
            chat_id=chat_id,
            video_note=video_note,
            duration=duration,
            length=length,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            thumbnail=thumbnail,
            reply_parameters=reply_parameters,
            filename=filename,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        filename: str | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_voice(
            chat_id=chat_id,
            voice=voice,
            duration=duration,
            caption=caption,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            allow_sending_without_reply=allow_sending_without_reply,
            caption_entities=caption_entities,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            filename=filename,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            direct_messages_topic_id=direct_messages_topic_id,
            allow_paid_broadcast=allow_paid_broadcast,
            suggested_post_parameters=suggested_post_parameters,
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_chat_administrator_custom_title(
            chat_id=chat_id,
            user_id=user_id,
            custom_title=custom_title,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_chat_description(
            chat_id=chat_id,
            description=description,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_user_emoji_status(
            user_id=user_id,
            emoji_status_custom_emoji_id=emoji_status_custom_emoji_id,
            emoji_status_expiration_date=emoji_status_expiration_date,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_chat_menu_button(
            chat_id=chat_id,
            menu_button=menu_button,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_chat_permissions(
            chat_id=chat_id,
            permissions=permissions,
            use_independent_chat_permissions=use_independent_chat_permissions,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_chat_photo(
            chat_id=chat_id,
            photo=photo,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_chat_sticker_set(
            chat_id=chat_id,
            sticker_set_name=sticker_set_name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_chat_title(
            chat_id=chat_id,
            title=title,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> "Message | bool":
        return await super().set_game_score(
            user_id=user_id,
            score=score,
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            force=force,
            disable_edit_message=disable_edit_message,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_my_commands(
            commands=commands,
            scope=scope,
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_my_default_administrator_rights(
            rights=rights,
            for_channels=for_channels,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_passport_data_errors(
            user_id=user_id,
            errors=errors,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_sticker_position_in_set(
            sticker=sticker,
            position=position,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_sticker_set_thumbnail(
            name=name,
            user_id=user_id,
            thumbnail=thumbnail,
            format=format,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_webhook(
            url=url,
            certificate=certificate,
            max_connections=max_connections,
            allowed_updates=allowed_updates,
            ip_address=ip_address,
            drop_pending_updates=drop_pending_updates,
            secret_token=secret_token,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> "Message | bool":
        return await super().stop_message_live_location(
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().unban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            only_if_banned=only_if_banned,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().unban_chat_sender_chat(
            chat_id=chat_id,
            sender_chat_id=sender_chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().unpin_all_chat_messages(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().unpin_chat_message(
            chat_id=chat_id,
            message_id=message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            business_connection_id=business_connection_id,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().unpin_all_forum_topic_messages(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().unpin_all_general_forum_topic_messages(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> File:
        return await super().upload_sticker_file(
            user_id=user_id,
            sticker=sticker,
            sticker_format=sticker_format,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_my_description(
            description=description,
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_my_short_description(
            short_description=short_description,
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> BotDescription:
        return await super().get_my_description(
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> BotShortDescription:
        return await super().get_my_short_description(
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_my_name(
            name=name,
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> BotName:
        return await super().get_my_name(
            language_code=language_code,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_custom_emoji_sticker_set_thumbnail(
            name=name,
            custom_emoji_id=custom_emoji_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_sticker_set_title(
            name=name,
            title=title,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_sticker_set(
            name=name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_sticker_emoji_list(
            sticker=sticker,
            emoji_list=emoji_list,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_sticker_keywords(
            sticker=sticker,
            keywords=keywords,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_sticker_mask_position(
            sticker=sticker,
            mask_position=mask_position,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> UserChatBoosts:
        return await super().get_user_chat_boosts(
            chat_id=chat_id,
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=reaction,
            is_big=is_big,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().gift_premium_subscription(
            user_id=user_id,
            month_count=month_count,
            star_count=star_count,
            text=text,
            text_parse_mode=text_parse_mode,
            text_entities=text_entities,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> BusinessConnection:
        return await super().get_business_connection(
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_business_account_gifts(
        self,
        business_connection_id: str,
        exclude_unsaved: bool | None = None,
        exclude_saved: bool | None = None,
        exclude_unlimited: bool | None = None,
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
        rate_limit_args: RLARGS | None = None,
    ) -> OwnedGifts:
        return await super().get_business_account_gifts(
            business_connection_id=business_connection_id,
            exclude_unsaved=exclude_unsaved,
            exclude_saved=exclude_saved,
            exclude_unlimited=exclude_unlimited,
            exclude_limited=exclude_limited,
            exclude_limited_upgradable=exclude_limited_upgradable,
            exclude_limited_non_upgradable=exclude_limited_non_upgradable,
            exclude_unique=exclude_unique,
            exclude_from_blockchain=exclude_from_blockchain,
            sort_by_price=sort_by_price,
            offset=offset,
            limit=limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> StarAmount:
        return await super().get_business_account_star_balance(
            business_connection_id=business_connection_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().read_business_message(
            business_connection_id=business_connection_id,
            chat_id=chat_id,
            message_id=message_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_business_messages(
            business_connection_id=business_connection_id,
            message_ids=message_ids,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> Story:
        return await super().post_story(
            business_connection_id=business_connection_id,
            content=content,
            active_period=active_period,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            areas=areas,
            post_to_chat_page=post_to_chat_page,
            protect_content=protect_content,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> Story:
        return await super().edit_story(
            business_connection_id=business_connection_id,
            story_id=story_id,
            content=content,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            areas=areas,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().delete_story(
            business_connection_id=business_connection_id,
            story_id=story_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_business_account_name(
            business_connection_id=business_connection_id,
            first_name=first_name,
            last_name=last_name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_business_account_username(
            business_connection_id=business_connection_id,
            username=username,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_business_account_bio(
            business_connection_id=business_connection_id,
            bio=bio,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_business_account_gift_settings(
            business_connection_id=business_connection_id,
            show_gift_button=show_gift_button,
            accepted_gift_types=accepted_gift_types,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().set_business_account_profile_photo(
            business_connection_id=business_connection_id,
            photo=photo,
            is_public=is_public,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().remove_business_account_profile_photo(
            business_connection_id=business_connection_id,
            is_public=is_public,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().convert_gift_to_stars(
            business_connection_id=business_connection_id,
            owned_gift_id=owned_gift_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().upgrade_gift(
            business_connection_id=business_connection_id,
            owned_gift_id=owned_gift_id,
            keep_original_details=keep_original_details,
            star_count=star_count,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().transfer_gift(
            business_connection_id=business_connection_id,
            owned_gift_id=owned_gift_id,
            new_owner_chat_id=new_owner_chat_id,
            star_count=star_count,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().transfer_business_account_stars(
            business_connection_id=business_connection_id,
            star_count=star_count,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().replace_sticker_in_set(
            user_id=user_id,
            name=name,
            old_sticker=old_sticker,
            sticker=sticker,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().refund_star_payment(
            user_id=user_id,
            telegram_payment_charge_id=telegram_payment_charge_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> StarTransactions:
        return await super().get_star_transactions(
            offset=offset,
            limit=limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().edit_user_star_subscription(
            user_id=user_id,
            telegram_payment_charge_id=telegram_payment_charge_id,
            is_canceled=is_canceled,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_paid_media(
            chat_id=chat_id,
            star_count=star_count,
            media=media,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            show_caption_above_media=show_caption_above_media,
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
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            business_connection_id=business_connection_id,
            payload=payload,
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
        rate_limit_args: RLARGS | None = None,
    ) -> ChatInviteLink:
        return await super().create_chat_subscription_invite_link(
            chat_id=chat_id,
            subscription_period=subscription_period,
            subscription_price=subscription_price,
            name=name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> ChatInviteLink:
        return await super().edit_chat_subscription_invite_link(
            chat_id=chat_id,
            invite_link=invite_link,
            name=name,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_available_gifts(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Gifts:
        return await super().get_available_gifts(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().send_gift(
            user_id=user_id,
            chat_id=chat_id,
            gift_id=gift_id,
            text=text,
            text_parse_mode=text_parse_mode,
            text_entities=text_entities,
            pay_for_upgrade=pay_for_upgrade,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().verify_chat(
            chat_id=chat_id,
            custom_description=custom_description,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().verify_user(
            user_id=user_id,
            custom_description=custom_description,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().remove_chat_verification(
            chat_id=chat_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().remove_user_verification(
            user_id=user_id,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    async def get_my_star_balance(
        self,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> StarAmount:
        return await super().get_my_star_balance(
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().decline_suggested_post(
            chat_id=chat_id,
            message_id=message_id,
            comment=comment,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> bool:
        return await super().approve_suggested_post(
            chat_id=chat_id,
            message_id=message_id,
            send_date=send_date,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> Story:
        return await super().repost_story(
            business_connection_id=business_connection_id,
            from_chat_id=from_chat_id,
            from_story_id=from_story_id,
            active_period=active_period,
            post_to_chat_page=post_to_chat_page,
            protect_content=protect_content,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
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
        rate_limit_args: RLARGS | None = None,
    ) -> OwnedGifts:
        return await super().get_user_gifts(
            user_id=user_id,
            exclude_unlimited=exclude_unlimited,
            exclude_limited_upgradable=exclude_limited_upgradable,
            exclude_limited_non_upgradable=exclude_limited_non_upgradable,
            exclude_from_blockchain=exclude_from_blockchain,
            exclude_unique=exclude_unique,
            sort_by_price=sort_by_price,
            offset=offset,
            limit=limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

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
        rate_limit_args: RLARGS | None = None,
    ) -> OwnedGifts:
        return await super().get_chat_gifts(
            chat_id=chat_id,
            exclude_unsaved=exclude_unsaved,
            exclude_saved=exclude_saved,
            exclude_unlimited=exclude_unlimited,
            exclude_limited_upgradable=exclude_limited_upgradable,
            exclude_limited_non_upgradable=exclude_limited_non_upgradable,
            exclude_from_blockchain=exclude_from_blockchain,
            exclude_unique=exclude_unique,
            sort_by_price=sort_by_price,
            offset=offset,
            limit=limit,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
        )

    # updated camelCase aliases
    getMe = get_me
    sendMessage = send_message
    sendMessageDraft = send_message_draft
    deleteMessage = delete_message
    deleteMessages = delete_messages
    forwardMessage = forward_message
    forwardMessages = forward_messages
    sendPhoto = send_photo
    sendAudio = send_audio
    sendDocument = send_document
    sendSticker = send_sticker
    sendVideo = send_video
    sendAnimation = send_animation
    sendVoice = send_voice
    sendVideoNote = send_video_note
    sendMediaGroup = send_media_group
    sendLocation = send_location
    editMessageLiveLocation = edit_message_live_location
    stopMessageLiveLocation = stop_message_live_location
    sendVenue = send_venue
    sendContact = send_contact
    sendGame = send_game
    sendChatAction = send_chat_action
    answerInlineQuery = answer_inline_query
    savePreparedInlineMessage = save_prepared_inline_message
    getUserProfilePhotos = get_user_profile_photos
    getFile = get_file
    banChatMember = ban_chat_member
    banChatSenderChat = ban_chat_sender_chat
    unbanChatMember = unban_chat_member
    unbanChatSenderChat = unban_chat_sender_chat
    answerCallbackQuery = answer_callback_query
    editMessageText = edit_message_text
    editMessageCaption = edit_message_caption
    editMessageMedia = edit_message_media
    editMessageReplyMarkup = edit_message_reply_markup
    getUpdates = get_updates
    setWebhook = set_webhook
    deleteWebhook = delete_webhook
    leaveChat = leave_chat
    getChat = get_chat
    getChatAdministrators = get_chat_administrators
    getChatMember = get_chat_member
    setChatStickerSet = set_chat_sticker_set
    deleteChatStickerSet = delete_chat_sticker_set
    getChatMemberCount = get_chat_member_count
    getWebhookInfo = get_webhook_info
    setGameScore = set_game_score
    getGameHighScores = get_game_high_scores
    sendInvoice = send_invoice
    answerShippingQuery = answer_shipping_query
    answerPreCheckoutQuery = answer_pre_checkout_query
    answerWebAppQuery = answer_web_app_query
    restrictChatMember = restrict_chat_member
    promoteChatMember = promote_chat_member
    setChatPermissions = set_chat_permissions
    setChatAdministratorCustomTitle = set_chat_administrator_custom_title
    exportChatInviteLink = export_chat_invite_link
    createChatInviteLink = create_chat_invite_link
    editChatInviteLink = edit_chat_invite_link
    revokeChatInviteLink = revoke_chat_invite_link
    approveChatJoinRequest = approve_chat_join_request
    declineChatJoinRequest = decline_chat_join_request
    setChatPhoto = set_chat_photo
    deleteChatPhoto = delete_chat_photo
    setChatTitle = set_chat_title
    setChatDescription = set_chat_description
    setUserEmojiStatus = set_user_emoji_status
    pinChatMessage = pin_chat_message
    unpinChatMessage = unpin_chat_message
    unpinAllChatMessages = unpin_all_chat_messages
    getStickerSet = get_sticker_set
    getCustomEmojiStickers = get_custom_emoji_stickers
    uploadStickerFile = upload_sticker_file
    createNewStickerSet = create_new_sticker_set
    addStickerToSet = add_sticker_to_set
    setStickerPositionInSet = set_sticker_position_in_set
    deleteStickerFromSet = delete_sticker_from_set
    setStickerSetThumbnail = set_sticker_set_thumbnail
    setPassportDataErrors = set_passport_data_errors
    sendPoll = send_poll
    stopPoll = stop_poll
    sendChecklist = send_checklist
    editMessageChecklist = edit_message_checklist
    sendDice = send_dice
    getMyCommands = get_my_commands
    setMyCommands = set_my_commands
    deleteMyCommands = delete_my_commands
    logOut = log_out
    copyMessage = copy_message
    copyMessages = copy_messages
    getChatMenuButton = get_chat_menu_button
    setChatMenuButton = set_chat_menu_button
    getMyDefaultAdministratorRights = get_my_default_administrator_rights
    setMyDefaultAdministratorRights = set_my_default_administrator_rights
    createInvoiceLink = create_invoice_link
    getForumTopicIconStickers = get_forum_topic_icon_stickers
    createForumTopic = create_forum_topic
    editForumTopic = edit_forum_topic
    closeForumTopic = close_forum_topic
    reopenForumTopic = reopen_forum_topic
    deleteForumTopic = delete_forum_topic
    unpinAllForumTopicMessages = unpin_all_forum_topic_messages
    editGeneralForumTopic = edit_general_forum_topic
    closeGeneralForumTopic = close_general_forum_topic
    reopenGeneralForumTopic = reopen_general_forum_topic
    hideGeneralForumTopic = hide_general_forum_topic
    unhideGeneralForumTopic = unhide_general_forum_topic
    setMyDescription = set_my_description
    getMyDescription = get_my_description
    setMyShortDescription = set_my_short_description
    getMyShortDescription = get_my_short_description
    setCustomEmojiStickerSetThumbnail = set_custom_emoji_sticker_set_thumbnail
    setStickerSetTitle = set_sticker_set_title
    deleteStickerSet = delete_sticker_set
    setStickerEmojiList = set_sticker_emoji_list
    setStickerKeywords = set_sticker_keywords
    setStickerMaskPosition = set_sticker_mask_position
    setMyName = set_my_name
    getMyName = get_my_name
    unpinAllGeneralForumTopicMessages = unpin_all_general_forum_topic_messages
    getUserChatBoosts = get_user_chat_boosts
    setMessageReaction = set_message_reaction
    giftPremiumSubscription = gift_premium_subscription
    getBusinessConnection = get_business_connection
    getBusinessAccountGifts = get_business_account_gifts
    getBusinessAccountStarBalance = get_business_account_star_balance
    readBusinessMessage = read_business_message
    deleteBusinessMessages = delete_business_messages
    postStory = post_story
    editStory = edit_story
    deleteStory = delete_story
    setBusinessAccountName = set_business_account_name
    setBusinessAccountUsername = set_business_account_username
    setBusinessAccountBio = set_business_account_bio
    setBusinessAccountGiftSettings = set_business_account_gift_settings
    setBusinessAccountProfilePhoto = set_business_account_profile_photo
    removeBusinessAccountProfilePhoto = remove_business_account_profile_photo
    convertGiftToStars = convert_gift_to_stars
    upgradeGift = upgrade_gift
    transferGift = transfer_gift
    transferBusinessAccountStars = transfer_business_account_stars
    replaceStickerInSet = replace_sticker_in_set
    refundStarPayment = refund_star_payment
    getStarTransactions = get_star_transactions
    editUserStarSubscription = edit_user_star_subscription
    createChatSubscriptionInviteLink = create_chat_subscription_invite_link
    editChatSubscriptionInviteLink = edit_chat_subscription_invite_link
    sendPaidMedia = send_paid_media
    getAvailableGifts = get_available_gifts
    sendGift = send_gift
    verifyChat = verify_chat
    verifyUser = verify_user
    removeChatVerification = remove_chat_verification
    removeUserVerification = remove_user_verification
    getMyStarBalance = get_my_star_balance
    approveSuggestedPost = approve_suggested_post
    declineSuggestedPost = decline_suggested_post
    repostStory = repost_story
    getUserGifts = get_user_gifts
    getChatGifts = get_chat_gifts
