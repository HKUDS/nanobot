from unittest.mock import MagicMock
from nanobot.config.schema import FeishuConfig, FeishuAccountConfig


def test_get_feishu_client_uses_default_credentials():
    from nanobot.agent.tools.feishu.client import get_feishu_client
    cfg = FeishuConfig(enabled=True, app_id="aid", app_secret="asec")
    client = get_feishu_client(cfg)
    assert client is not None


def test_get_feishu_client_uses_named_account():
    from nanobot.agent.tools.feishu.client import get_feishu_client
    cfg = FeishuConfig(
        enabled=True,
        accounts={"main": FeishuAccountConfig(name="main", app_id="aid2", app_secret="asec2")},
    )
    client = get_feishu_client(cfg, account_id="main")
    assert client is not None


def test_get_feishu_client_raises_when_no_credentials():
    from nanobot.agent.tools.feishu.client import get_feishu_client
    cfg = FeishuConfig(enabled=True)
    import pytest
    with pytest.raises(ValueError, match="No Feishu credentials"):
        get_feishu_client(cfg)
