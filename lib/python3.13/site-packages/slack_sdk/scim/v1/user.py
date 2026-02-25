from typing import Optional, Any, List, Dict, Union

from .default_arg import DefaultArg, NotGiven
from .internal_utils import _to_dict_without_not_given, _is_iterable
from .types import TypeAndValue


class UserAddress:
    country: Union[Optional[str], DefaultArg]
    locality: Union[Optional[str], DefaultArg]
    postal_code: Union[Optional[str], DefaultArg]
    primary: Union[Optional[bool], DefaultArg]
    region: Union[Optional[str], DefaultArg]
    street_address: Union[Optional[str], DefaultArg]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        country: Union[Optional[str], DefaultArg] = NotGiven,
        locality: Union[Optional[str], DefaultArg] = NotGiven,
        postal_code: Union[Optional[str], DefaultArg] = NotGiven,
        primary: Union[Optional[bool], DefaultArg] = NotGiven,
        region: Union[Optional[str], DefaultArg] = NotGiven,
        street_address: Union[Optional[str], DefaultArg] = NotGiven,
        **kwargs,
    ) -> None:
        self.country = country
        self.locality = locality
        self.postal_code = postal_code
        self.primary = primary
        self.region = region
        self.street_address = street_address
        self.unknown_fields = kwargs

    def to_dict(self) -> dict:
        return _to_dict_without_not_given(self)


class UserEmail(TypeAndValue):
    pass


class UserPhoneNumber(TypeAndValue):
    pass


class UserRole(TypeAndValue):
    pass


class UserGroup:
    display: Union[Optional[str], DefaultArg]
    value: Union[Optional[str], DefaultArg]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        display: Union[Optional[str], DefaultArg] = NotGiven,
        value: Union[Optional[str], DefaultArg] = NotGiven,
        **kwargs,
    ) -> None:
        self.display = display
        self.value = value
        self.unknown_fields = kwargs

    def to_dict(self) -> dict:
        return _to_dict_without_not_given(self)


class UserMeta:
    created: Union[Optional[str], DefaultArg]
    location: Union[Optional[str], DefaultArg]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        created: Union[Optional[str], DefaultArg] = NotGiven,
        location: Union[Optional[str], DefaultArg] = NotGiven,
        **kwargs,
    ) -> None:
        self.created = created
        self.location = location
        self.unknown_fields = kwargs

    def to_dict(self) -> dict:
        return _to_dict_without_not_given(self)


class UserName:
    family_name: Union[Optional[str], DefaultArg]
    given_name: Union[Optional[str], DefaultArg]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        family_name: Union[Optional[str], DefaultArg] = NotGiven,
        given_name: Union[Optional[str], DefaultArg] = NotGiven,
        **kwargs,
    ) -> None:
        self.family_name = family_name
        self.given_name = given_name
        self.unknown_fields = kwargs

    def to_dict(self) -> dict:
        return _to_dict_without_not_given(self)


class UserPhoto:
    type: Union[Optional[str], DefaultArg]
    value: Union[Optional[str], DefaultArg]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        type: Union[Optional[str], DefaultArg] = NotGiven,
        value: Union[Optional[str], DefaultArg] = NotGiven,
        **kwargs,
    ) -> None:
        self.type = type
        self.value = value
        self.unknown_fields = kwargs

    def to_dict(self) -> dict:
        return _to_dict_without_not_given(self)


