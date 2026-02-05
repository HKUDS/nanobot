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
"""A library that provides a Python interface to the Telegram Bot API"""

__author__ = "devs@python-telegram-bot.org"
__all__ = (
    "AcceptedGiftTypes",
    "AffiliateInfo",
    "Animation",
    "Audio",
    "BackgroundFill",
    "BackgroundFillFreeformGradient",
    "BackgroundFillGradient",
    "BackgroundFillSolid",
    "BackgroundType",
    "BackgroundTypeChatTheme",
    "BackgroundTypeFill",
    "BackgroundTypePattern",
    "BackgroundTypeWallpaper",
    "Birthdate",
    "Bot",
    "BotCommand",
    "BotCommandScope",
    "BotCommandScopeAllChatAdministrators",
    "BotCommandScopeAllGroupChats",
    "BotCommandScopeAllPrivateChats",
    "BotCommandScopeChat",
    "BotCommandScopeChatAdministrators",
    "BotCommandScopeChatMember",
    "BotCommandScopeDefault",
    "BotDescription",
    "BotName",
    "BotShortDescription",
    "BusinessBotRights",
    "BusinessConnection",
    "BusinessIntro",
    "BusinessLocation",
    "BusinessMessagesDeleted",
    "BusinessOpeningHours",
    "BusinessOpeningHoursInterval",
    "CallbackGame",
    "CallbackQuery",
    "Chat",
    "ChatAdministratorRights",
    "ChatBackground",
    "ChatBoost",
    "ChatBoostAdded",
    "ChatBoostRemoved",
    "ChatBoostSource",
    "ChatBoostSourceGiftCode",
    "ChatBoostSourceGiveaway",
    "ChatBoostSourcePremium",
    "ChatBoostUpdated",
    "ChatFullInfo",
    "ChatInviteLink",
    "ChatJoinRequest",
    "ChatLocation",
    "ChatMember",
    "ChatMemberAdministrator",
    "ChatMemberBanned",
    "ChatMemberLeft",
    "ChatMemberMember",
    "ChatMemberOwner",
    "ChatMemberRestricted",
    "ChatMemberUpdated",
    "ChatPermissions",
    "ChatPhoto",
    "ChatShared",
    "Checklist",
    "ChecklistTask",
    "ChecklistTasksAdded",
    "ChecklistTasksDone",
    "ChosenInlineResult",
    "Contact",
    "CopyTextButton",
    "Credentials",
    "DataCredentials",
    "Dice",
    "DirectMessagePriceChanged",
    "DirectMessagesTopic",
    "Document",
    "EncryptedCredentials",
    "EncryptedPassportElement",
    "ExternalReplyInfo",
    "File",
    "FileCredentials",
    "ForceReply",
    "ForumTopic",
    "ForumTopicClosed",
    "ForumTopicCreated",
    "ForumTopicEdited",
    "ForumTopicReopened",
    "Game",
    "GameHighScore",
    "GeneralForumTopicHidden",
    "GeneralForumTopicUnhidden",
    "Gift",
    "GiftBackground",
    "GiftInfo",
    "Gifts",
    "Giveaway",
    "GiveawayCompleted",
    "GiveawayCreated",
    "GiveawayWinners",
    "IdDocumentData",
    "InaccessibleMessage",
    "InlineKeyboardButton",
    "InlineKeyboardMarkup",
    "InlineQuery",
    "InlineQueryResult",
    "InlineQueryResultArticle",
    "InlineQueryResultAudio",
    "InlineQueryResultCachedAudio",
    "InlineQueryResultCachedDocument",
    "InlineQueryResultCachedGif",
    "InlineQueryResultCachedMpeg4Gif",
    "InlineQueryResultCachedPhoto",
    "InlineQueryResultCachedSticker",
    "InlineQueryResultCachedVideo",
    "InlineQueryResultCachedVoice",
    "InlineQueryResultContact",
    "InlineQueryResultDocument",
    "InlineQueryResultGame",
    "InlineQueryResultGif",
    "InlineQueryResultLocation",
    "InlineQueryResultMpeg4Gif",
    "InlineQueryResultPhoto",
    "InlineQueryResultVenue",
    "InlineQueryResultVideo",
    "InlineQueryResultVoice",
    "InlineQueryResultsButton",
    "InputChecklist",
    "InputChecklistTask",
    "InputContactMessageContent",
    "InputFile",
    "InputInvoiceMessageContent",
    "InputLocationMessageContent",
    "InputMedia",
    "InputMediaAnimation",
    "InputMediaAudio",
    "InputMediaDocument",
    "InputMediaPhoto",
    "InputMediaVideo",
    "InputMessageContent",
    "InputPaidMedia",
    "InputPaidMediaPhoto",
    "InputPaidMediaVideo",
    "InputPollOption",
    "InputProfilePhoto",
    "InputProfilePhotoAnimated",
    "InputProfilePhotoStatic",
    "InputSticker",
    "InputStoryContent",
    "InputStoryContentPhoto",
    "InputStoryContentVideo",
    "InputTextMessageContent",
    "InputVenueMessageContent",
    "Invoice",
    "KeyboardButton",
    "KeyboardButtonPollType",
    "KeyboardButtonRequestChat",
    "KeyboardButtonRequestUsers",
    "LabeledPrice",
    "LinkPreviewOptions",
    "Location",
    "LocationAddress",
    "LoginUrl",
    "MaskPosition",
    "MaybeInaccessibleMessage",
    "MenuButton",
    "MenuButtonCommands",
    "MenuButtonDefault",
    "MenuButtonWebApp",
    "Message",
    "MessageAutoDeleteTimerChanged",
    "MessageEntity",
    "MessageId",
    "MessageOrigin",
    "MessageOriginChannel",
    "MessageOriginChat",
    "MessageOriginHiddenUser",
    "MessageOriginUser",
    "MessageReactionCountUpdated",
    "MessageReactionUpdated",
    "OrderInfo",
    "OwnedGift",
    "OwnedGiftRegular",
    "OwnedGiftUnique",
    "OwnedGifts",
    "PaidMedia",
    "PaidMediaInfo",
    "PaidMediaPhoto",
    "PaidMediaPreview",
    "PaidMediaPurchased",
    "PaidMediaVideo",
    "PaidMessagePriceChanged",
    "PassportData",
    "PassportElementError",
    "PassportElementErrorDataField",
    "PassportElementErrorFile",
    "PassportElementErrorFiles",
    "PassportElementErrorFrontSide",
    "PassportElementErrorReverseSide",
    "PassportElementErrorSelfie",
    "PassportElementErrorTranslationFile",
    "PassportElementErrorTranslationFiles",
    "PassportElementErrorUnspecified",
    "PassportFile",
    "PersonalDetails",
    "PhotoSize",
    "Poll",
    "PollAnswer",
    "PollOption",
    "PreCheckoutQuery",
    "PreparedInlineMessage",
    "ProximityAlertTriggered",
    "ReactionCount",
    "ReactionType",
    "ReactionTypeCustomEmoji",
    "ReactionTypeEmoji",
    "ReactionTypePaid",
    "RefundedPayment",
    "ReplyKeyboardMarkup",
    "ReplyKeyboardRemove",
    "ReplyParameters",
    "ResidentialAddress",
    "RevenueWithdrawalState",
    "RevenueWithdrawalStateFailed",
    "RevenueWithdrawalStatePending",
    "RevenueWithdrawalStateSucceeded",
    "SecureData",
    "SecureValue",
    "SentWebAppMessage",
    "SharedUser",
    "ShippingAddress",
    "ShippingOption",
    "ShippingQuery",
    "StarAmount",
    "StarTransaction",
    "StarTransactions",
    "Sticker",
    "StickerSet",
    "Story",
    "StoryArea",
    "StoryAreaPosition",
    "StoryAreaType",
    "StoryAreaTypeLink",
    "StoryAreaTypeLocation",
    "StoryAreaTypeSuggestedReaction",
    "StoryAreaTypeUniqueGift",
    "StoryAreaTypeWeather",
    "SuccessfulPayment",
    "SuggestedPostApprovalFailed",
    "SuggestedPostApproved",
    "SuggestedPostDeclined",
    "SuggestedPostInfo",
    "SuggestedPostPaid",
    "SuggestedPostParameters",
    "SuggestedPostPrice",
    "SuggestedPostRefunded",
    "SwitchInlineQueryChosenChat",
    "TelegramObject",
    "TextQuote",
    "TransactionPartner",
    "TransactionPartnerAffiliateProgram",
    "TransactionPartnerChat",
    "TransactionPartnerFragment",
    "TransactionPartnerOther",
    "TransactionPartnerTelegramAds",
    "TransactionPartnerTelegramApi",
    "TransactionPartnerUser",
    "UniqueGift",
    "UniqueGiftBackdrop",
    "UniqueGiftBackdropColors",
    "UniqueGiftColors",
    "UniqueGiftInfo",
    "UniqueGiftModel",
    "UniqueGiftSymbol",
    "Update",
    "User",
    "UserChatBoosts",
    "UserProfilePhotos",
    "UserRating",
    "UsersShared",
    "Venue",
    "Video",
    "VideoChatEnded",
    "VideoChatParticipantsInvited",
    "VideoChatScheduled",
    "VideoChatStarted",
    "VideoNote",
    "Voice",
    "WebAppData",
    "WebAppInfo",
    "WebhookInfo",
    "WriteAccessAllowed",
    "__bot_api_version__",
    "__bot_api_version_info__",
    "__version__",
    "__version_info__",
    "constants",
    "error",
    "helpers",
    "request",
    "warnings",
)

