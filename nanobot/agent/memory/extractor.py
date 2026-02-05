"""Memory extractor for automatically extracting facts from conversations."""

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, ValidationError


EXTRACTION_PROMPT = """Analyze the conversation and extract key facts.

<conversation>
{conversation}
</conversation>

Extract:
- Personal info (name, job, location, preferences)
- Decisions, requirements, relationships
- Technical preferences (tools, languages)

Rules:
- Facts only, no opinions or temporary context
- Self-contained statements
- Skip greetings and small talk

Return JSON array: [{{"fact": "...", "importance": "high|medium|low"}}]
Example: [{{"fact": "User's name is John", "importance": "high"}}]

Facts:"""


TRIVIAL_PATTERNS = [
    r'^(ok|okay|yes|no|thanks|sure|got it|cool|nice|great|hmm|ah|oh|lol|yep|yeah)[\.\!\?]?\s*$',
    r'^[\s\W]*$',
]


@dataclass
class ExtractedFact:
    """A fact extracted from conversation with metadata."""
    content: str
    importance: float  # 0.0 to 1.0
    source: str  # "llm" or "heuristic"


class ExtractedFactSchema(BaseModel):
    """Pydantic schema for validating LLM-extracted facts."""
    fact: str = Field(..., min_length=1, max_length=500)
    importance: Literal["high", "medium", "low"] = "medium"


class MemoryExtractor:
    """Extracts memorable facts from conversations."""

    def __init__(self, model: str = "gpt-4o-mini", max_facts: int = 5):
        self.model = model
        self.max_facts = max_facts
        self._trivial_patterns = [re.compile(p, re.IGNORECASE) for p in TRIVIAL_PATTERNS]

    def extract(self, messages: list[dict[str, Any]], max_facts: int = 5) -> list[ExtractedFact]:
        """Extract facts from a conversation."""
        if not messages:
            return []

        user_messages = [m for m in messages if m.get("role") == "user"]
        if len(user_messages) < 3:
            return []

        # Skip trivial last messages
        if user_messages:
            last_msg = user_messages[-1].get("content", "").strip()
            if not last_msg or any(p.match(last_msg) for p in self._trivial_patterns):
                logger.debug(f"Skipping trivial message: {last_msg[:50]}")
                return []

        conversation = self._format_conversation(messages)
        if len(conversation) < 50:
            return []

        try:
            facts = self._llm_extract(conversation)
            return facts[:max_facts]
        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}")
            return self._heuristic_extract(messages)[:max_facts]

    def _sanitize_for_prompt(self, text: str) -> str:
        """Sanitize user content before embedding in prompts."""
        text = text.replace("```", "'''").replace("<", "&lt;").replace(">", "&gt;")
        return text[:2000] + "..." if len(text) > 2000 else text

    def _format_conversation(self, messages: list[dict[str, Any]]) -> str:
        """Format messages for the extraction prompt with sanitization."""
        parts = []
        for msg in messages[-20:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content and role in ("user", "assistant"):
                content = self._sanitize_for_prompt(content)[:500]
                parts.append(f"{role.upper()}: {content}")
        return "\n".join(parts)

    def _llm_extract(self, conversation: str) -> list[ExtractedFact]:
        """Extract facts using LLM with Pydantic validation."""
        import litellm

        response = litellm.completion(
            model=self.model,
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(conversation=conversation)}],
            max_tokens=300,
            temperature=0.1,
        )

        content = response.choices[0].message.content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        try:
            raw_data = json.loads(content)
            if not isinstance(raw_data, list):
                raise ValueError("Expected JSON array")

            extracted = []
            importance_map = {"high": 0.9, "medium": 0.7, "low": 0.3}

            for item in raw_data[:self.max_facts]:
                try:
                    validated = ExtractedFactSchema(**item) if isinstance(item, dict) else ExtractedFactSchema(fact=str(item))
                    extracted.append(ExtractedFact(
                        content=validated.fact,
                        importance=importance_map.get(validated.importance, 0.5),
                        source="llm"
                    ))
                except ValidationError:
                    continue
            return extracted
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Invalid LLM response: {e}")
            return []

    def _heuristic_extract(self, messages: list[dict[str, Any]]) -> list[ExtractedFact]:
        """Extract facts using simple heuristics (fallback)."""
        facts = []
        seen = set()

        patterns = [
            ("my name is", 0.9), ("i am a", 0.7), ("i work", 0.8),
            ("i live", 0.8), ("i prefer", 0.7), ("i like", 0.6),
            ("i use", 0.6), ("call me", 0.8),
        ]

        for msg in messages:
            if msg.get("role") != "user":
                continue

            content = msg.get("content", "").lower()

            for indicator, importance in patterns:
                if indicator in content:
                    start = content.find(indicator)
                    end = next((content.find(sep, start) for sep in [".", "!", "?", "\n"] if content.find(sep, start) != -1), len(content))

                    fact_text = content[start:end].strip()
                    if fact_text and len(fact_text) > 5:
                        fact = self._to_third_person(fact_text)
                        fact = fact[0].upper() + fact[1:] if fact else fact

                        if fact not in seen:
                            facts.append(ExtractedFact(content=fact, importance=importance, source="heuristic"))
                            seen.add(fact)

        return facts

    def _to_third_person(self, text: str) -> str:
        """Convert first-person text to third-person."""
        replacements = [
            (r'\bmy\b', "User's"), (r'\bi am\b', "User is"), (r"\bi'm\b", "User is"),
            (r'\bi have\b', "User has"), (r"\bi've\b", "User has"),
            (r'\bi will\b', "User will"), (r"\bi'll\b", "User will"),
            (r'\bi\b', "User"),
        ]
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return re.sub(r'\bUser User\b', "User", text)
