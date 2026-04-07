"""Tests for FeishuChannel._resolve_mentions."""

from types import SimpleNamespace

from nanobot.channels.feishu import FeishuChannel


def _mention(key: str, name: str, open_id: str = "", user_id: str = ""):
    """Build a mock MentionEvent-like object."""
    id_obj = SimpleNamespace(open_id=open_id, user_id=user_id) if (open_id or user_id) else None
    return SimpleNamespace(key=key, name=name, id=id_obj)


class TestResolveMentions:
    def test_single_mention_replaced(self):
        text = "hello @_user_1 how are you"
        mentions = [_mention("@_user_1", "Alice", open_id="ou_abc123")]
        result = FeishuChannel._resolve_mentions(text, mentions)
        assert "@Alice (ou_abc123)" in result
        assert "@_user_1" not in result

    def test_mention_with_both_ids(self):
        text = "@_user_1 said hi"
        mentions = [_mention("@_user_1", "Bob", open_id="ou_abc", user_id="uid_456")]
        result = FeishuChannel._resolve_mentions(text, mentions)
        assert "@Bob (ou_abc, user id: uid_456)" in result

    def test_mention_no_id_skipped(self):
        """When mention has no id object, the placeholder is left unchanged."""
        text = "@_user_1 said hi"
        mentions = [SimpleNamespace(key="@_user_1", name="Charlie", id=None)]
        result = FeishuChannel._resolve_mentions(text, mentions)
        assert result == "@_user_1 said hi"

    def test_multiple_mentions(self):
        text = "@_user_1 and @_user_2 are here"
        mentions = [
            _mention("@_user_1", "Alice", open_id="ou_a"),
            _mention("@_user_2", "Bob", open_id="ou_b"),
        ]
        result = FeishuChannel._resolve_mentions(text, mentions)
        assert "@Alice (ou_a)" in result
        assert "@Bob (ou_b)" in result
        assert "@_user_1" not in result
        assert "@_user_2" not in result

    def test_no_mentions_returns_text(self):
        assert FeishuChannel._resolve_mentions("hello world", None) == "hello world"
        assert FeishuChannel._resolve_mentions("hello world", []) == "hello world"

    def test_empty_text_returns_empty(self):
        mentions = [_mention("@_user_1", "Alice", open_id="ou_a")]
        assert FeishuChannel._resolve_mentions("", mentions) == ""

    def test_mention_key_not_in_text_skipped(self):
        text = "hello world"
        mentions = [_mention("@_user_99", "Ghost", open_id="ou_ghost")]
        result = FeishuChannel._resolve_mentions(text, mentions)
        assert result == "hello world"
