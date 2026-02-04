"""Router for intelligent local/cloud model selection."""

import re
from enum import Enum
from typing import Literal

from loguru import logger

from nanobot.providers.litellm_provider import LiteLLMProvider


class RouteDecision(str, Enum):
    """Routing decision."""
    LOCAL = "local"
    CLOUD = "cloud"
    TOOLS_ONLY = "tools_only"


class RoutingMode(str, Enum):
    """Routing mode."""
    AUTO = "auto"  # Auto routing based on classification
    LOCAL_ONLY = "local"  # Force local model
    CLOUD_ONLY = "cloud"  # Force cloud model


class RouterAgent:
    """
    Router agent for intelligent local/cloud model selection.

    Uses heuristics and optional small model to classify messages and route
    to appropriate model for cost and speed optimization.
    """

    def __init__(
        self,
        local_provider: LiteLLMProvider,
        config: "RoutingConfig",
        mode: RoutingMode = RoutingMode.AUTO,
    ):
        from nanobot.config.schema import RoutingConfig

        self.local_provider = local_provider
        self.config = config
        self.mode = mode

        # Cloud keywords that indicate need for cloud model
        self.cloud_keywords = {
            "code", "explain", "analyze", "generate", "creative", "write",
            "summarize", "translate", "solve", "debug", "refactor",
            "implement", "program", "algorithm", "design", "architecture",
            "comprehensive", "detailed", "thorough", "research"
        }

        # Simple patterns for local routing
        self.local_patterns = {
            r"^what\s+(is|are|was|were)": "fact",
            r"^(who|where|when|why|how)": "question",
            r"^list\b": "listing",
            r"^tell\s+me": "simple",
            r"^give\s+me": "simple",
            r"^show\s+me": "simple",
            r"^what('?s|\s+is)": "fact",
            r"^how\s+many": "simple",
        }

        # Compile patterns
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in self.local_patterns.items()
        ]

        # Stats for optimization
        self.stats = {
            "total": 0,
            "local": 0,
            "cloud": 0,
            "local_fallback": 0
        }

    async def classify(self, message: str) -> RouteDecision:
        """
        Classify message to determine routing.

        Args:
            message: User message to classify.

        Returns:
            RouteDecision: LOCAL, CLOUD, or TOOLS_ONLY.
        """
        self.stats["total"] += 1

        # Handle forced modes
        if self.mode == RoutingMode.LOCAL_ONLY:
            logger.debug("Router: Forced local mode")
            return RouteDecision.LOCAL

        if self.mode == RoutingMode.CLOUD_ONLY:
            logger.debug("Router: Forced cloud mode")
            return RouteDecision.CLOUD

        # Check routing disabled
        if not self.config.enabled:
            return RouteDecision.CLOUD

        # Check message length heuristic
        if len(message) < 50:
            self._track_route("local")
            logger.debug(f"Router: Local (short message, len={len(message)})")
            return RouteDecision.LOCAL

        # Check for local patterns
        for pattern, reason in self.compiled_patterns:
            if pattern.match(message):
                self._track_route("local")
                logger.debug(f"Router: Local (pattern: {reason})")
                return RouteDecision.LOCAL

        # Check for cloud keywords
        message_lower = message.lower()
        cloud_hits = sum(1 for kw in self.cloud_keywords if kw in message_lower)

        if cloud_hits >= 2:
            self._track_route("cloud")
            logger.debug(f"Router: Cloud (cloud keywords: {cloud_hits})")
            return RouteDecision.CLOUD

        # Check for tools
        if self._has_tool_request(message):
            logger.debug("Router: Tools only (tool request detected)")
            return RouteDecision.TOOLS_ONLY

        # Use LLM classifier if available and long enough message
        if len(message) > 100:
            try:
                decision = await self._llm_classify(message)
                if decision:
                    self._track_route(decision)
                    return decision
            except Exception as e:
                logger.warning(f"Router: LLM classifier failed: {e}, falling back to heuristics")

        # Default to local for short messages, cloud for longer
        if len(message) < 150:
            self._track_route("local")
            logger.debug(f"Router: Local (default, len={len(message)})")
            return RouteDecision.LOCAL
        else:
            self._track_route("cloud")
            logger.debug(f"Router: Cloud (default, len={len(message)})")
            return RouteDecision.CLOUD

    async def _llm_classify(self, message: str) -> RouteDecision | None:
        """
        Use local LLM to classify the message.

        Args:
            message: User message to classify.

        Returns:
            RouteDecision if classification succeeded, None otherwise.
        """
        prompt = f"""Classify this user message as either "local" or "cloud":

Message: "{message}"

Respond with only "local" or "cloud" (lowercase, no quotes).

Local if:
- Simple facts or questions
- Short answers
- Basic explanations
- No complex reasoning needed

Cloud if:
- Code generation or explanation
- Complex analysis
- Creative writing
- Multi-step reasoning
- Long detailed responses

Classification:"""

        try:
            response = await self.local_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0
            )

            content = response.content.strip().lower()
            if content == "local":
                return RouteDecision.LOCAL
            elif content == "cloud":
                return RouteDecision.CLOUD
            else:
                logger.warning(f"Router: Unexpected LLM response: {content}")
                return None

        except Exception as e:
            logger.warning(f"Router: LLM classification failed: {e}")
            return None

    def _has_tool_request(self, message: str) -> bool:
        """
        Check if message likely requires tools.

        Args:
            message: User message to check.

        Returns:
            True if tool request detected, False otherwise.
        """
        tool_keywords = {
            "search", "fetch", "execute", "run", "calculate", "compute",
            "find", "look up", "check", "get", "list", "file", "read",
            "write", "save", "delete", "terminal", "command", "shell"
        }

        message_lower = message.lower()
        return any(kw in message_lower for kw in tool_keywords)

    def _track_route(self, route: str) -> None:
        """Track routing decision for stats."""
        if route in self.stats:
            self.stats[route] += 1

    def get_stats(self) -> dict:
        """Get routing statistics."""
        return self.stats.copy()

    def reset_stats(self) -> None:
        """Reset routing statistics."""
        self.stats = {
            "total": 0,
            "local": 0,
            "cloud": 0,
            "local_fallback": 0
        }