from telegram._inputchecklist import InputChecklist, InputChecklistTask
from telegram._payment.stars.staramount import StarAmount
from telegram._payment.stars.startransactions import StarTransaction, StarTransactions
from telegram._payment.stars.transactionpartner import (
    TransactionPartner,
    TransactionPartnerAffiliateProgram,
    TransactionPartnerChat,
    TransactionPartnerFragment,
    TransactionPartnerOther,
    TransactionPartnerTelegramAds,
    TransactionPartnerTelegramApi,
    TransactionPartnerUser,
)

from . import _version, constants, error, helpers, request, warnings
from ._birthdate import Birthdate
from ._bot import Bot
from ._botcommand import BotCommand
from ._botcommandscope import (
    BotCommandScope,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeChatAdministrators,
    BotCommandScopeChatMember,
    BotCommandScopeDefault,
)
from ._botdescription import BotDescription, BotShortDescription
from ._botname import BotName
from ._business import (
    BusinessBotRights,
    BusinessConnection,
    BusinessIntro,
    BusinessLocation,
    BusinessMessagesDeleted,
    BusinessOpeningHours,
    BusinessOpeningHoursInterval,
)
from ._callbackquery import CallbackQuery
from ._chat import Chat
from ._chatadministratorrights import ChatAdministratorRights
from ._chatbackground import (
    BackgroundFill,
    BackgroundFillFreeformGradient,
    BackgroundFillGradient,
    BackgroundFillSolid,
    BackgroundType,
    BackgroundTypeChatTheme,
    BackgroundTypeFill,
    BackgroundTypePattern,
    BackgroundTypeWallpaper,
    ChatBackground,
)
from ._chatboost import (
    ChatBoost,
    ChatBoostAdded,
    ChatBoostRemoved,
    ChatBoostSource,
    ChatBoostSourceGiftCode,
    ChatBoostSourceGiveaway,
    ChatBoostSourcePremium,
    ChatBoostUpdated,
    UserChatBoosts,
)
from ._chatfullinfo import ChatFullInfo
from ._chatinvitelink import ChatInviteLink
from ._chatjoinrequest import ChatJoinRequest
from ._chatlocation import ChatLocation
from ._chatmember import (
    ChatMember,
    ChatMemberAdministrator,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
)
from ._chatmemberupdated import ChatMemberUpdated
from ._chatpermissions import ChatPermissions
from ._checklists import Checklist, ChecklistTask, ChecklistTasksAdded, ChecklistTasksDone
from ._choseninlineresult import ChosenInlineResult
from ._copytextbutton import CopyTextButton
from ._dice import Dice
from ._directmessagepricechanged import DirectMessagePriceChanged
from ._directmessagestopic import DirectMessagesTopic
from ._files._inputstorycontent import (
    InputStoryContent,
    InputStoryContentPhoto,
    InputStoryContentVideo,
)
from ._files.animation import Animation
from ._files.audio import Audio
from ._files.chatphoto import ChatPhoto
from ._files.contact import Contact
from ._files.document import Document
from ._files.file import File
from ._files.inputfile import InputFile
from ._files.inputmedia import (
    InputMedia,
    InputMediaAnimation,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputPaidMedia,
    InputPaidMediaPhoto,
    InputPaidMediaVideo,
)
from ._files.inputprofilephoto import (
    InputProfilePhoto,
    InputProfilePhotoAnimated,
    InputProfilePhotoStatic,
)
from ._files.inputsticker import InputSticker
from ._files.location import Location
from ._files.photosize import PhotoSize
from ._files.sticker import MaskPosition, Sticker, StickerSet
from ._files.venue import Venue
from ._files.video import Video
from ._files.videonote import VideoNote
from ._files.voice import Voice
from ._forcereply import ForceReply
from ._forumtopic import (
    ForumTopic,
    ForumTopicClosed,
    ForumTopicCreated,
    ForumTopicEdited,
    ForumTopicReopened,
    GeneralForumTopicHidden,
    GeneralForumTopicUnhidden,
)
from ._games.callbackgame import CallbackGame
from ._games.game import Game
from ._games.gamehighscore import GameHighScore
from ._gifts import AcceptedGiftTypes, Gift, GiftBackground, GiftInfo, Gifts
from ._giveaway import Giveaway, GiveawayCompleted, GiveawayCreated, GiveawayWinners
from ._inline.inlinekeyboardbutton import InlineKeyboardButton
from ._inline.inlinekeyboardmarkup import InlineKeyboardMarkup
from ._inline.inlinequery import InlineQuery
from ._inline.inlinequeryresult import InlineQueryResult
from ._inline.inlinequeryresultarticle import InlineQueryResultArticle
from ._inline.inlinequeryresultaudio import InlineQueryResultAudio
from ._inline.inlinequeryresultcachedaudio import InlineQueryResultCachedAudio
from ._inline.inlinequeryresultcacheddocument import InlineQueryResultCachedDocument
from ._inline.inlinequeryresultcachedgif import InlineQueryResultCachedGif
from ._inline.inlinequeryresultcachedmpeg4gif import InlineQueryResultCachedMpeg4Gif
from ._inline.inlinequeryresultcachedphoto import InlineQueryResultCachedPhoto
from ._inline.inlinequeryresultcachedsticker import InlineQueryResultCachedSticker
from ._inline.inlinequeryresultcachedvideo import InlineQueryResultCachedVideo
from ._inline.inlinequeryresultcachedvoice import InlineQueryResultCachedVoice
from ._inline.inlinequeryresultcontact import InlineQueryResultContact
from ._inline.inlinequeryresultdocument import InlineQueryResultDocument
from ._inline.inlinequeryresultgame import InlineQueryResultGame
from ._inline.inlinequeryresultgif import InlineQueryResultGif
from ._inline.inlinequeryresultlocation import InlineQueryResultLocation
from ._inline.inlinequeryresultmpeg4gif import InlineQueryResultMpeg4Gif
from ._inline.inlinequeryresultphoto import InlineQueryResultPhoto
from ._inline.inlinequeryresultsbutton import InlineQueryResultsButton
from ._inline.inlinequeryresultvenue import InlineQueryResultVenue
from ._inline.inlinequeryresultvideo import InlineQueryResultVideo
from ._inline.inlinequeryresultvoice import InlineQueryResultVoice
from ._inline.inputcontactmessagecontent import InputContactMessageContent
from ._inline.inputinvoicemessagecontent import InputInvoiceMessageContent
from ._inline.inputlocationmessagecontent import InputLocationMessageContent
from ._inline.inputmessagecontent import InputMessageContent
from ._inline.inputtextmessagecontent import InputTextMessageContent
from ._inline.inputvenuemessagecontent import InputVenueMessageContent
from ._inline.preparedinlinemessage import PreparedInlineMessage
from ._keyboardbutton import KeyboardButton
from ._keyboardbuttonpolltype import KeyboardButtonPollType
from ._keyboardbuttonrequest import KeyboardButtonRequestChat, KeyboardButtonRequestUsers
from ._linkpreviewoptions import LinkPreviewOptions
from ._loginurl import LoginUrl
from ._menubutton import MenuButton, MenuButtonCommands, MenuButtonDefault, MenuButtonWebApp
from ._message import InaccessibleMessage, MaybeInaccessibleMessage, Message
from ._messageautodeletetimerchanged import MessageAutoDeleteTimerChanged
from ._messageentity import MessageEntity
from ._messageid import MessageId
from ._messageorigin import (
    MessageOrigin,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)
