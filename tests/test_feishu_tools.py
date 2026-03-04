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


# Task 6: feishu_doc tests
def test_feishu_doc_tool_name():
    from nanobot.agent.tools.feishu.doc import FeishuDocTool
    tool = FeishuDocTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    assert tool.name == "feishu_doc"


def test_feishu_doc_tool_has_required_params():
    from nanobot.agent.tools.feishu.doc import FeishuDocTool
    tool = FeishuDocTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    props = tool.parameters["properties"]
    assert "action" in props
    assert "doc_id" in props


import pytest
@pytest.mark.asyncio
async def test_feishu_doc_read_calls_api():
    from unittest.mock import MagicMock, patch
    from nanobot.agent.tools.feishu.doc import FeishuDocTool

    tool = FeishuDocTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.success.return_value = True
    mock_resp.data.content = "doc content here"
    mock_client.docx.v1.document.raw_content.return_value = mock_resp

    with patch("nanobot.agent.tools.feishu.doc.get_feishu_client", return_value=mock_client):
        result = await tool.execute(action="read", doc_id="doxcnABC123")
    assert "doc content here" in result

