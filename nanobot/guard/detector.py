"""PII and sensitivity detection for the guard router."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SecurityLevel(str, Enum):
    S1 = "S1"  # Safe — send to cloud directly
    S2 = "S2"  # Sensitive — desensitize before cloud
    S3 = "S3"  # Private — local model only


@dataclass
class PIIEntity:
    text: str
    entity_type: str
    level: SecurityLevel
    start: int
    end: int


# (regex_pattern, entity_type, level)
_BUILTIN_RULES: list[tuple[str, str, SecurityLevel]] = [
    # S3 — must NOT reach the cloud
    (r"(sk-|AKIA|sk-ant-)[A-Za-z0-9/_\-]{16,}", "api_key", SecurityLevel.S3),
    (r"-----BEGIN [A-Z ]+-----", "pem_cert", SecurityLevel.S3),
    (r"\b\d{17}[\dXx]\b", "cn_id_card", SecurityLevel.S3),
    (r"\b(?:\d{4}[- ]?){3}\d{4}\b", "credit_card", SecurityLevel.S3),
    # S2 — desensitize before cloud
    (r"\b1[3-9]\d{9}\b", "cn_phone", SecurityLevel.S2),
    (r"[\w.+\-]+@[\w\-]+\.[\w.]+", "email", SecurityLevel.S2),
    (r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "ip_address", SecurityLevel.S2),
]

_LEVEL_RANK: dict[SecurityLevel, int] = {
    SecurityLevel.S1: 0,
    SecurityLevel.S2: 1,
    SecurityLevel.S3: 2,
}


class RuleDetector:
    """Regex/keyword-based PII detector (~0 ms latency)."""

    def __init__(self, extra_rules: list[dict] | None = None) -> None:
        self._rules: list[tuple[re.Pattern[str], str, SecurityLevel]] = []
        for pattern, entity_type, level in _BUILTIN_RULES:
            self._rules.append((re.compile(pattern), entity_type, level))
        for rule in extra_rules or []:
            level = SecurityLevel(rule.get("level", "S2"))
            self._rules.append(
                (re.compile(rule["pattern"]), rule.get("type", "custom"), level)
            )

    def detect(self, text: str) -> list[PIIEntity]:
        entities: list[PIIEntity] = []
        for pattern, entity_type, level in self._rules:
            for m in pattern.finditer(text):
                entities.append(
                    PIIEntity(
                        text=m.group(),
                        entity_type=entity_type,
                        level=level,
                        start=m.start(),
                        end=m.end(),
                    )
                )
        entities.sort(key=lambda e: e.start)
        return entities

    def max_level(self, entities: list[PIIEntity]) -> SecurityLevel:
        if not entities:
            return SecurityLevel.S1
        return max(entities, key=lambda e: _LEVEL_RANK[e.level]).level
