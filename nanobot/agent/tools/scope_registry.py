"""Scope-to-tool mapping for dynamic tool registration based on OAuth scopes.

Maps Google and X OAuth scopes to the tool classes they enable.  The agent
loop uses these mappings to register only the tools a user actually has
permissions for, and to reconcile when scopes change at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nanobot.agent.tools.google import (
    GmailSendTool,
    GmailListTool,
    GmailGetTool,
    GmailSearchTool,
    GmailReplyTool,
    GmailTrashTool,
    GmailCreateDraftTool,
    GmailListLabelsTool,
    GoogleCalendarCreateEventTool,
    GoogleCalendarListEventsTool,
    GoogleCalendarGetEventTool,
    GoogleCalendarUpdateEventTool,
    GoogleCalendarDeleteEventTool,
    GoogleCalendarListCalendarsTool,
    GoogleDriveUploadTool,
    GoogleDriveListTool,
    GoogleDriveGetTool,
    GoogleDriveDownloadTool,
    GoogleDriveCreateFolderTool,
    GoogleDriveDeleteTool,
    GoogleDriveShareTool,
    GoogleDriveSearchTool,
    GoogleDocsCreateTool,
    GoogleDocsGetTool,
    GoogleDocsAppendTool,
    GoogleDocsInsertTool,
    GoogleSheetsCreateTool,
    GoogleSheetsGetTool,
    GoogleSheetsReadRangeTool,
    GoogleSheetsWriteRangeTool,
    GoogleSheetsAppendRowsTool,
    GoogleSheetsClearRangeTool,
    GoogleContactsListTool,
    GoogleContactsGetTool,
    GoogleContactsCreateTool,
    GoogleContactsUpdateTool,
    GoogleContactsDeleteTool,
    GoogleContactsSearchTool,
)
from nanobot.agent.tools.x import (
    XPostTweetTool,
    XDeleteTweetTool,
    XGetTweetTool,
    XSearchTweetsTool,
    XGetUserTweetsTool,
    XGetUserMentionsTool,
    XLikeTweetTool,
    XUnlikeTweetTool,
    XGetLikedTweetsTool,
    XRetweetTool,
    XUndoRetweetTool,
    XGetMeTool,
    XGetUserByIdTool,
    XGetUserByUsernameTool,
    XFollowUserTool,
    XUnfollowUserTool,
    XGetFollowersTool,
    XGetFollowingTool,
    XGetBookmarksTool,
    XBookmarkTweetTool,
    XRemoveBookmarkTool,
    XCreateListTool,
    XDeleteListTool,
    XGetListTool,
    XGetOwnedListsTool,
    XAddListMemberTool,
    XRemoveListMemberTool,
    XSendDmTool,
    XGetDmEventsTool,
    XGetDmConversationTool,
)

if TYPE_CHECKING:
    from nanobot.agent.tools.base import Tool

# Google scope suffixes → tool classes.
# Scopes arrive as full URLs (e.g. "https://www.googleapis.com/auth/gmail.modify")
# but we match on the suffix after "/auth/" for convenience.
GOOGLE_SCOPE_TOOLS: dict[str, list[type[Tool]]] = {
    "gmail.modify": [
        GmailSendTool,
        GmailReplyTool,
        GmailTrashTool,
        GmailCreateDraftTool,
    ],
    "gmail.readonly": [
        GmailListTool,
        GmailGetTool,
        GmailSearchTool,
        GmailListLabelsTool,
    ],
    "calendar": [
        GoogleCalendarCreateEventTool,
        GoogleCalendarListEventsTool,
        GoogleCalendarGetEventTool,
        GoogleCalendarUpdateEventTool,
        GoogleCalendarDeleteEventTool,
        GoogleCalendarListCalendarsTool,
    ],
    "drive": [
        GoogleDriveUploadTool,
        GoogleDriveListTool,
        GoogleDriveGetTool,
        GoogleDriveDownloadTool,
        GoogleDriveCreateFolderTool,
        GoogleDriveDeleteTool,
        GoogleDriveShareTool,
        GoogleDriveSearchTool,
    ],
    "documents": [
        GoogleDocsCreateTool,
        GoogleDocsGetTool,
        GoogleDocsAppendTool,
        GoogleDocsInsertTool,
    ],
    "spreadsheets": [
        GoogleSheetsCreateTool,
        GoogleSheetsGetTool,
        GoogleSheetsReadRangeTool,
        GoogleSheetsWriteRangeTool,
        GoogleSheetsAppendRowsTool,
        GoogleSheetsClearRangeTool,
    ],
    "contacts": [
        GoogleContactsListTool,
        GoogleContactsGetTool,
        GoogleContactsCreateTool,
        GoogleContactsUpdateTool,
        GoogleContactsDeleteTool,
        GoogleContactsSearchTool,
    ],
}

# X scopes → tool classes (scopes are bare strings like "tweet.read").
X_SCOPE_TOOLS: dict[str, list[type[Tool]]] = {
    "tweet.read": [
        XGetTweetTool,
        XSearchTweetsTool,
        XGetUserTweetsTool,
        XGetUserMentionsTool,
    ],
    "tweet.write": [
        XPostTweetTool,
        XDeleteTweetTool,
    ],
    "users.read": [
        XGetMeTool,
        XGetUserByIdTool,
        XGetUserByUsernameTool,
    ],
    "follows.read": [
        XGetFollowersTool,
        XGetFollowingTool,
    ],
    "follows.write": [
        XFollowUserTool,
        XUnfollowUserTool,
    ],
    "like.read": [
        XGetLikedTweetsTool,
    ],
    "like.write": [
        XLikeTweetTool,
        XUnlikeTweetTool,
    ],
    "bookmark.read": [
        XGetBookmarksTool,
    ],
    "bookmark.write": [
        XBookmarkTweetTool,
        XRemoveBookmarkTool,
    ],
    "list.read": [
        XGetListTool,
        XGetOwnedListsTool,
    ],
    "list.write": [
        XCreateListTool,
        XDeleteListTool,
        XAddListMemberTool,
        XRemoveListMemberTool,
    ],
    "dm.read": [
        XGetDmEventsTool,
        XGetDmConversationTool,
    ],
    "dm.write": [
        XSendDmTool,
    ],
    "retweet.write": [
        XRetweetTool,
        XUndoRetweetTool,
    ],
}


def _normalize_google_scope(scope: str) -> str:
    """Extract the suffix after '/auth/' from a full Google scope URL.

    ``"https://www.googleapis.com/auth/gmail.modify"`` → ``"gmail.modify"``
    If the scope is already a bare suffix, return it as-is.
    """
    marker = "/auth/"
    idx = scope.rfind(marker)
    if idx != -1:
        return scope[idx + len(marker):]
    return scope


def _all_scoped_tool_names() -> frozenset[str]:
    """Pre-compute the set of tool *names* that are scope-managed."""
    names: set[str] = set()
    for classes in GOOGLE_SCOPE_TOOLS.values():
        for cls in classes:
            names.add(cls().name)
    for classes in X_SCOPE_TOOLS.values():
        for cls in classes:
            names.add(cls().name)
    return frozenset(names)


ALL_SCOPED_TOOL_NAMES: frozenset[str] = _all_scoped_tool_names()


def get_tools_for_scopes(
    google_scopes: list[str] | None = None,
    x_scopes: list[str] | None = None,
) -> dict[str, type[Tool]]:
    """Return ``{tool_name: tool_class}`` for all tools enabled by *scopes*.

    Google scopes may be full URLs or bare suffixes; both are handled.
    """
    result: dict[str, type[Tool]] = {}

    for scope in google_scopes or []:
        key = _normalize_google_scope(scope)
        for cls in GOOGLE_SCOPE_TOOLS.get(key, []):
            result[cls().name] = cls

    for scope in x_scopes or []:
        for cls in X_SCOPE_TOOLS.get(scope, []):
            result[cls().name] = cls

    return result
