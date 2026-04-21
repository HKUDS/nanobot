"""Input sanitization and prompt injection defense."""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class InjectionResult:
    """Result of injection detection."""
    is_injection: bool
    confidence: float  # 0.0 to 1.0
    detected_patterns: list[str]
    sanitized_content: str


class PromptInjectionDetector:
    """
    Regex-based prompt injection detection.
    
    Covers common patterns:
    - Direct instruction override attempts
    - Role manipulation
    - Delimiter injection
    - System prompt extraction attempts
    """
    
    # Patterns that indicate injection attempts
    PATTERNS = [
        # Direct overrides
        (r"(?i)(ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|commands?))", "override_attempt", 0.9),
        (r"(?i)(disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|commands?))", "override_attempt", 0.9),
        (r"(?i)(forget\s+(everything|all|your)\s+(instructions?|programming|training|guidelines?|rules?))", "override_attempt", 0.85),

        # Role manipulation
        (r"(?i)(you\s+are\s+(now|no\s+longer|instead\s+of|instead)\b)", "role_manipulation", 0.8),
        (r"(?i)(act\s+as\s+(if\s+)?(a\s+)?(different|new|another|admin|root|system))", "role_manipulation", 0.8),
        (r"(?i)(pretend\s+(to\s+)?(be|that\s+you\s+are)|imagine\s+(you\s+are|that))", "role_manipulation", 0.75),
        (r"(?i)(roleplay\s+as|play\s+the\s+role\s+of)", "role_manipulation", 0.7),

        # Delimiter injection
        (r"(\x00|\x1b|\x04|\x05)", "control_char", 0.6),
        (r"(\[\[|\]\]|\{\{|\}\}|<<<|>>>|---{3,})", "delimiter_injection", 0.5),

        # System prompt extraction
        (r"(?i)(show\s+(me\s+)?(your\s+)?(system\s+)?(instructions?|prompt|configuration|settings?|rules?))", "prompt_extraction", 0.85),
        (r"(?i)(what\s+(are|were)\s+(your\s+)?(system\s+)?instructions?)", "prompt_extraction", 0.8),
        (r"(?i)(repeat\s+(all\s+)?(your\s+)?(instructions?|system\s+prompt))", "prompt_extraction", 0.9),

        # Jailbreak attempts
        (r"(?i)\b(do\s+anything\s+now|developer\s+mode|bypass\s+(safety|restrictions?|filters?)|jailbreak)\b", "jailbreak", 0.95),
        (r"(?i)(new\s+instructions?|override\s+system|system\s+override)", "jailbreak", 0.9),

        # Code injection — only match at word boundaries to reduce false positives
        (r"(?i)\b(exec\s*\(|eval\s*\(|__import__|subprocess\s*\(|os\.system\s*\(|shell_exec\s*\()", "code_injection", 0.95),
        (r"(?i)^import\s+(os|sys|subprocess)\s*$", "code_injection", 0.8),

        # Prompt leaking
        (r"(?i)(tell\s+me\s+your\s+(system\s+)?prompt|reveal\s+(your\s+)?(system\s+)?instructions?)", "prompt_leaking", 0.85),
        (r"(?i)(output\s+(your\s+)?(system\s+)?(instructions?|prompt)\b)", "prompt_leaking", 0.9),
    ]
    
    # High-confidence threshold
    CONFIDENCE_THRESHOLD = 0.7
    
    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold
        self._compiled_patterns = [
            (re.compile(pattern), name, confidence)
            for pattern, name, confidence in self.PATTERNS
        ]
    
    def detect(self, content: str) -> InjectionResult:
        """
        Analyze content for prompt injection attempts.
        
        Returns InjectionResult with:
        - is_injection: bool - whether injection was detected
        - confidence: float - confidence score (0-1)
        - detected_patterns: list of detected pattern names
        - sanitized_content: content with dangerous parts removed
        """
        if not content:
            return InjectionResult(
                is_injection=False,
                confidence=0.0,
                detected_patterns=[],
                sanitized_content=content
            )
        
        detected = []
        max_confidence = 0.0
        
        for pattern, name, confidence in self._compiled_patterns:
            if pattern.search(content):
                detected.append(name)
                max_confidence = max(max_confidence, confidence)
        
        # Sanitize: remove or escape detected patterns
        sanitized = self._sanitize(content, detected)
        
        is_injection = max_confidence >= self.threshold
        
        return InjectionResult(
            is_injection=is_injection,
            confidence=max_confidence,
            detected_patterns=detected,
            sanitized_content=sanitized
        )
    
    def _sanitize(self, content: str, detected: list[str]) -> str:
        """Remove or escape detected injection patterns."""
        if not detected:
            return content
        
        sanitized = content
        
        # Remove control characters
        sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)
        
        # Escape common delimiters that might be used for injection
        sanitized = re.sub(r'\[{2,}', '[', sanitized)
        sanitized = re.sub(r'\]{2,}', ']', sanitized)
        sanitized = re.sub(r'={3,}', '==', sanitized)
        
        return sanitized.strip()


# Singleton instance
_detector: Optional[PromptInjectionDetector] = None


def get_detector() -> PromptInjectionDetector:
    """Get or create the detector singleton."""
    global _detector
    if _detector is None:
        _detector = PromptInjectionDetector()
    return _detector


def sanitize_input(content: str, log_detections: bool = True) -> tuple[str, bool]:
    """
    Sanitize user input for prompt injection.
    
    Args:
        content: Raw user input
        log_detections: Whether to log detected injections
    
    Returns:
        Tuple of (sanitized_content, was_injection_detected)
    """
    detector = get_detector()
    result = detector.detect(content)
    
    if result.is_injection and log_detections:
        import loguru
        logger = loguru.logger
        logger.warning(
            f"Prompt injection detected: {result.detected_patterns} "
            f"(confidence: {result.confidence:.2f})"
        )
    
    return result.sanitized_content, result.is_injection