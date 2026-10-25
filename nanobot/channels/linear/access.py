"""Installation-scoped member choices, with non-destructive legacy approval fallback."""

from nanobot.channels.linear.config import LinearConfig
from nanobot.channels.linear.state import LinearStateStore
from nanobot.pairing.store import is_approved


def member_allowed(
    config: LinearConfig, state: LinearStateStore, organization_id: str, user_id: str,
) -> bool:
    installation = state.installation(organization_id)
    if installation is None or installation.oauth_client_id != config.client_id:
        return False
    choice = state.member_access(config.client_id, organization_id, user_id)
    if choice is not None:
        return choice
    return (
        "*" in config.allow_from
        or user_id in config.allow_from
        or is_approved("linear", user_id)
    )
