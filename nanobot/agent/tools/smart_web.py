"""Smart Web Fetch: AI-powered web content extraction inspired by Claude Code."""

import json
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.web import WebFetchTool
from nanobot.providers.base import LLMProvider


class SmartWebFetchTool(Tool):
    """
    Fetch URL and extract information using AI.

    Similar to Claude Code's WebFetch, this tool:
    1. Fetches URL content and converts to markdown
    2. Uses a small, fast LLM to extract relevant information based on prompt
    3. Returns the AI-extracted information instead of raw content

    This provides more focused, relevant responses compared to raw content dumps.
    """

    name = "smart_web_fetch"
    description = (
        "Fetch a URL and extract specific information using AI. "
        "Provide a URL and a prompt describing what information you want to extract. "
        "The AI will read the page and return only the relevant information."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch"
            },
            "prompt": {
                "type": "string",
                "description": "What information to extract from the page (e.g., 'What are the latest features?', 'Summarize the main points')"
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to fetch (default 50000)",
                "minimum": 1000
            }
        },
        "required": ["url", "prompt"]
    }

    def __init__(
        self,
        llm_provider: LLMProvider,
        extraction_model: str | None = None,
        max_chars: int = 50000,
        proxy: str | None = None,
        cache_ttl: int = 900  # 15 minutes like Claude Code
    ):
        """
        Initialize SmartWebFetchTool.

        Args:
            llm_provider: LLM provider for content extraction
            extraction_model: Model to use for extraction (default: use provider's default, recommend Haiku for speed)
            max_chars: Maximum characters to fetch from URL
            proxy: Optional HTTP/SOCKS5 proxy
            cache_ttl: Cache time-to-live in seconds (default 900 = 15 min)
        """
        self.llm_provider = llm_provider
        self.extraction_model = extraction_model
        self.web_fetcher = WebFetchTool(max_chars=max_chars, proxy=proxy)
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, str]] = {}  # url -> (timestamp, result)

    async def execute(
        self,
        url: str,
        prompt: str,
        max_chars: int | None = None,
        **kwargs: Any
    ) -> str:
        """
        Fetch URL and extract information using AI.

        Args:
            url: URL to fetch
            prompt: What information to extract
            max_chars: Optional max characters to fetch

        Returns:
            AI-extracted information from the page
        """
        import time

        # Check cache
        cache_key = f"{url}:{prompt}"
        if cache_key in self._cache:
            timestamp, cached_result = self._cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                logger.debug(f"SmartWebFetch: Cache hit for {url}")
                return cached_result
            else:
                # Clean expired cache entry
                del self._cache[cache_key]

        # Step 1: Fetch URL content
        logger.info(f"SmartWebFetch: Fetching {url}")
        raw_result = await self.web_fetcher.execute(
            url=url,
            extractMode="markdown",
            maxChars=max_chars,
            **kwargs
        )

        # Parse result
        try:
            result_data = json.loads(raw_result)
        except json.JSONDecodeError:
            return f"Error: Failed to parse web fetch result: {raw_result[:200]}"

        # Check for errors
        if "error" in result_data:
            return f"Error fetching URL: {result_data['error']}"

        content = result_data.get("text", "")
        final_url = result_data.get("finalUrl", url)

        if not content:
            return f"Error: No content found at {url}"

        # Step 2: Use LLM to extract information
        logger.info(f"SmartWebFetch: Extracting information with LLM (prompt: {prompt[:50]}...)")

        extraction_prompt = f"""You are a web content analyzer. Extract the requested information from the following web page content.

URL: {final_url}

User Request: {prompt}

Web Page Content:
{content}

Instructions:
- Extract only the information requested by the user
- Be concise but complete
- If the information isn't in the page, say so
- Format your response in a clear, readable way
- Do not include information not relevant to the user's request

Response:"""

        try:
            # Use LLM to extract information
            response = await self.llm_provider.chat(
                messages=[{
                    "role": "user",
                    "content": extraction_prompt
                }],
                max_tokens=4096,
                temperature=0.1,  # Low temperature for focused extraction
                model=self.extraction_model  # Use specified model (e.g., Haiku for speed)
            )

            extracted_info = response.content.strip()

            # Add metadata
            result = f"**Source:** {final_url}\n\n{extracted_info}"

            # Cache the result
            self._cache[cache_key] = (time.time(), result)

            # Clean old cache entries (simple LRU-like cleanup)
            if len(self._cache) > 100:
                # Remove oldest entries
                sorted_cache = sorted(self._cache.items(), key=lambda x: x[1][0])
                for old_key, _ in sorted_cache[:20]:
                    del self._cache[old_key]

            logger.success(f"SmartWebFetch: Successfully extracted information from {url}")
            return result

        except Exception as e:
            logger.error(f"SmartWebFetch: LLM extraction failed: {e}")
            return f"Error during AI extraction: {str(e)}\n\nRaw content available via web_fetch tool."


