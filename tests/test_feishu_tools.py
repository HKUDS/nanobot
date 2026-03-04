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


# Task 7: feishu_wiki tests
def test_feishu_wiki_tool_name():
    from nanobot.agent.tools.feishu.wiki import FeishuWikiTool
    tool = FeishuWikiTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    assert tool.name == "feishu_wiki"


def test_feishu_wiki_tool_has_required_params():
    from nanobot.agent.tools.feishu.wiki import FeishuWikiTool
    tool = FeishuWikiTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    props = tool.parameters["properties"]
    assert "action" in props


@pytest.mark.asyncio
async def test_feishu_wiki_list_spaces_calls_api():
    from unittest.mock import MagicMock, patch
    from nanobot.agent.tools.feishu.wiki import FeishuWikiTool

    tool = FeishuWikiTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.success.return_value = True
    mock_space = MagicMock()
    mock_space.space_id = "sp_123"
    mock_space.name = "My Space"
    mock_resp.data.items = [mock_space]
    mock_resp.data.has_more = False
    mock_client.wiki.v2.space.list.return_value = mock_resp

    with patch("nanobot.agent.tools.feishu.wiki.get_feishu_client", return_value=mock_client):
        result = await tool.execute(action="list_spaces")
    assert "sp_123" in result


# Task 8: feishu_bitable tests
def test_feishu_bitable_tool_name():
    from nanobot.agent.tools.feishu.bitable import FeishuBitableTool
    tool = FeishuBitableTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    assert tool.name == "feishu_bitable"


def test_feishu_bitable_tool_has_required_params():
    from nanobot.agent.tools.feishu.bitable import FeishuBitableTool
    tool = FeishuBitableTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    props = tool.parameters["properties"]
    assert "action" in props
    assert "app_token" in props


@pytest.mark.asyncio
async def test_feishu_bitable_list_records_calls_api():
    from unittest.mock import MagicMock, patch
    from nanobot.agent.tools.feishu.bitable import FeishuBitableTool

    tool = FeishuBitableTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.success.return_value = True
    mock_record = MagicMock()
    mock_record.record_id = "rec_abc"
    mock_record.fields = {"Name": "Alice"}
    mock_resp.data.items = [mock_record]
    mock_resp.data.has_more = False
    mock_client.bitable.v1.app_table_record.list.return_value = mock_resp

    with patch("nanobot.agent.tools.feishu.bitable.get_feishu_client", return_value=mock_client):
        result = await tool.execute(action="list_records", app_token="bascABC", table_id="tblXYZ")
    assert "rec_abc" in result


# Task 9: feishu_drive tests
def test_feishu_drive_tool_name():
    from nanobot.agent.tools.feishu.drive import FeishuDriveTool
    tool = FeishuDriveTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    assert tool.name == "feishu_drive"


def test_feishu_drive_tool_has_required_params():
    from nanobot.agent.tools.feishu.drive import FeishuDriveTool
    tool = FeishuDriveTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    props = tool.parameters["properties"]
    assert "action" in props


@pytest.mark.asyncio
async def test_feishu_drive_list_files_calls_api():
    from unittest.mock import MagicMock, patch
    from nanobot.agent.tools.feishu.drive import FeishuDriveTool

    tool = FeishuDriveTool(FeishuConfig(enabled=True, app_id="a", app_secret="b"))
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.success.return_value = True
    mock_file = MagicMock()
    mock_file.token = "fldABC"
    mock_file.name = "report.docx"
    mock_file.type = "docx"
    mock_resp.data.files = [mock_file]
    mock_resp.data.has_more = False
    mock_client.drive.v1.file.list.return_value = mock_resp

    with patch("nanobot.agent.tools.feishu.drive.get_feishu_client", return_value=mock_client):
        result = await tool.execute(action="list_files")
    assert "fldABC" in result


