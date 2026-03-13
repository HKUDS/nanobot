import logging
import os
from typing import Any, Optional

from nanobot.agent.tools.base import Tool
from nanobot.config.schema import ToolsConfig


# Helper to load .env for RAG variables (SEEKDB, etc.)
def _load_rag_env():
    import os
    # nanobot/nanobot/agent/tools/rag.py -> ../../../.. (root) -> sun_ai ?
    # Better to look relative to this file?
    # This file: .../BOT/nanobot/nanobot/agent/tools/rag.py
    # RAG Env: .../RAG/RAG-Anything/.env
    # Path diff: ../../../../../RAG/RAG-Anything/.env

    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up 5 levels to reach common root (sun_ai) from .../nanobot/agent/tools
    # tools -> agent -> nanobot -> nanobot -> BOT -> sun_ai
    rag_env_path = os.path.abspath(
        os.path.join(current_dir, "../../../../../RAG/RAG-Anything/.env")
    )

    if os.path.exists(rag_env_path):
        # logger.info(f"Loading RAG env from {rag_env_path}")
        with open(rag_env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    # Remove inline comments like "1024 # comment"
                    if "#" in value:
                        value = value.split("#", 1)[0]
                    value = value.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = value


# Load env vars before creating instance
_load_rag_env()

# Try importing RAGAnything, fail gracefully if not available
try:
    from raganything.sunteco.sunteco_rag_anything import CustomRAGAnything

    RAG_AVAILABLE = True
except (ImportError, TypeError, ValueError, Exception) as e:
    # Catch ALL import/init errors to prevent gateway crash
    # raganything init_env.py can raise TypeError (int(None)) or ValueError
    print(f"Error importing RAG library: {e}")
    CustomRAGAnything = None
    RAG_AVAILABLE = False


logger = logging.getLogger(__name__)


class RagTool(Tool):
    name = "rag_query"
    description = (
        "MANDATORY to use this tool for ALL queries about Sunteco services, system configurations, "
        "technical documentation, virtual machines (VM), or any specific knowledge related to Sunteco "
        "products that is not in your general training data. "
        "This tool provides up-to-date and specific information from Sunteco's internal knowledge base."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question or query to search for."},
            "mode": {
                "type": "string",
                "enum": ["naive", "local", "global", "hybrid", "mix"],
                "default": "hybrid",
                "description": "Search mode. 'hybrid' or 'mix' matches both text and vector. 'naive' is simple vector search.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, config: ToolsConfig):
        # We store the entire ToolsConfig so we can access config.rag
        self.config = config
        self._rag_instance: Optional[CustomRAGAnything] = None
        self.rag_config = config.rag  # Store rag config for easier access
        logger.info(f"RagTool initialized (enabled={self.rag_config.enabled})")

    async def execute(self, query: str, mode: str = "hybrid", **kwargs) -> str:
        """Execute the RAG query."""
        if not RAG_AVAILABLE:
            logger.error("RAG library (raganything) not installed or could not be imported.")
            return "Error: RAG library (raganything) not installed or could not be imported."

        if not self.rag_config.enabled:
            logger.warning("RAG tool is disabled in configuration.")
            return "Error: RAG tool is disabled in configuration."

        # Lazy Initialization
        if not self._rag_instance:
            logger.info(
                f"Initializing RAG instance with Dual Model config (LLM: {self.rag_config.llm_model_name} @ {self.rag_config.llm_base_url})..."
            )
            try:
                # DUAL MODEL CONFIGURATION
                # Agent uses its own config (passed elsewhere)
                # RAG uses this specific config from ToolsConfig.rag

                # Ensure working directory is absolute
                working_dir = os.path.abspath("./rag_storage")
                logger.info(f"RAG working directory: {working_dir}")
                
                self._rag_instance = CustomRAGAnything(
                    working_dir=working_dir,
                    # RAG LLM (Ministral / Bifrost) - Distinct from Agent
                    llm_binding=self.rag_config.llm_binding,
                    llm_model_name=self.rag_config.llm_model_name,
                    llm_base_url=self.rag_config.llm_base_url,
                    llm_api_key=self.rag_config.llm_api_key,
                    # Embedding settings
                    embed_binding=self.rag_config.embed_binding,
                    embed_model_name=self.rag_config.embed_model_name,
                    embed_base_url=self.rag_config.embed_endpoint,
                    embed_api_key=self.rag_config.embed_api_key,
                    embed_dimension=self.rag_config.embed_dimension,
                    # Embedding dimension (optional, usually inferred)
                    # embed_dimension=1536
                )
                logger.info("RAG instance initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize RAG: {e}")
                return f"Error initializing RAG: {e}"

        try:
            # Map 'hybrid' to 'mix' if library expects 'mix' (LightRAG conventionally uses 'mix' for hybrid)
            query_mode = "mix" if mode == "hybrid" else mode

            # Log detailed execution info
            logger.debug(f"RAG Execution - Query: '{query}' | Mode: '{query_mode}'")

            result = await self._rag_instance.aquery(query, mode=query_mode)
            result_str = str(result)

            # Log full result for debugging (as requested)
            logger.debug(f"RAG Raw Result (Length: {len(result_str)}):")
            # Log in chunks if very long, or just the whole thing if reasonable
            if len(result_str) > 2000:
                logger.debug(f"{result_str[:2000]}... [truncated]")
            else:
                logger.debug(result_str)

            if not result_str or result_str == "None":
                logger.warning(f"RAG returned empty result for query: '{query}'")

            return result_str
        except Exception as e:
            return f"Error executing RAG query: {e}"