class SmartWebSearchTool(Tool):
    """
    Search the web and get AI-summarized results.

    Combines web search with AI summarization to provide more useful results.
    """

    name = "smart_web_search"
    description = (
        "Search the web and get AI-summarized, relevant results. "
        "Provide a search query and optionally what specific information you're looking for."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query"
            },
            "focus": {
                "type": "string",
                "description": "Optional: What specific information to focus on in the results (e.g., 'pricing', 'features', 'reviews')"
            },
            "count": {
                "type": "integer",
                "description": "Number of results to analyze (1-5)",
                "minimum": 1,
                "maximum": 5
            }
        },
        "required": ["query"]
    }

    def __init__(
        self,
        llm_provider: LLMProvider,
        smart_fetch_tool: SmartWebFetchTool,
        extraction_model: str | None = None
    ):
        """
        Initialize SmartWebSearchTool.

        Args:
            llm_provider: LLM provider for summarization
            smart_fetch_tool: SmartWebFetchTool instance for fetching pages
            extraction_model: Model to use for summarization
        """
        self.llm_provider = llm_provider
        self.smart_fetch_tool = smart_fetch_tool
        self.extraction_model = extraction_model

    async def execute(
        self,
        query: str,
        focus: str | None = None,
        count: int = 3,
        **kwargs: Any
    ) -> str:
        """
        Search web and return AI-summarized results.

        Args:
            query: Search query
            focus: Optional specific information to focus on
            count: Number of top results to analyze

        Returns:
            AI-summarized search results
        """
        from nanobot.agent.tools.web import WebSearchTool
        import os

        # Step 1: Perform search
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return "Error: Brave Search API key not configured. Set BRAVE_API_KEY environment variable."

        searcher = WebSearchTool(api_key=api_key)
        search_results = await searcher.execute(query=query, count=min(count, 5))

        if search_results.startswith("Error") or search_results.startswith("No results"):
            return search_results

        # Step 2: Extract URLs from search results
        import re
        urls = re.findall(r'https?://[^\s\)]+', search_results)[:count]

        if not urls:
            return f"Search completed but no URLs found in results:\n\n{search_results}"

        # Step 3: Fetch and analyze top results
        logger.info(f"SmartWebSearch: Analyzing {len(urls)} top results for '{query}'")

        analyses = []
        for i, url in enumerate(urls, 1):
            extraction_prompt = focus or f"Summarize the key information relevant to: {query}"
            try:
                analysis = await self.smart_fetch_tool.execute(
                    url=url,
                    prompt=extraction_prompt
                )
                analyses.append(f"**Result {i}:** {analysis}\n")
            except Exception as e:
                logger.warning(f"SmartWebSearch: Failed to analyze {url}: {e}")
                analyses.append(f"**Result {i}:** {url}\n(Could not analyze: {str(e)})\n")

        # Step 4: Synthesize results
        synthesis_prompt = f"""Synthesize the following web search results into a comprehensive answer.

Search Query: {query}
{f"Focus Area: {focus}" if focus else ""}

Search Results:
{"".join(analyses)}

Instructions:
- Provide a clear, comprehensive answer to the search query
- Cite sources by referencing "Result 1", "Result 2", etc.
- If results are conflicting, mention both perspectives
- Be concise but informative

Synthesized Answer:"""

        try:
            response = await self.llm_provider.chat(
                messages=[{
                    "role": "user",
                    "content": synthesis_prompt
                }],
                max_tokens=4096,
                temperature=0.3,
                model=self.extraction_model
            )

            return response.content.strip()

        except Exception as e:
            logger.error(f"SmartWebSearch: Synthesis failed: {e}")
            return f"Search completed but synthesis failed:\n\n{''.join(analyses)}"
