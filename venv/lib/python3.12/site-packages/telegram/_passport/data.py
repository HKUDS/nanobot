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
# pylint: disable=missing-module-docstring

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class PersonalDetails(TelegramObject):
    """
    This object represents personal details.

    Args:
        first_name (:obj:`str`): First Name.
        middle_name (:obj:`str`): Optional. First Name.
        last_name (:obj:`str`): Last Name.
        birth_date (:obj:`str`): Date of birth in DD.MM.YYYY format.
        gender (:obj:`str`): Gender, male or female.
        country_code (:obj:`str`): Citizenship (ISO 3166-1 alpha-2 country code).
        residence_country_code (:obj:`str`): Country of residence (ISO 3166-1 alpha-2 country
            code).
        first_name_native (:obj:`str`): First Name in the language of the user's country of
            residence.
        middle_name_native (:obj:`str`): Optional. Middle Name in the language of the user's
            country of residence.
        last_name_native (:obj:`str`): Last Name in the language of the user's country of
            residence.

    Attributes:
        first_name (:obj:`str`): First Name.
        middle_name (:obj:`str`): Optional. First Name.
        last_name (:obj:`str`): Last Name.
        birth_date (:obj:`str`): Date of birth in DD.MM.YYYY format.
        gender (:obj:`str`): Gender, male or female.
        country_code (:obj:`str`): Citizenship (ISO 3166-1 alpha-2 country code).
        residence_country_code (:obj:`str`): Country of residence (ISO 3166-1 alpha-2 country
            code).
        first_name_native (:obj:`str`): First Name in the language of the user's country of
            residence.
        middle_name_native (:obj:`str`): Optional. Middle Name in the language of the user's
            country of residence.
        last_name_native (:obj:`str`): Last Name in the language of the user's country of
            residence.
    """

    __slots__ = (
        "birth_date",
        "country_code",
        "first_name",
        "first_name_native",
        "gender",
        "last_name",
        "last_name_native",
        "middle_name",
        "middle_name_native",
        "residence_country_code",
    )

    def __init__(
        self,
        first_name: str,
        last_name: str,
        birth_date: str,
        gender: str,
        country_code: str,
        residence_country_code: str,
        first_name_native: str | None = None,
        last_name_native: str | None = None,
        middle_name: str | None = None,
        middle_name_native: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.first_name: str = first_name
        self.last_name: str = last_name
        self.middle_name: str | None = middle_name
        self.birth_date: str = birth_date
        self.gender: str = gender
        self.country_code: str = country_code
        self.residence_country_code: str = residence_country_code
        self.first_name_native: str | None = first_name_native
        self.last_name_native: str | None = last_name_native
        self.middle_name_native: str | None = middle_name_native

        self._freeze()


class ResidentialAddress(TelegramObject):
    """
    This object represents a residential address.

    Args:
        street_line1 (:obj:`str`): First line for the address.
        street_line2 (:obj:`str`): Optional. Second line for the address.
        city (:obj:`str`): City.
        state (:obj:`str`): Optional. State.
        country_code (:obj:`str`): ISO 3166-1 alpha-2 country code.
        post_code (:obj:`str`): Address post code.

    Attributes:
        street_line1 (:obj:`str`): First line for the address.
        street_line2 (:obj:`str`): Optional. Second line for the address.
        city (:obj:`str`): City.
        state (:obj:`str`): Optional. State.
        country_code (:obj:`str`): ISO 3166-1 alpha-2 country code.
        post_code (:obj:`str`): Address post code.
    """

    __slots__ = (
        "city",
        "country_code",
        "post_code",
        "state",
        "street_line1",
        "street_line2",
    )

    def __init__(
        self,
        street_line1: str,
        street_line2: str,
        city: str,
        state: str,
        country_code: str,
        post_code: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.street_line1: str = street_line1
        self.street_line2: str = street_line2
        self.city: str = city
        self.state: str = state
        self.country_code: str = country_code
        self.post_code: str = post_code

        self._freeze()


class IdDocumentData(TelegramObject):
    """
    This object represents the data of an identity document.

    Args:
        document_no (:obj:`str`): Document number.
        expiry_date (:obj:`str`): Optional. Date of expiry, in DD.MM.YYYY format.

    Attributes:
        document_no (:obj:`str`): Document number.
        expiry_date (:obj:`str`): Optional. Date of expiry, in DD.MM.YYYY format.
    """

    __slots__ = ("document_no", "expiry_date")

    def __init__(
        self,
        document_no: str,
        expiry_date: str,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.document_no: str = document_no
        self.expiry_date: str = expiry_date

        self._freeze()
