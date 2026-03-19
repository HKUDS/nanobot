"""Tests for SecurityRouter and CostRouter."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.guard.detector import SecurityLevel
from nanobot.guard.router import Complexity, SecurityRouter, _mask_text


def _make_guard_config(
    enabled=True,
    extra_rules=None,
    local_model="",
    local_detector_model="",
    cost_aware=False,
    simple_model="",
    medium_model="",
):
    from nanobot.config.schema import GuardConfig
    return GuardConfig(
        enabled=enabled,
        extra_rules=extra_rules or [],
        local_model=local_model,
        local_detector_model=local_detector_model,
        cost_aware=cost_aware,
        simple_model=simple_model,
        medium_model=medium_model,
    )


class TestMaskText:
    def test_single_entity(self):
        from nanobot.guard.detector import PIIEntity
        text = "Call 13812345678 now"
        entities = [PIIEntity(text="13812345678", entity_type="cn_phone", level=SecurityLevel.S2, start=5, end=16)]
        assert _mask_text(text, entities) == "Call [CN_PHONE] now"

    def test_multiple_entities_no_overlap(self):
        from nanobot.guard.detector import PIIEntity
        text = "foo@bar.com and 192.168.0.1"
        entities = [
            PIIEntity(text="foo@bar.com", entity_type="email", level=SecurityLevel.S2, start=0, end=11),
            PIIEntity(text="192.168.0.1", entity_type="ip_address", level=SecurityLevel.S2, start=16, end=27),
        ]
        result = _mask_text(text, entities)
        assert "[EMAIL]" in result
        assert "[IP_ADDRESS]" in result

    def test_no_entities(self):
        assert _mask_text("hello world", []) == "hello world"


class TestSecurityRouter:
    def setup_method(self):
        self.config = _make_guard_config()
        self.router = SecurityRouter(self.config)

    def _user_msg(self, content):
        return [{"role": "user", "content": content}]

    def test_s1_clean_message(self):
        level, entities = self.router.classify_messages(self._user_msg("What is the weather?"))
        assert level == SecurityLevel.S1
        assert entities == []

    def test_s2_email(self):
        level, entities = self.router.classify_messages(self._user_msg("My email is user@example.com"))
        assert level == SecurityLevel.S2

    def test_s3_api_key(self):
        level, entities = self.router.classify_messages(
            self._user_msg("Here is my key: sk-abcdefghijklmnopqrstuvwxyz123456")
        )
        assert level == SecurityLevel.S3

    def test_s3_wins_over_s2(self):
        msg = "email foo@bar.com, key sk-abcdefghijklmnopqrstuvwxyz"
        level, _ = self.router.classify_messages(self._user_msg(msg))
        assert level == SecurityLevel.S3

    def test_system_messages_ignored(self):
        messages = [
            {"role": "system", "content": "sk-abcdefghijklmnopqrstuvwxyz"},
            {"role": "user", "content": "Hi there"},
        ]
        level, _ = self.router.classify_messages(messages)
        assert level == SecurityLevel.S1

    def test_apply_mask_s2(self):
        messages = [{"role": "user", "content": "Call 13812345678"}]
        from nanobot.guard.detector import PIIEntity
        entities = [PIIEntity("13812345678", "cn_phone", SecurityLevel.S2, 5, 16)]
        masked = self.router.apply_mask(messages, entities)
        assert "[CN_PHONE]" in masked[0]["content"]
        assert "13812345678" not in masked[0]["content"]

    def test_apply_mask_skips_non_user(self):
        messages = [{"role": "assistant", "content": "Hello 13812345678"}]
        from nanobot.guard.detector import PIIEntity
        entities = [PIIEntity("13812345678", "cn_phone", SecurityLevel.S2, 6, 17)]
        masked = self.router.apply_mask(messages, entities)
        # assistant messages are not masked
        assert masked[0]["content"] == "Hello 13812345678"

    def test_multimodal_message(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "key: sk-abcdefghijklmnopqrstuvwxyz"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ]
        level, _ = self.router.classify_messages(messages)
        assert level == SecurityLevel.S3


@pytest.mark.asyncio
class TestCostRouter:
    async def test_classify_simple(self):
        from nanobot.guard.router import CostRouter
        config = _make_guard_config(cost_aware=True, simple_model="gpt-4o-mini")
        router = CostRouter(config)

        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "SIMPLE"
        mock_provider.chat_with_retry = AsyncMock(return_value=mock_response)

        messages = [{"role": "user", "content": "Hi"}]
        result = await router.classify(messages, mock_provider)
        assert result == Complexity.SIMPLE

    async def test_classify_fallback_on_error(self):
        from nanobot.guard.router import CostRouter
        config = _make_guard_config(cost_aware=True)
        router = CostRouter(config)

        mock_provider = MagicMock()
        mock_provider.chat_with_retry = AsyncMock(side_effect=RuntimeError("fail"))

        messages = [{"role": "user", "content": "complex task"}]
        result = await router.classify(messages, mock_provider)
        assert result == Complexity.MEDIUM  # safe default

    async def test_classify_invalid_response(self):
        from nanobot.guard.router import CostRouter
        config = _make_guard_config(cost_aware=True)
        router = CostRouter(config)

        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "UNKNOWN_WORD"
        mock_provider.chat_with_retry = AsyncMock(return_value=mock_response)

        messages = [{"role": "user", "content": "task"}]
        result = await router.classify(messages, mock_provider)
        assert result == Complexity.MEDIUM
