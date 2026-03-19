"""Tests for the guard PII detector."""

import pytest

from nanobot.guard.detector import PIIEntity, RuleDetector, SecurityLevel


class TestRuleDetector:
    def setup_method(self):
        self.detector = RuleDetector()

    # ── S3 patterns ──────────────────────────────────────────────────────────

    def test_api_key_sk_prefix(self):
        entities = self.detector.detect("My key is sk-abcdefghijklmnopqrstuvwxyz123456")
        assert any(e.entity_type == "api_key" and e.level == SecurityLevel.S3 for e in entities)

    def test_api_key_akia_prefix(self):
        entities = self.detector.detect("AWS key: AKIAIOSFODNN7EXAMPLE")
        assert any(e.entity_type == "api_key" and e.level == SecurityLevel.S3 for e in entities)

    def test_pem_cert(self):
        entities = self.detector.detect("-----BEGIN RSA PRIVATE KEY-----")
        assert any(e.entity_type == "pem_cert" and e.level == SecurityLevel.S3 for e in entities)

    def test_cn_id_card(self):
        entities = self.detector.detect("身份证: 110101199003077890")
        assert any(e.entity_type == "cn_id_card" and e.level == SecurityLevel.S3 for e in entities)

    def test_credit_card(self):
        entities = self.detector.detect("Card: 4111 1111 1111 1111")
        assert any(e.entity_type == "credit_card" and e.level == SecurityLevel.S3 for e in entities)

    # ── S2 patterns ──────────────────────────────────────────────────────────

    def test_cn_phone(self):
        entities = self.detector.detect("手机号: 13812345678")
        assert any(e.entity_type == "cn_phone" and e.level == SecurityLevel.S2 for e in entities)

    def test_email(self):
        entities = self.detector.detect("Contact: user@example.com")
        assert any(e.entity_type == "email" and e.level == SecurityLevel.S2 for e in entities)

    def test_ip_address(self):
        entities = self.detector.detect("Server at 192.168.1.100")
        assert any(e.entity_type == "ip_address" and e.level == SecurityLevel.S2 for e in entities)

    # ── max_level ─────────────────────────────────────────────────────────────

    def test_max_level_empty(self):
        assert self.detector.max_level([]) == SecurityLevel.S1

    def test_max_level_s2(self):
        entities = self.detector.detect("email: foo@bar.com")
        assert self.detector.max_level(entities) == SecurityLevel.S2

    def test_max_level_s3_wins_over_s2(self):
        entities = self.detector.detect("email: foo@bar.com, key: sk-abcdefghijklmnopqrstuvwxyz")
        assert self.detector.max_level(entities) == SecurityLevel.S3

    # ── clean text ───────────────────────────────────────────────────────────

    def test_no_entities_in_clean_text(self):
        entities = self.detector.detect("Hello, what is the weather today?")
        assert entities == []

    # ── custom rules ─────────────────────────────────────────────────────────

    def test_extra_rule_s3(self):
        detector = RuleDetector(extra_rules=[{"pattern": r"SECRET-\w+", "level": "S3", "type": "secret"}])
        entities = detector.detect("token: SECRET-abc123")
        assert any(e.entity_type == "secret" and e.level == SecurityLevel.S3 for e in entities)
