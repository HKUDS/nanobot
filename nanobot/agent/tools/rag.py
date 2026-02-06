"""
RAG Tool for Nanobot.
Integrates RAG-Anything to provide knowledge base querying capabilities.
"""

import os
import sys
import logging
import inspect
from typing import Any, Optional

from nanobot.agent.tools.base import Tool

# Setup logger
logger = logging.getLogger(__name__)

# Try importing RAGAnything, might fail if not in environment
try:
    # Add workspace root to path if needed to find raganything
    # Assuming standard project structure where RAG is a sibling or installed
    # We will try dynamic import or assume it's in python path
    from raganything.sunteco.sunteco_rag_anything import CustomRAGAnything

    RAG_AVAILABLE = True
except ImportError:
    # Attempt to add relative path to sys.path for development environments
    # /home/sunteco/phuongdd/sun_ai/BOT/nanobot/nanobot/agent/tools/rag.py
    # to /home/sunteco/phuongdd/sun_ai/RAG/RAG-Anything
    try:
        current_file = os.path.abspath(__file__)
        nanobot_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        )
        workspace_root = os.path.dirname(os.path.dirname(nanobot_root))
        rag_path = os.path.join(workspace_root, "RAG", "RAG-Anything")
        if rag_path not in sys.path:
            sys.path.append(rag_path)

        from raganything.sunteco.sunteco_rag_anything import CustomRAGAnything

        RAG_AVAILABLE = True
    except ImportError as e:
        logger.warning(f"Failed to import RAGAnything: {e}")
        RAG_AVAILABLE = False
        CustomRAGAnything = None


class RagTool(Tool):
    """
    Tool for querying a proprietary knowledge base using RAG-Anything.
    Supports hybrid retrieval and multimodal analysis.
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._rag_instance = None

    @property
    def name(self) -> str:
        return "rag_query"

    @property
    def description(self) -> str:
        return (
            "Query the knowledge base using RAG (Retrieval Augmented Generation). "
            "Use this tool when you need information from indexed documents, technical manuals, "
            "or internal data. Supports standard text queries (hybrid search) and visual analysis."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question or query to search for in the knowledge base.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["hybrid", "local", "global", "naive"],
                    "description": "Retrieval mode. 'hybrid' is recommended (combines vector+graph).",
                    "default": "hybrid",
                },
                "use_vlm": {
                    "type": "boolean",
                    "description": "If true, enables VLM (Vision Language Model) to analyze images found in the retrieved context.",
                    "default": False,
                },
            },
            "required": ["query"],
        }

    async def execute(
        self, query: str, mode: str = "hybrid", use_vlm: bool = False, **kwargs
    ) -> str:
        if not RAG_AVAILABLE:
            return "Error: RAG-Anything dependencies are not installed or accessible in this environment."

        try:
            # Lazy initialization of the heavy RAG model
            if self._rag_instance is None:
                await self._initialize_rag()

            logger.info(f"Executing RAG query: '{query}' | mode={mode} | vlm={use_vlm}")

            # Execute query based on configuration
            if use_vlm:
                # Multimodal/VLM enhanced query
                result = await self._rag_instance.aquery(query, mode=mode, vlm_enhanced=True)
            else:
                # Standard query
                result = await self._rag_instance.aquery(query, mode=mode)

            return str(result)

        except Exception as e:
            logger.error(f"RAG query execution failed: {e}", exc_info=True)
            return f"Error executing RAG query: {str(e)}"

    async def _initialize_rag(self):
        """Initialize the CustomRAGAnything instance singleton."""
        logger.info("Initializing CustomRAGAnything instance...")

        # Load configuration from Nanobot config or env vars
        # We assume RAG-Anything's init_env handles most env vars,
        # but we can pass specific overrides if they exist in self._config

        working_dir = self._config.get("working_dir", "rag_storage")

        # Extract RAG-specific config from tool config if present
        rag_config = self._config.get("rag_config", {})

        self._rag_instance = CustomRAGAnything(working_dir=working_dir, **rag_config)

        logger.info("CustomRAGAnything initialized successfully.")
