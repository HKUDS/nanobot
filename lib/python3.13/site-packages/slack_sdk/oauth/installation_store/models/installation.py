from datetime import datetime, timezone
from time import time
from typing import Optional, Union, Dict, Any, Sequence

from slack_sdk.oauth.installation_store.internals import _timestamp_to_type
from slack_sdk.oauth.installation_store.models.bot import Bot


class Installation:
    app_id: Optional[str]
    enterprise_id: Optional[str]
    enterprise_name: Optional[str]
    enterprise_url: Optional[str]
    team_id: Optional[str]
    team_name: Optional[str]
    bot_token: Optional[str]
    bot_id: Optional[str]
    bot_user_id: Optional[str]
    bot_scopes: Optional[Sequence[str]]
    bot_refresh_token: Optional[str]  # only when token rotation is enabled
    # only when token rotation is enabled
    # Unix time (seconds): only when token rotation is enabled
    bot_token_expires_at: Optional[int]
    user_id: str
    user_token: Optional[str]
    user_scopes: Optional[Sequence[str]]
    user_refresh_token: Optional[str]  # only when token rotation is enabled
    # Unix time (seconds): only when token rotation is enabled
    user_token_expires_at: Optional[int]
    incoming_webhook_url: Optional[str]
    incoming_webhook_channel: Optional[str]
    incoming_webhook_channel_id: Optional[str]
    incoming_webhook_configuration_url: Optional[str]
    is_enterprise_install: bool
    token_type: Optional[str]
    installed_at: float

    custom_values: Dict[str, Any]

    def __init__(
        self,
        *,
        app_id: Optional[str] = None,
        # org / workspace
        enterprise_id: Optional[str] = None,
        enterprise_name: Optional[str] = None,
        enterprise_url: Optional[str] = None,
        team_id: Optional[str] = None,
        team_name: Optional[str] = None,
        # bot
        bot_token: Optional[str] = None,
        bot_id: Optional[str] = None,
        bot_user_id: Optional[str] = None,
        bot_scopes: Union[str, Sequence[str]] = "",
        bot_refresh_token: Optional[str] = None,  # only when token rotation is enabled
        # only when token rotation is enabled
        bot_token_expires_in: Optional[int] = None,
        # only for duplicating this object
        # only when token rotation is enabled
        bot_token_expires_at: Optional[Union[int, datetime, str]] = None,
        # installer
        user_id: str,
        user_token: Optional[str] = None,
        user_scopes: Union[str, Sequence[str]] = "",
        user_refresh_token: Optional[str] = None,  # only when token rotation is enabled
        # only when token rotation is enabled
        user_token_expires_in: Optional[int] = None,
        # only for duplicating this object
        # only when token rotation is enabled
        user_token_expires_at: Optional[Union[int, datetime, str]] = None,
        # incoming webhook
        incoming_webhook_url: Optional[str] = None,
        incoming_webhook_channel: Optional[str] = None,
        incoming_webhook_channel_id: Optional[str] = None,
        incoming_webhook_configuration_url: Optional[str] = None,
        # org app
        is_enterprise_install: Optional[bool] = False,
        token_type: Optional[str] = None,
        # timestamps
        # The expected value type is float but the internals handle other types too
        # for str values, we supports only ISO datetime format.
        installed_at: Optional[Union[float, datetime, str]] = None,
        # custom values
        custom_values: Optional[Dict[str, Any]] = None,
    ):
        self.app_id = app_id
        self.enterprise_id = enterprise_id
        self.enterprise_name = enterprise_name
        self.enterprise_url = enterprise_url
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

        self.user_id = user_id
        self.user_token = user_token
        if isinstance(user_scopes, str):
            self.user_scopes = user_scopes.split(",") if len(user_scopes) > 0 else []
        else:
            self.user_scopes = user_scopes
        self.user_refresh_token = user_refresh_token

        if user_token_expires_at is not None:
            self.user_token_expires_at = _timestamp_to_type(user_token_expires_at, int)
        elif user_token_expires_in is not None:
            self.user_token_expires_at = int(time()) + user_token_expires_in
        else:
            self.user_token_expires_at = None

        self.incoming_webhook_url = incoming_webhook_url
        self.incoming_webhook_channel = incoming_webhook_channel
        self.incoming_webhook_channel_id = incoming_webhook_channel_id
        self.incoming_webhook_configuration_url = incoming_webhook_configuration_url

        self.is_enterprise_install = is_enterprise_install or False
        self.token_type = token_type

        if installed_at is None:
            self.installed_at = datetime.now().timestamp()
        else:
            self.installed_at = _timestamp_to_type(installed_at, float)

        self.custom_values = custom_values if custom_values is not None else {}

    def to_bot(self) -> Bot:
        return Bot(
            app_id=self.app_id,
            enterprise_id=self.enterprise_id,
            enterprise_name=self.enterprise_name,
            team_id=self.team_id,
            team_name=self.team_name,
            bot_token=self.bot_token,  # type: ignore[arg-type]
            bot_id=self.bot_id,  # type: ignore[arg-type]
            bot_user_id=self.bot_user_id,  # type: ignore[arg-type]
            bot_scopes=self.bot_scopes,  # type: ignore[arg-type]
            bot_refresh_token=self.bot_refresh_token,
            bot_token_expires_at=self.bot_token_expires_at,
            is_enterprise_install=self.is_enterprise_install,
            installed_at=self.installed_at,
            custom_values=self.custom_values,
        )

    def set_custom_value(self, name: str, value: Any):
        self.custom_values[name] = value

    def get_custom_value(self, name: str) -> Optional[Any]:
        return self.custom_values.get(name)

    def _to_standard_value_dict(self) -> Dict[str, Any]:
        return {
            "app_id": self.app_id,
            "enterprise_id": self.enterprise_id,
            "enterprise_name": self.enterprise_name,
            "enterprise_url": self.enterprise_url,
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
            "user_id": self.user_id,
            "user_token": self.user_token,
            "user_scopes": ",".join(self.user_scopes) if self.user_scopes else None,
            "user_refresh_token": self.user_refresh_token,
            "user_token_expires_at": (
                datetime.fromtimestamp(self.user_token_expires_at, tz=timezone.utc)
                if self.user_token_expires_at is not None
                else None
            ),
            "incoming_webhook_url": self.incoming_webhook_url,
            "incoming_webhook_channel": self.incoming_webhook_channel,
            "incoming_webhook_channel_id": self.incoming_webhook_channel_id,
            "incoming_webhook_configuration_url": self.incoming_webhook_configuration_url,
            "is_enterprise_install": self.is_enterprise_install,
            "token_type": self.token_type,
            "installed_at": datetime.fromtimestamp(self.installed_at, tz=timezone.utc),
        }

    def to_dict_for_copying(self) -> Dict[str, Any]:
        return {"custom_values": self.custom_values, **self._to_standard_value_dict()}

    def to_dict(self) -> Dict[str, Any]:
        # prioritize standard_values over custom_values
        # when the same keys exist in both
        return {**self.custom_values, **self._to_standard_value_dict()}
