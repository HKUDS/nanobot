"""Dependency-free Feishu configuration model shared by management and runtime."""

from typing import Literal

from pydantic import Field

from nanobot.config.schema import Base


class FeishuConfig(Base):
    """Feishu/Lark channel configuration using WebSocket long connection."""

    instance_id: str = "default"
    name: str = "nanobot"
    identity_key: str = ""
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    # Bot-to-bot groups: open_ids of peer bots allowed to trigger this bot (empty keeps the
    # default of dropping every bot message), plus a cap on consecutive bot-triggered turns
    # per chat. A human message resets that cap.
    allow_bot_senders: list[str] = Field(default_factory=list)
    bot_hop_limit: int = 2
    # Mention the peer bot on replies: Feishu only routes group messages that @ the target.
    reply_with_mention: bool = False
    react_emoji: str = "THUMBSUP"
    done_emoji: str | None = None
    tool_hint_prefix: str = "\U0001f527"
    group_policy: Literal["open", "mention"] = "mention"
    reply_to_message: bool = False
    streaming: bool = True
    domain: Literal["feishu", "lark"] = "feishu"
    topic_isolation: bool = True


def feishu_default_config() -> dict[str, object]:
    return FeishuConfig().model_dump(by_alias=True)


__all__ = ["FeishuConfig", "feishu_default_config"]