class User:
    active: Union[Optional[bool], DefaultArg]
    addresses: Union[Optional[List[UserAddress]], DefaultArg]
    display_name: Union[Optional[str], DefaultArg]
    emails: Union[Optional[List[TypeAndValue]], DefaultArg]
    external_id: Union[Optional[str], DefaultArg]
    groups: Union[Optional[List[UserGroup]], DefaultArg]
    id: Union[Optional[str], DefaultArg]
    meta: Union[Optional[UserMeta], DefaultArg]
    name: Union[Optional[UserName], DefaultArg]
    nick_name: Union[Optional[str], DefaultArg]
    phone_numbers: Union[Optional[List[TypeAndValue]], DefaultArg]
    photos: Union[Optional[List[UserPhoto]], DefaultArg]
    profile_url: Union[Optional[str], DefaultArg]
    roles: Union[Optional[List[TypeAndValue]], DefaultArg]
    schemas: Union[Optional[List[str]], DefaultArg]
    timezone: Union[Optional[str], DefaultArg]
    title: Union[Optional[str], DefaultArg]
    user_name: Union[Optional[str], DefaultArg]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        active: Union[Optional[bool], DefaultArg] = NotGiven,
        addresses: Union[Optional[List[Union[UserAddress, Dict[str, Any]]]], DefaultArg] = NotGiven,
        display_name: Union[Optional[str], DefaultArg] = NotGiven,
        emails: Union[Optional[List[Union[TypeAndValue, Dict[str, Any]]]], DefaultArg] = NotGiven,
        external_id: Union[Optional[str], DefaultArg] = NotGiven,
        groups: Union[Optional[List[Union[UserGroup, Dict[str, Any]]]], DefaultArg] = NotGiven,
        id: Union[Optional[str], DefaultArg] = NotGiven,
        meta: Union[Optional[Union[UserMeta, Dict[str, Any]]], DefaultArg] = NotGiven,
        name: Union[Optional[Union[UserName, Dict[str, Any]]], DefaultArg] = NotGiven,
        nick_name: Union[Optional[str], DefaultArg] = NotGiven,
        phone_numbers: Union[Optional[List[Union[TypeAndValue, Dict[str, Any]]]], DefaultArg] = NotGiven,
        photos: Union[Optional[List[Union[UserPhoto, Dict[str, Any]]]], DefaultArg] = NotGiven,
        profile_url: Union[Optional[str], DefaultArg] = NotGiven,
        roles: Union[Optional[List[Union[TypeAndValue, Dict[str, Any]]]], DefaultArg] = NotGiven,
        schemas: Union[Optional[List[str]], DefaultArg] = NotGiven,
        timezone: Union[Optional[str], DefaultArg] = NotGiven,
        title: Union[Optional[str], DefaultArg] = NotGiven,
        user_name: Union[Optional[str], DefaultArg] = NotGiven,
        **kwargs,
    ) -> None:
        self.active = active
        self.addresses = (
            [a if isinstance(a, UserAddress) else UserAddress(**a) for a in addresses]  # type: ignore
            if _is_iterable(addresses)
            else addresses
        )
        self.display_name = display_name
        self.emails = (
            [a if isinstance(a, TypeAndValue) else TypeAndValue(**a) for a in emails]  # type: ignore
            if _is_iterable(emails)
            else emails
        )
        self.external_id = external_id
        self.groups = (
            [a if isinstance(a, UserGroup) else UserGroup(**a) for a in groups]  # type: ignore
            if _is_iterable(groups)
            else groups
        )
        self.id = id
        self.meta = UserMeta(**meta) if meta is not None and isinstance(meta, dict) else meta
        self.name = UserName(**name) if name is not None and isinstance(name, dict) else name
        self.nick_name = nick_name
        self.phone_numbers = (
            [a if isinstance(a, TypeAndValue) else TypeAndValue(**a) for a in phone_numbers]  # type: ignore
            if _is_iterable(phone_numbers)
            else phone_numbers
        )
        self.photos = (
            [a if isinstance(a, UserPhoto) else UserPhoto(**a) for a in photos]  # type: ignore
            if _is_iterable(photos)
            else photos
        )
        self.profile_url = profile_url
        self.roles = (
            [a if isinstance(a, TypeAndValue) else TypeAndValue(**a) for a in roles]  # type: ignore
            if _is_iterable(roles)
            else roles
        )
        self.schemas = schemas
        self.timezone = timezone
        self.title = title
        self.user_name = user_name

        self.unknown_fields = kwargs

    def to_dict(self):
        return _to_dict_without_not_given(self)

    def __repr__(self):
        return f"<slack_sdk.scim.{self.__class__.__name__}: {self.to_dict()}>"
