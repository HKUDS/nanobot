"""Feishu lark-oapi client factory."""
from typing import Any

from nanobot.config.schema import FeishuConfig

try:
    import lark_oapi as lark
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False
    lark = None


def get_feishu_client(cfg: FeishuConfig, account_id: str | None = None) -> Any:
    """
    Create a lark_oapi Client from FeishuConfig.

    Uses named account if account_id provided, otherwise falls back to
    top-level app_id/app_secret. Raises ValueError if no credentials found.
    """
    if not LARK_AVAILABLE:
        raise ImportError("lark-oapi not installed. Run: pip install lark-oapi")

    app_id, app_secret = None, None

    if account_id and cfg.accounts:
        account = cfg.accounts.get(account_id)
        if account:
            app_id = account.app_id
            app_secret = account.app_secret

    if not app_id:
        app_id = cfg.app_id
        app_secret = cfg.app_secret

    if not app_id or not app_secret:
        raise ValueError("No Feishu credentials found in config")

    return (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )
