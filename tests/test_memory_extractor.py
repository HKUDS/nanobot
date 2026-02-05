"""Unit tests for MemoryExtractor and MemoryConsolidator."""

import json
from unittest.mock import Mock, patch

import pytest

from nanobot.agent.memory.consolidator import (
    MemoryConsolidator,
    Operation,
)
from nanobot.agent.memory.extractor import (
    ExtractedFact,
    MemoryExtractor,
    extract_facts_from_messages,
)
from nanobot.agent.memory.store import MemoryItem, VectorMemoryStore


class TestMemoryExtractor:
    """Tests for MemoryExtractor."""

    def test_extract_minimum_message_threshold(self):
        """Extract should return empty list when < 3 user messages."""
        extractor = MemoryExtractor()

        # 0 messages
        assert extractor.extract([]) == []

        # 1 user message
        messages = [{"role": "user", "content": "Hello"}]
        assert extractor.extract(messages) == []

        # 2 user messages
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"}
        ]
        assert extractor.extract(messages) == []

    def test_extract_trivial_message_filtering(self):
        """Extract should skip trivial last messages."""
        extractor = MemoryExtractor()

        trivial_messages = [
            "ok",
            "okay",
            "yes",
            "no",
            "thanks",
            "sure",
            "got it",
            "cool",
            "nice",
            "great",
            "hmm",
            "ah",
            "oh",
            "lol",
            "yep",
            "yeah",
            "okay.",
            "thanks!",
        ]

        for trivial in trivial_messages:
            messages = [
                {"role": "user", "content": "My name is John"},
                {"role": "assistant", "content": "Nice to meet you"},
                {"role": "user", "content": "I work at Google"},
                {"role": "assistant", "content": "Great company"},
                {"role": "user", "content": trivial},
            ]
            result = extractor.extract(messages)
            assert result == [], f"Should skip trivial message: {trivial}"

    def test_extract_conversation_length_threshold(self):
        """Extract should return empty for very short conversations."""
        extractor = MemoryExtractor()

        # Conversation < 50 chars total
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "OK"},
            {"role": "assistant", "content": "OK"},
        ]
        result = extractor.extract(messages)
        assert result == []

    @patch("litellm.completion")
    def test_extract_max_facts_parameter(self, mock_completion):
        """Extract should respect max_facts parameter."""
        extractor = MemoryExtractor()

        # Mock LLM to return 10 facts
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps([
            {"fact": f"Fact {i}", "importance": "medium"}
            for i in range(10)
        ])
        mock_completion.return_value = mock_response

        messages = [
            {"role": "user", "content": "My name is John and I work at Google"},
            {"role": "assistant", "content": "Nice to meet you John"},
            {"role": "user", "content": "I live in San Francisco and prefer Python"},
        ]

        # Request only 3 facts
        result = extractor.extract(messages, max_facts=3)
        assert len(result) <= 3

    def test_sanitize_for_prompt_code_blocks(self):
        """_sanitize_for_prompt should escape code blocks."""
        extractor = MemoryExtractor()

        text = "Here's code: ```python\nprint('hello')\n```"
        sanitized = extractor._sanitize_for_prompt(text)

        assert "```" not in sanitized
        assert "'''" in sanitized

    def test_sanitize_for_prompt_html_tags(self):
        """_sanitize_for_prompt should escape HTML tags."""
        extractor = MemoryExtractor()

        text = "<script>alert('xss')</script>"
        sanitized = extractor._sanitize_for_prompt(text)

        assert "<script>" not in sanitized
        assert "&lt;script&gt;" in sanitized
        assert "&lt;/script&gt;" in sanitized

    def test_sanitize_for_prompt_closing_tag_escape(self):
        """_sanitize_for_prompt should escape closing tags."""
        extractor = MemoryExtractor()

        text = "</div>"
        sanitized = extractor._sanitize_for_prompt(text)

        assert "</" not in sanitized
        assert "&lt;/" in sanitized

    def test_sanitize_for_prompt_length_truncation(self):
        """_sanitize_for_prompt should truncate long text."""
        extractor = MemoryExtractor()

        text = "a" * 3000
        sanitized = extractor._sanitize_for_prompt(text)

        assert len(sanitized) <= 2003  # 2000 + "..."
        assert sanitized.endswith("...")

    @patch("litellm.completion")
    def test_llm_extract_valid_json(self, mock_completion):
        """_llm_extract should parse valid JSON responses."""
        extractor = MemoryExtractor()

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps([
            {"fact": "User's name is John", "importance": "high"},
            {"fact": "User works at Google", "importance": "medium"},
        ])
        mock_completion.return_value = mock_response

        result = extractor._llm_extract("conversation text")

        assert len(result) == 2
        assert result[0].content == "User's name is John"
        assert result[0].importance == 0.9  # high
        assert result[0].source == "llm"
        assert result[1].content == "User works at Google"
        assert result[1].importance == 0.7  # medium

    @patch("litellm.completion")
    def test_llm_extract_markdown_code_block(self, mock_completion):
        """_llm_extract should handle markdown code blocks."""
        extractor = MemoryExtractor()

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = (
            "```json\n"
            + json.dumps([{"fact": "User's name is John", "importance": "high"}])
            + "\n```"
        )
        mock_completion.return_value = mock_response

        result = extractor._llm_extract("conversation text")

        assert len(result) == 1
        assert result[0].content == "User's name is John"

    @patch("litellm.completion")
    def test_llm_extract_pydantic_validation(self, mock_completion):
        """_llm_extract should validate with Pydantic and skip invalid items."""
        extractor = MemoryExtractor()

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps([
            {"fact": "Valid fact", "importance": "high"},
            {"fact": "", "importance": "medium"},  # Invalid: empty fact
            {"fact": "a" * 600, "importance": "low"},  # Invalid: too long
            {"fact": "Another valid fact", "importance": "low"},
        ])
        mock_completion.return_value = mock_response

        result = extractor._llm_extract("conversation text")

        # Only 2 valid facts should be extracted
        assert len(result) == 2
        assert result[0].content == "Valid fact"
        assert result[1].content == "Another valid fact"

    @patch("litellm.completion")
    def test_llm_extract_invalid_response_fallback(self, mock_completion):
        """_llm_extract should return empty list for invalid JSON."""
        extractor = MemoryExtractor()

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "This is not JSON"
        mock_completion.return_value = mock_response

        result = extractor._llm_extract("conversation text")

        assert result == []

    @patch("litellm.completion")
    def test_llm_extract_non_array_response(self, mock_completion):
        """_llm_extract should handle non-array JSON responses."""
        extractor = MemoryExtractor()

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({"fact": "Single fact"})
        mock_completion.return_value = mock_response

        result = extractor._llm_extract("conversation text")

        assert result == []

    def test_heuristic_extract_pattern_matching(self):
        """_heuristic_extract should match known patterns."""
        extractor = MemoryExtractor()

        messages = [
            {"role": "user", "content": "My name is Alice"},
            {"role": "user", "content": "I am a software engineer"},
            {"role": "user", "content": "I work at Microsoft"},
            {"role": "user", "content": "I live in Seattle"},
            {"role": "user", "content": "I prefer TypeScript"},
        ]

        result = extractor._heuristic_extract(messages)

        assert len(result) > 0
        # Check that patterns are converted to third person
        contents = [fact.content.lower() for fact in result]
        assert any("user" in c for c in contents)

    def test_heuristic_extract_third_person_conversion(self):
        """_heuristic_extract should convert to third person."""
        extractor = MemoryExtractor()

        messages = [
            {"role": "user", "content": "My name is Bob. I work at Apple."},
        ]

        result = extractor._heuristic_extract(messages)

        assert len(result) > 0
        # Should not contain first-person pronouns
        for fact in result:
            content_lower = fact.content.lower()
            assert "my name" not in content_lower or "user" in content_lower

    def test_heuristic_extract_deduplication(self):
        """_heuristic_extract should deduplicate facts."""
        extractor = MemoryExtractor()

        messages = [
            {"role": "user", "content": "My name is Charlie"},
            {"role": "user", "content": "My name is Charlie"},  # Duplicate
            {"role": "user", "content": "I work at Tesla"},
        ]

        result = extractor._heuristic_extract(messages)

        # Check no exact duplicates
        contents = [fact.content for fact in result]
        assert len(contents) == len(set(contents))

    def test_extract_facts_from_messages_keyword_matching(self):
        """extract_facts_from_messages should match FACT_KEYWORDS."""
        messages = [
            {"role": "user", "content": "My name is David"},
            {"role": "user", "content": "Remember that I prefer dark mode"},
            {"role": "user", "content": "Email: david@example.com"},
            {"role": "user", "content": "Random text without keywords"},
        ]

        result = extract_facts_from_messages(messages)

        assert len(result) >= 3
        assert any("name" in fact.lower() for fact in result)
        assert any("remember" in fact.lower() for fact in result)
        assert any("email" in fact.lower() for fact in result)

    def test_extract_facts_from_messages_max_facts_limit(self):
        """extract_facts_from_messages should respect max_facts limit."""
        messages = [
            {"role": "user", "content": f"My name is User{i}"}
            for i in range(20)
        ]

        result = extract_facts_from_messages(messages, max_facts=5)

        assert len(result) == 5

    def test_extract_facts_from_messages_ignores_system_messages(self):
        """extract_facts_from_messages should skip system messages."""
        messages = [
            {"role": "system", "content": "My name is System"},
            {"role": "user", "content": "My name is User"},
        ]

        result = extract_facts_from_messages(messages)

        assert len(result) == 1
        assert "User" in result[0]

    def test_extract_facts_from_messages_min_line_length(self):
        """extract_facts_from_messages should skip short lines."""
        messages = [
            {"role": "user", "content": "My name is Eve"},  # Long enough
            {"role": "user", "content": "I am X"},  # Too short (< 10 chars)
        ]

        result = extract_facts_from_messages(messages)

        assert len(result) == 1
        assert "Eve" in result[0]

    def test_extract_facts_from_messages_truncates_facts(self):
        """extract_facts_from_messages should truncate long facts to 200 chars."""
        long_content = "My name is " + "X" * 300
        messages = [
            {"role": "user", "content": long_content},
        ]

        result = extract_facts_from_messages(messages)

        assert len(result) == 1
        assert len(result[0]) == 200


