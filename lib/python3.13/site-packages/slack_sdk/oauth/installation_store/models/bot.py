from datetime import datetime, timezone
from time import time
from typing import Optional, Union, Dict, Any, Sequence

from slack_sdk.oauth.installation_store.internals import _timestamp_to_type


class Bot:
    app_id: Optional[str]
    enterprise_id: Optional[str]
    enterprise_name: Optional[str]
    team_id: Optional[str]
    team_name: Optional[str]
    bot_token: str
    bot_id: str
    bot_user_id: str
    bot_scopes: Sequence[str]
    # only when token rotation is enabled
    bot_refresh_token: Optional[str]
    # only when token rotation is enabled
    bot_token_expires_at: Optional[int]
    is_enterprise_install: bool
    installed_at: float

    custom_values: Dict[str, Any]

    def __init__(
        self,
        *,
        app_id: Optional[str] = None,
        # org / workspace
        enterprise_id: Optional[str] = None,
        enterprise_name: Optional[str] = None,
        team_id: Optional[str] = None,
        team_name: Optional[str] = None,
        # bot
        bot_token: str,
        bot_id: str,
        bot_user_id: str,
        bot_scopes: Union[str, Sequence[str]] = "",
        # only when token rotation is enabled
        bot_refresh_token: Optional[str] = None,
        # only when token rotation is enabled
        bot_token_expires_in: Optional[int] = None,
        # only for duplicating this object
        # only when token rotation is enabled
        bot_token_expires_at: Optional[Union[int, datetime, str]] = None,
        is_enterprise_install: Optional[bool] = False,
        # timestamps
        # The expected value type is float but the internals handle other types too
        # for str values, we support only ISO datetime format.
        installed_at: Union[float, datetime, str],
        # custom values
        custom_values: Optional[Dict[str, Any]] = None,
    ):
        self.app_id = app_id
        self.enterprise_id = enterprise_id
        self.enterprise_name = enterprise_name
        self.team_id = team_id
        self.team_name = team_name

        self.bot_token = bot_token
        self.bot_id = bot_id
        self.bot_user_id = bot_user_id
        if isinstance(bot_scopes, str):
            self.bot_scopes = bot_scopes.split(",") if len(bot_scopes) > 0 else []
        else:
            self.bot_scopes = bot_scopes
        self.bot_refresh_token = bot_refresh_token

        if bot_token_expires_at is not None:
            self.bot_token_expires_at = _timestamp_to_type(bot_token_expires_at, int)
        elif bot_token_expires_in is not None:
            self.bot_token_expires_at = int(time()) + bot_token_expires_in
        else:
            self.bot_token_expires_at = None

        self.is_enterprise_install = is_enterprise_install or False

        self.installed_at = _timestamp_to_type(installed_at, float)

        self.custom_values = custom_values if custom_values is not None else {}

    def set_custom_value(self, name: str, value: Any):
        self.custom_values[name] = value

    def get_custom_value(self, name: str) -> Optional[Any]:
        return self.custom_values.get(name)

    def _to_standard_value_dict(self) -> Dict[str, Any]:
        return {
            "app_id": self.app_id,
            "enterprise_id": self.enterprise_id,
            "enterprise_name": self.enterprise_name,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "bot_token": self.bot_token,
            "bot_id": self.bot_id,
            "bot_user_id": self.bot_user_id,
            "bot_scopes": ",".join(self.bot_scopes) if self.bot_scopes else None,
            "bot_refresh_token": self.bot_refresh_token,
            "bot_token_expires_at": (
                datetime.fromtimestamp(self.bot_token_expires_at, tz=timezone.utc)
                if self.bot_token_expires_at is not None
                else None
            ),
            "is_enterprise_install": self.is_enterprise_install,
            "installed_at": datetime.fromtimestamp(self.installed_at, tz=timezone.utc),
        }

    def to_dict_for_copying(self) -> Dict[str, Any]:
        return {"custom_values": self.custom_values, **self._to_standard_value_dict()}

    def to_dict(self) -> Dict[str, Any]:
        # prioritize standard_values over custom_values
        # when the same keys exist in both
        return {**self.custom_values, **self._to_standard_value_dict()}
