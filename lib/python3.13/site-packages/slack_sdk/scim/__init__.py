"""SCIM API is a set of APIs for provisioning and managing user accounts and groups.
SCIM is used by Single Sign-On (SSO) services and identity providers to manage people across a variety of tools,
including Slack.

Refer to https://docs.slack.dev/tools/python-slack-sdk/scim for details.
"""

from .v1.client import SCIMClient
from .v1.response import SCIMResponse
from .v1.response import SearchUsersResponse, ReadUserResponse
from .v1.response import SearchGroupsResponse, ReadGroupResponse
from .v1.user import User
from .v1.group import Group

__all__ = [
    "SCIMClient",
    "SCIMResponse",
    "SearchUsersResponse",
    "ReadUserResponse",
    "SearchGroupsResponse",
    "ReadGroupResponse",
    "User",
    "Group",
]
