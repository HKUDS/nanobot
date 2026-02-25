import json
from typing import Dict, Any, List, Optional

from slack_sdk.scim.v1.group import Group
from slack_sdk.scim.v1.internal_utils import _to_snake_cased
from slack_sdk.scim.v1.user import User


class Errors:
    code: int
    description: str

    def __init__(self, code: int, description: str) -> None:
        self.code = code
        self.description = description

    def to_dict(self) -> dict:
        return {"code": self.code, "description": self.description}


class SCIMResponse:
    url: str
    status_code: int
    headers: Dict[str, Any]
    raw_body: Optional[str]
    body: Optional[Dict[str, Any]]
    snake_cased_body: Optional[Dict[str, Any]]

    errors: Optional[Errors]

    @property
    def snake_cased_body(self) -> Optional[Dict[str, Any]]:
        if self._snake_cased_body is None:
            self._snake_cased_body = _to_snake_cased(self.body)
        return self._snake_cased_body

    @property
    def errors(self) -> Optional[Errors]:
        errors = self.snake_cased_body.get("errors")
        if errors is None:
            return None
        return Errors(**errors)

    def __init__(
        self,
        *,
        url: str,
        status_code: int,
        raw_body: Optional[str],
        headers: dict,
    ):
        self.url = url
        self.status_code = status_code
        self.headers = headers
        self.raw_body = raw_body
        self.body = json.loads(raw_body) if raw_body is not None and raw_body.startswith("{") else None
        self._snake_cased_body = None  # build this when it's accessed for the first time

    def __repr__(self):
        dict_value = {}
        for key, value in vars(self).items():
            dict_value[key] = value.to_dict() if hasattr(value, "to_dict") else value

        if dict_value:
            return f"<slack_sdk.scim.v1.{self.__class__.__name__}: {dict_value}>"
        else:
            return self.__str__()


# ---------------------------------
# Users
# ---------------------------------


class SearchUsersResponse(SCIMResponse):
    users: List[User]

    @property
    def users(self) -> List[User]:
        return [User(**r) for r in self.snake_cased_body.get("resources")]

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class ReadUserResponse(SCIMResponse):
    user: User

    @property
    def user(self) -> User:
        return User(**self.snake_cased_body)

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class UserCreateResponse(SCIMResponse):
    user: User

    @property
    def user(self) -> User:
        return User(**self.snake_cased_body)

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class UserPatchResponse(SCIMResponse):
    user: User

    @property
    def user(self) -> User:
        return User(**self.snake_cased_body)

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class UserUpdateResponse(SCIMResponse):
    user: User

    @property
    def user(self) -> User:
        return User(**self.snake_cased_body)

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class UserDeleteResponse(SCIMResponse):
    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


# ---------------------------------
# Groups
# ---------------------------------


class SearchGroupsResponse(SCIMResponse):
    groups: List[Group]

    @property
    def groups(self) -> List[Group]:
        return [Group(**r) for r in self.snake_cased_body.get("resources")]

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class ReadGroupResponse(SCIMResponse):
    group: Group

    @property
    def group(self) -> Group:
        return Group(**self.snake_cased_body)

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class GroupCreateResponse(SCIMResponse):
    group: Group

    @property
    def group(self) -> Group:
        return Group(**self.snake_cased_body)

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class GroupPatchResponse(SCIMResponse):
    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class GroupUpdateResponse(SCIMResponse):
    group: Group

    @property
    def group(self) -> Group:
        return Group(**self.snake_cased_body)

    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None


class GroupDeleteResponse(SCIMResponse):
    def __init__(self, underlying: SCIMResponse):
        self.underlying = underlying
        self.url = underlying.url
        self.status_code = underlying.status_code
        self.headers = underlying.headers
        self.raw_body = underlying.raw_body
        self.body = underlying.body
        self._snake_cased_body = None
