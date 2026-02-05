"""Memory consolidator for managing memory updates with Mem0-style operations."""

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ValidationError

from nanobot.agent.memory.store import VectorMemoryStore, MemoryItem
from nanobot.agent.memory.extractor import ExtractedFact


class Operation(Enum):
    """Memory operation types following Mem0 pattern."""
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    NOOP = "noop"


@dataclass
class ConsolidationResult:
    """Result of a consolidation operation."""
    operation: Operation
    memory_id: str | None = None
    old_content: str | None = None
    new_content: str | None = None
    similarity: float = 0.0
    reason: str = ""


class ConsolidationDecision(BaseModel):
    """Validated LLM decision schema."""
    operation: Literal["ADD", "UPDATE", "DELETE", "NOOP"]
    memory_id: str | None = None
    content: str | None = None
    reason: str = ""


class MemoryConsolidator:
    """Consolidates memories using LLM-driven decision making."""

    def __init__(
        self,
        store: VectorMemoryStore,
        model: str = "gpt-4o-mini",
        candidate_threshold: float = 0.5,
        provider: Any = None,
    ):
        self.store = store
        self.model = model
        self.candidate_threshold = candidate_threshold

    def _sanitize_content(self, text: str) -> str:
        """Sanitize content before embedding in prompts."""
        if not text:
            return ""
        text = text.replace('"', '\\"').replace('\n', ' ')
        return text[:500] if len(text) > 500 else text

    def _sanitize_storage_content(self, text: str) -> str:
        """Sanitize content before storing."""
        if not text:
            return text
        return text.replace("<", "&lt;").replace(">", "&gt;")

    def consolidate(self, facts: list[ExtractedFact], namespace: str = "default") -> list[ConsolidationResult]:
        """Consolidate extracted facts into the memory store."""
        results = []
        for fact in facts:
            if not fact.content or len(fact.content.strip()) < 5:
                continue
            result, valid_ids = self._consolidate_single(fact.content.strip(), namespace)
            results.append(result)

            # Validate and normalize importance
            if isinstance(fact.importance, (int, float)):
                imp = float(fact.importance)
                importance = max(0.0, min(1.0, imp)) if not (math.isnan(imp) or math.isinf(imp)) else 0.5
            else:
                importance = 0.5

            self._execute_operation(result, namespace, importance, valid_ids)
        return results

    def _consolidate_single(self, fact: str, namespace: str = "default") -> tuple[ConsolidationResult, set[str]]:
        """Determine the appropriate operation for a single fact using LLM."""
        similar = self.store.search(fact, top_k=3, threshold=self.candidate_threshold, namespace=namespace)
        valid_ids = {item.id for item, _ in similar}

        if not similar:
            return ConsolidationResult(
                operation=Operation.ADD,
                new_content=fact,
                reason="No similar memories found"
            ), valid_ids

        try:
            result = self._llm_decide_operation(fact, similar)
            return result, valid_ids
        except Exception as e:
            logger.warning(f"LLM decision failed: {e}")
            return ConsolidationResult(
                operation=Operation.ADD,
                new_content=fact,
                reason=f"LLM failed: {e}"
            ), valid_ids

    def _llm_decide_operation(
        self,
        fact: str,
        candidates: list[tuple[MemoryItem, float]]
    ) -> ConsolidationResult:
        """Use LLM to decide the operation and potentially merge content."""
        import litellm

        candidates_text = "\n".join([
            f"{i}. [id: {item.id}] \"{self._sanitize_content(item.content)}\" (similarity: {score:.2f})"
            for i, (item, score) in enumerate(candidates, 1)
        ])

        prompt = f"""Memory management decision.

Existing memories:
{candidates_text}

New fact: "{self._sanitize_content(fact)}"

Operations:
- ADD: Completely new information
- UPDATE <id>: Update/replace existing (provide merged content)
- DELETE <id>: Contradicts existing (provide new content)
- NOOP: Already captured

JSON format: {{"operation": "UPDATE", "memory_id": "abc123", "content": "merged", "reason": "..."}}
For ADD/NOOP, omit memory_id. For UPDATE, MUST provide merged content.

Response:"""

        response = litellm.completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=500,
        )

        try:
            decision = ConsolidationDecision(**json.loads(response.choices[0].message.content.strip()))
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Invalid LLM decision: {e}")
            return ConsolidationResult(operation=Operation.ADD, new_content=fact, reason=f"Invalid response: {e}")

        operation = Operation[decision.operation.upper()] if decision.operation.upper() in Operation.__members__ else Operation.ADD
        memory_id = decision.memory_id
        content = decision.content if decision.content else fact
        reason = decision.reason or "LLM decision"

        # Validate UPDATE/DELETE operations
        if operation in (Operation.UPDATE, Operation.DELETE):
            if not memory_id:
                logger.warning(f"{operation} without memory_id, defaulting to ADD")
                return ConsolidationResult(operation=Operation.ADD, new_content=fact, reason="Missing memory_id")

            matching = [item for item, _ in candidates if item.id == memory_id]
            if not matching:
                logger.warning(f"Invalid memory_id {memory_id}, defaulting to ADD")
                return ConsolidationResult(operation=Operation.ADD, new_content=fact, reason="Invalid memory_id")

            old_content = matching[0].content
            similarity = next(score for item, score in candidates if item.id == memory_id)
            return ConsolidationResult(
                operation=operation,
                memory_id=memory_id,
                old_content=old_content,
                new_content=content,
                similarity=similarity,
                reason=reason
            )

        return ConsolidationResult(
            operation=operation,
            new_content=content,
            similarity=candidates[0][1] if candidates else 0.0,
            reason=reason
        )

    def _execute_operation(self, result: ConsolidationResult, namespace: str = "default", importance: float = 0.5, valid_ids: set[str] | None = None) -> None:
        """Execute a consolidation operation with ID validation."""
        if valid_ids is None:
            valid_ids = set()

        try:
            # Validate memory_id for UPDATE/DELETE
            if result.operation in (Operation.UPDATE, Operation.DELETE):
                if result.memory_id and result.memory_id not in valid_ids:
                    logger.warning(f"Invalid memory_id {result.memory_id}, falling back to ADD")
                    result.operation = Operation.ADD
                    result.memory_id = None

            if result.operation == Operation.ADD:
                content = self._sanitize_storage_content(result.new_content) if result.new_content else ""
                item = self.store.add(content, metadata={"importance": importance}, namespace=namespace)
                result.memory_id = item.id
                logger.debug(f"Added: {content[:50]}...")

            elif result.operation == Operation.UPDATE:
                if not result.memory_id:
                    logger.error("Cannot UPDATE without memory_id")
                    return

                content = self._sanitize_storage_content(result.new_content) if result.new_content else ""
                updated = self.store.update(result.memory_id, content, namespace=namespace)
                if not updated:
                    logger.info(f"Memory {result.memory_id} not found, creating new memory instead")
                    item = self.store.add(content, metadata={"importance": importance}, namespace=namespace)
                    result.memory_id = item.id
                else:
                    logger.debug(f"Updated {result.memory_id}: {content[:50]}...")

            elif result.operation == Operation.DELETE:
                if not result.memory_id:
                    logger.error("Cannot DELETE without memory_id")
                    return

                deleted = self.store.delete(result.memory_id, namespace=namespace)
                if not deleted:
                    logger.warning(f"Memory {result.memory_id} not found for DELETE")
                else:
                    logger.debug(f"Deleted {result.memory_id}")

                # Add replacement if different
                if result.new_content and result.new_content != result.old_content:
                    content = self._sanitize_storage_content(result.new_content)
                    self.store.add(content, metadata={"importance": importance}, namespace=namespace)
                    logger.debug(f"Added replacement: {content[:50]}...")

            elif result.operation == Operation.NOOP:
                logger.debug(f"Skipped duplicate: {result.new_content[:50] if result.new_content else 'N/A'}...")

        except Exception as e:
            logger.error(f"Failed to execute {result.operation}: {e}")
