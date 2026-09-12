"""Dependency-free configuration for Telegram's outbound-only operational feed."""

import re

from pydantic import ConfigDict, Field, field_validator, model_validator

from nanobot.config_base import Base


class TelegramTechnicalConfig(Base):
    """Only structured names/statuses are permitted; never raw log mirroring."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    enabled: bool = False
    profile_name: str = Field(default="Powiadomienia", min_length=1, max_length=64)
    shared_inbox: bool = False
    main_chat_id: str = ""
    chat_id: str = ""
    token: str = Field(default="", repr=False)
    include_tool_events: bool = True
    include_status_events: bool = True

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, value: str) -> str:
        # Numeric, canonical IDs make inbound isolation independent of usernames.
        if value and re.fullmatch(r"-?[1-9][0-9]{0,19}", value) is None:
            raise ValueError("technical.chatId must be a canonical numeric Telegram chat ID")
        return value

    @field_validator("main_chat_id")
    @classmethod
    def validate_main_chat_id(cls, value: str) -> str:
        if value and re.fullmatch(r"[1-9][0-9]{0,19}", value) is None:
            raise ValueError("technical.mainChatId must be a private numeric Telegram user ID")
        return value

    @model_validator(mode="after")
    def require_target(self) -> "TelegramTechnicalConfig":
        if self.shared_inbox and not self.main_chat_id:
            raise ValueError("technical.sharedInbox requires mainChatId")
        if self.enabled and not self.chat_id:
            raise ValueError("technical.chatId is required when technical notifications are enabled")
        return self

    def uses_main_bot(self, main_token: str) -> bool:
        return not self.token or self.token.split(":", 1)[0] == main_token.split(":", 1)[0]

    def validate_credentials(self, main_token: str) -> None:
        if not self.enabled:
            return
        token = self.token or main_token
        if not token.strip():
            raise ValueError("technical notifications require technical.token or Telegram token")
        if self.uses_main_bot(main_token) and not self.chat_id.startswith("-"):
            raise ValueError(
                "same-bot technical.chatId must be a dedicated group/channel (negative ID); "
                "use a separate technical.token for a technical DM"
            )