from ._messagereactionupdated import MessageReactionCountUpdated, MessageReactionUpdated
from ._ownedgift import OwnedGift, OwnedGiftRegular, OwnedGifts, OwnedGiftUnique
from ._paidmedia import (
    PaidMedia,
    PaidMediaInfo,
    PaidMediaPhoto,
    PaidMediaPreview,
    PaidMediaPurchased,
    PaidMediaVideo,
)
from ._paidmessagepricechanged import PaidMessagePriceChanged
from ._passport.credentials import (
    Credentials,
    DataCredentials,
    EncryptedCredentials,
    FileCredentials,
    SecureData,
    SecureValue,
)
from ._passport.data import IdDocumentData, PersonalDetails, ResidentialAddress
from ._passport.encryptedpassportelement import EncryptedPassportElement
from ._passport.passportdata import PassportData
from ._passport.passportelementerrors import (
    PassportElementError,
    PassportElementErrorDataField,
    PassportElementErrorFile,
    PassportElementErrorFiles,
    PassportElementErrorFrontSide,
    PassportElementErrorReverseSide,
    PassportElementErrorSelfie,
    PassportElementErrorTranslationFile,
    PassportElementErrorTranslationFiles,
    PassportElementErrorUnspecified,
)
from ._passport.passportfile import PassportFile
from ._payment.invoice import Invoice
from ._payment.labeledprice import LabeledPrice
from ._payment.orderinfo import OrderInfo
from ._payment.precheckoutquery import PreCheckoutQuery
from ._payment.refundedpayment import RefundedPayment
from ._payment.shippingaddress import ShippingAddress
from ._payment.shippingoption import ShippingOption
from ._payment.shippingquery import ShippingQuery
from ._payment.stars.affiliateinfo import AffiliateInfo
from ._payment.stars.revenuewithdrawalstate import (
    RevenueWithdrawalState,
    RevenueWithdrawalStateFailed,
    RevenueWithdrawalStatePending,
    RevenueWithdrawalStateSucceeded,
)
from ._payment.successfulpayment import SuccessfulPayment
from ._poll import InputPollOption, Poll, PollAnswer, PollOption
from ._proximityalerttriggered import ProximityAlertTriggered
from ._reaction import (
    ReactionCount,
    ReactionType,
    ReactionTypeCustomEmoji,
    ReactionTypeEmoji,
    ReactionTypePaid,
)
from ._reply import ExternalReplyInfo, ReplyParameters, TextQuote
from ._replykeyboardmarkup import ReplyKeyboardMarkup
from ._replykeyboardremove import ReplyKeyboardRemove
from ._sentwebappmessage import SentWebAppMessage
from ._shared import ChatShared, SharedUser, UsersShared
from ._story import Story
from ._storyarea import (
    LocationAddress,
    StoryArea,
    StoryAreaPosition,
    StoryAreaType,
    StoryAreaTypeLink,
    StoryAreaTypeLocation,
    StoryAreaTypeSuggestedReaction,
    StoryAreaTypeUniqueGift,
    StoryAreaTypeWeather,
)
from ._suggestedpost import (
    SuggestedPostApprovalFailed,
    SuggestedPostApproved,
    SuggestedPostDeclined,
    SuggestedPostInfo,
    SuggestedPostPaid,
    SuggestedPostParameters,
    SuggestedPostPrice,
    SuggestedPostRefunded,
)
from ._switchinlinequerychosenchat import SwitchInlineQueryChosenChat
from ._telegramobject import TelegramObject
from ._uniquegift import (
    UniqueGift,
    UniqueGiftBackdrop,
    UniqueGiftBackdropColors,
    UniqueGiftColors,
    UniqueGiftInfo,
    UniqueGiftModel,
    UniqueGiftSymbol,
)
from ._update import Update
from ._user import User
from ._userprofilephotos import UserProfilePhotos
from ._userrating import UserRating
from ._videochat import (
    VideoChatEnded,
    VideoChatParticipantsInvited,
    VideoChatScheduled,
    VideoChatStarted,
)
from ._webappdata import WebAppData
from ._webappinfo import WebAppInfo
from ._webhookinfo import WebhookInfo
from ._writeaccessallowed import WriteAccessAllowed

#: :obj:`str`: The version of the `python-telegram-bot` library as string.
#: To get detailed information about the version number, please use :data:`__version_info__`
#: instead.
__version__: str = _version.__version__
#:  :class:`typing.NamedTuple`: A tuple containing the five components of the version number:
#:  `major`, `minor`, `micro`, `releaselevel`, and `serial`.
#:  All values except `releaselevel` are integers.
#:  The release level is ``'alpha'``, ``'beta'``, ``'candidate'``, or ``'final'``.
#:  The components can also be accessed by name, so ``__version_info__[0]`` is equivalent to
#:  ``__version_info__.major`` and so on.
#:
#:  .. versionadded:: 20.0
__version_info__: _version.Version = _version.__version_info__
#: :obj:`str`: Shortcut for :const:`telegram.constants.BOT_API_VERSION`.
#:
#: .. versionchanged:: 20.0
#:    This constant was previously named ``bot_api_version``.
__bot_api_version__: str = constants.BOT_API_VERSION
#: :class:`typing.NamedTuple`: Shortcut for :const:`telegram.constants.BOT_API_VERSION_INFO`.
#:
#: .. versionadded:: 20.0
__bot_api_version_info__: constants._BotAPIVersion = constants.BOT_API_VERSION_INFO