class TestMemoryConsolidator:
    """Tests for MemoryConsolidator."""

    @pytest.fixture
    def mock_store(self):
        """Create a mock VectorMemoryStore."""
        store = Mock(spec=VectorMemoryStore)
        return store

    def test_consolidate_add_operation(self, mock_store):
        """consolidate should ADD when no similar memories exist."""
        mock_store.search.return_value = []
        mock_store.add.return_value = MemoryItem(
            id="new123",
            content="User's name is Frank",
            embedding=[0.1] * 384,
            metadata={"importance": 0.9}
        )

        consolidator = MemoryConsolidator(store=mock_store)
        facts = [ExtractedFact(content="User's name is Frank", importance=0.9, source="llm")]

        results = consolidator.consolidate(facts)

        assert len(results) == 1
        assert results[0].operation == Operation.ADD
        assert results[0].new_content == "User's name is Frank"
        assert results[0].reason == "No similar memories found"
        mock_store.add.assert_called_once()

    @patch("litellm.completion")
    def test_consolidate_update_operation(self, mock_completion, mock_store):
        """consolidate should UPDATE when LLM decides to merge."""
        # Mock existing memory
        existing = MemoryItem(
            id="mem123",
            content="User's name is Frank",
            embedding=[0.1] * 384,
            metadata={"importance": 0.8}
        )
        mock_store.search.return_value = [(existing, 0.85)]
        mock_store.update.return_value = True

        # Mock LLM decision
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({
            "operation": "UPDATE",
            "memory_id": "mem123",
            "content": "User's name is Frank Smith",
            "reason": "Adding last name"
        })
        mock_completion.return_value = mock_response

        consolidator = MemoryConsolidator(store=mock_store)
        facts = [ExtractedFact(content="User's last name is Smith", importance=0.8, source="llm")]

        results = consolidator.consolidate(facts)

        assert len(results) == 1
        assert results[0].operation == Operation.UPDATE
        assert results[0].memory_id == "mem123"
        assert results[0].new_content == "User's name is Frank Smith"
        mock_store.update.assert_called_once()

    @patch("litellm.completion")
    def test_consolidate_delete_operation(self, mock_completion, mock_store):
        """consolidate should DELETE when fact contradicts existing."""
        # Mock existing memory
        existing = MemoryItem(
            id="mem456",
            content="User works at Google",
            embedding=[0.1] * 384,
            metadata={"importance": 0.7}
        )
        mock_store.search.return_value = [(existing, 0.75)]
        mock_store.delete.return_value = True
        mock_store.add.return_value = MemoryItem(
            id="new456",
            content="User works at Microsoft",
            embedding=[0.2] * 384,
            metadata={"importance": 0.8}
        )

        # Mock LLM decision
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({
            "operation": "DELETE",
            "memory_id": "mem456",
            "content": "User works at Microsoft",
            "reason": "User changed jobs"
        })
        mock_completion.return_value = mock_response

        consolidator = MemoryConsolidator(store=mock_store)
        facts = [ExtractedFact(content="User works at Microsoft", importance=0.8, source="llm")]

        results = consolidator.consolidate(facts)

        assert len(results) == 1
        assert results[0].operation == Operation.DELETE
        assert results[0].memory_id == "mem456"
        mock_store.delete.assert_called_once()
        mock_store.add.assert_called_once()  # Replacement added

    @patch("litellm.completion")
    def test_consolidate_noop_operation(self, mock_completion, mock_store):
        """consolidate should NOOP when fact is duplicate."""
        # Mock existing memory
        existing = MemoryItem(
            id="mem789",
            content="User prefers Python",
            embedding=[0.1] * 384,
            metadata={"importance": 0.6}
        )
        mock_store.search.return_value = [(existing, 0.95)]

        # Mock LLM decision
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({
            "operation": "NOOP",
            "reason": "Already captured"
        })
        mock_completion.return_value = mock_response

        consolidator = MemoryConsolidator(store=mock_store)
        facts = [ExtractedFact(content="User prefers Python", importance=0.6, source="llm")]

        results = consolidator.consolidate(facts)

        assert len(results) == 1
        assert results[0].operation == Operation.NOOP
        mock_store.add.assert_not_called()
        mock_store.update.assert_not_called()
        mock_store.delete.assert_not_called()

    def test_sanitize_storage_content_html_escaping(self, mock_store):
        """_sanitize_storage_content should escape HTML for storage."""
        consolidator = MemoryConsolidator(store=mock_store)

        text = "<script>alert('xss')</script>"
        sanitized = consolidator._sanitize_storage_content(text)

        assert "<script>" not in sanitized
        assert "&lt;script&gt;" in sanitized
        assert "&lt;/script&gt;" in sanitized

    def test_sanitize_storage_content_empty_string(self, mock_store):
        """_sanitize_storage_content should handle empty strings."""
        consolidator = MemoryConsolidator(store=mock_store)

        assert consolidator._sanitize_storage_content("") == ""
        assert consolidator._sanitize_storage_content(None) is None

    def test_importance_validation_inf_nan(self, mock_store):
        """consolidate should handle inf/nan importance values."""
        mock_store.search.return_value = []
        mock_store.add.return_value = MemoryItem(
            id="new999",
            content="Test fact",
            embedding=[0.1] * 384,
            metadata={"importance": 0.5}
        )

        consolidator = MemoryConsolidator(store=mock_store)

        # Test with inf
        facts = [ExtractedFact(content="Test fact", importance=float('inf'), source="llm")]
        consolidator.consolidate(facts)

        # Should default to 0.5
        call_args = mock_store.add.call_args
        assert call_args[1]["metadata"]["importance"] == 0.5

        # Test with nan
        facts = [ExtractedFact(content="Test fact 2", importance=float('nan'), source="llm")]
        consolidator.consolidate(facts)

        call_args = mock_store.add.call_args
        assert call_args[1]["metadata"]["importance"] == 0.5

    def test_importance_validation_range_clamping(self, mock_store):
        """consolidate should clamp importance to [0.0, 1.0]."""
        mock_store.search.return_value = []
        mock_store.add.return_value = MemoryItem(
            id="new888",
            content="Test fact",
            embedding=[0.1] * 384,
            metadata={"importance": 1.0}
        )

        consolidator = MemoryConsolidator(store=mock_store)

        # Test value > 1.0
        facts = [ExtractedFact(content="Test fact", importance=1.5, source="llm")]
        consolidator.consolidate(facts)

        call_args = mock_store.add.call_args
        assert call_args[1]["metadata"]["importance"] == 1.0

        # Test value < 0.0
        facts = [ExtractedFact(content="Test fact 2", importance=-0.5, source="llm")]
        consolidator.consolidate(facts)

        call_args = mock_store.add.call_args
        assert call_args[1]["metadata"]["importance"] == 0.0

    @patch("litellm.completion")
    def test_error_handling_invalid_llm_response(self, mock_completion, mock_store):
        """consolidate should handle invalid LLM response format."""
        existing = MemoryItem(
            id="mem111",
            content="User likes coffee",
            embedding=[0.1] * 384,
            metadata={"importance": 0.5}
        )
        mock_store.search.return_value = [(existing, 0.6)]
        mock_store.add.return_value = MemoryItem(
            id="new111",
            content="User drinks tea",
            embedding=[0.2] * 384,
            metadata={"importance": 0.5}
        )

        # Mock invalid LLM response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "This is not JSON"
        mock_completion.return_value = mock_response

        consolidator = MemoryConsolidator(store=mock_store)
        facts = [ExtractedFact(content="User drinks tea", importance=0.5, source="llm")]

        results = consolidator.consolidate(facts)

        # Should fallback to ADD
        assert len(results) == 1
        assert results[0].operation == Operation.ADD

    @patch("litellm.completion")
    def test_error_handling_update_target_not_found(self, mock_completion, mock_store):
        """consolidate should fallback to ADD when UPDATE target not found."""
        # Mock existing memory
        existing = MemoryItem(
            id="mem222",
            content="User likes Python",
            embedding=[0.1] * 384,
            metadata={"importance": 0.6}
        )
        mock_store.search.return_value = [(existing, 0.7)]

        # Mock LLM decision with invalid memory_id
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({
            "operation": "UPDATE",
            "memory_id": "invalid_id",  # Not in search results
            "content": "Merged content",
            "reason": "Merging info"
        })
        mock_completion.return_value = mock_response
        mock_store.add.return_value = MemoryItem(
            id="new222",
            content="User also likes JavaScript",
            embedding=[0.2] * 384,
            metadata={"importance": 0.6}
        )

        consolidator = MemoryConsolidator(store=mock_store)
        facts = [ExtractedFact(content="User also likes JavaScript", importance=0.6, source="llm")]

        results = consolidator.consolidate(facts)

        # Should fallback to ADD
        assert len(results) == 1
        assert results[0].operation == Operation.ADD
        mock_store.add.assert_called_once()

    def test_consolidate_skips_empty_facts(self, mock_store):
        """consolidate should skip empty or very short facts."""
        consolidator = MemoryConsolidator(store=mock_store)

        facts = [
            ExtractedFact(content="", importance=0.5, source="llm"),
            ExtractedFact(content="   ", importance=0.5, source="llm"),
            ExtractedFact(content="OK", importance=0.5, source="llm"),  # < 5 chars
        ]

        results = consolidator.consolidate(facts)

        assert len(results) == 0
        mock_store.search.assert_not_called()

    @patch("litellm.completion")
    def test_execute_operation_update_memory_not_found(self, mock_completion, mock_store):
        """_execute_operation should create new memory if UPDATE target not found."""
        existing = MemoryItem(
            id="mem333",
            content="Old fact",
            embedding=[0.1] * 384,
            metadata={"importance": 0.5}
        )
        mock_store.search.return_value = [(existing, 0.7)]
        mock_store.update.return_value = False  # Memory not found
        mock_store.add.return_value = MemoryItem(
            id="new333",
            content="Updated fact",
            embedding=[0.2] * 384,
            metadata={"importance": 0.6}
        )

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({
            "operation": "UPDATE",
            "memory_id": "mem333",
            "content": "Updated fact",
            "reason": "Updating"
        })
        mock_completion.return_value = mock_response

        consolidator = MemoryConsolidator(store=mock_store)
        facts = [ExtractedFact(content="Updated fact", importance=0.6, source="llm")]

        consolidator.consolidate(facts)

        # Should try to update, then fallback to add
        mock_store.update.assert_called_once()
        mock_store.add.assert_called_once()

    @patch("litellm.completion")
    def test_consolidate_llm_exception_fallback(self, mock_completion, mock_store):
        """consolidate should use heuristic ADD when LLM throws exception."""
        existing = MemoryItem(
            id="mem444",
            content="Existing fact",
            embedding=[0.1] * 384,
            metadata={"importance": 0.5}
        )
        mock_store.search.return_value = [(existing, 0.6)]
        mock_store.add.return_value = MemoryItem(
            id="new444",
            content="New fact",
            embedding=[0.2] * 384,
            metadata={"importance": 0.5}
        )

        # Mock LLM to raise exception
        mock_completion.side_effect = Exception("API error")

        consolidator = MemoryConsolidator(store=mock_store)
        facts = [ExtractedFact(content="New fact", importance=0.5, source="llm")]

        results = consolidator.consolidate(facts)

        # Should fallback to ADD
        assert len(results) == 1
        assert results[0].operation == Operation.ADD
        assert "LLM failed" in results[0].reason
