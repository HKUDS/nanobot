from unittest.mock import AsyncMock, MagicMock, patch
from nanobot.channels.feishu import FeishuChannel, _should_use_card


def make_channel():
    from nanobot.config.schema import FeishuConfig
    from nanobot.bus.queue import MessageBus
    cfg = FeishuConfig(enabled=True, app_id="aid", app_secret="asec")
    bus = MagicMock(spec=MessageBus)
    return FeishuChannel(cfg, bus)


def _make_mock_client(app_id="aid", app_secret="asec"):
    mock_client = MagicMock()
    mock_client.config.app_id = app_id
    mock_client.config.app_secret = app_secret
    return mock_client


def test_fetch_bot_open_id_returns_open_id():
    ch = make_channel()
    mock_client = _make_mock_client()

    with patch("nanobot.channels.feishu._requests") as mock_requests:
        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"tenant_access_token": "tok123"}
        mock_bot_resp = MagicMock()
        mock_bot_resp.json.return_value = {"code": 0, "bot": {"open_id": "ou_botid123"}}
        mock_requests.post.return_value = mock_token_resp
        mock_requests.get.return_value = mock_bot_resp

        result = ch._fetch_bot_open_id_sync(mock_client)
    assert result == "ou_botid123"


def test_fetch_bot_open_id_returns_none_on_failure():
    ch = make_channel()
    mock_client = _make_mock_client()

    with patch("nanobot.channels.feishu._requests") as mock_requests:
        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"tenant_access_token": "tok123"}
        mock_bot_resp = MagicMock()
        mock_bot_resp.json.return_value = {"code": 99, "msg": "error"}
        mock_requests.post.return_value = mock_token_resp
        mock_requests.get.return_value = mock_bot_resp

        result = ch._fetch_bot_open_id_sync(mock_client)
    assert result is None


# Task 3 tests
from nanobot.channels.feishu import _check_bot_mentioned, _strip_bot_mention


def test_check_bot_mentioned_finds_bot_in_mentions():
    mentions = [{"key": "@_user_1", "id": {"open_id": "ou_bot123"}, "name": "MyBot"}]
    assert _check_bot_mentioned(mentions, "ou_bot123") is True


def test_check_bot_mentioned_returns_false_when_not_mentioned():
    mentions = [{"key": "@_user_1", "id": {"open_id": "ou_other"}, "name": "Other"}]
    assert _check_bot_mentioned(mentions, "ou_bot123") is False


def test_check_bot_mentioned_returns_false_with_no_bot_id():
    assert _check_bot_mentioned([], None) is False


def test_strip_bot_mention_removes_at_name():
    result = _strip_bot_mention("@MyBot hello world", [{"name": "MyBot", "key": "@_user_1"}])
    assert "MyBot" not in result
    assert "hello world" in result


def test_group_allow_from_blocks_unlisted_group():
    import asyncio
    from nanobot.config.schema import FeishuConfig
    from nanobot.bus.queue import MessageBus

    cfg = FeishuConfig(
        enabled=True, app_id="aid", app_secret="asec",
        group_allow_from=["oc_allowed"],
    )
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    ch = FeishuChannel(cfg, bus)

    async def run():
        await ch._handle_group_message(
            sender_id="ou_user1",
            chat_id="oc_blocked",
            content="hello",
            message_id="msg1",
            mentions=[],
            account_id="default",
        )
    asyncio.run(run())
    bus.publish_inbound.assert_not_called()


# Task 4 tests
def test_should_use_card_detects_code_block():
    assert _should_use_card("```python\nprint('hi')\n```") is True


def test_should_use_card_detects_table():
    assert _should_use_card("| a | b |\n|---|---|\n| 1 | 2 |") is True


def test_should_use_card_plain_text():
    assert _should_use_card("just plain text") is False
