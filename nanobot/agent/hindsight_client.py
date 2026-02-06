"""Optional Hindsight client wrapper for semantic agent memory. Requires hindsight-client."""

import asyncio
from typing import Any

from loguru import logger

_HINDSIGHT_CLIENT = None


def _get_client(base_url: str):  # noqa: ANN201
    """Lazy import of Hindsight; returns None if package not installed or import fails."""
    global _HINDSIGHT_CLIENT
    if _HINDSIGHT_CLIENT is not None:
        return _HINDSIGHT_CLIENT
    try:
        from hindsight_client import Hindsight
        _HINDSIGHT_CLIENT = Hindsight
        return Hindsight
    except ImportError:
        logger.warning(
            "Hindsight is enabled but hindsight-client is not installed. "
            "Install with: pip install nanobot-ai[hindsight] or pip install hindsight-client"
        )
        return None


async def recall(base_url: str, bank_id: str, query: str, timeout: float = 10.0) -> str:
    """Retrieve relevant memories from Hindsight. Returns empty string on error or if disabled."""
    Klass = _get_client(base_url)
    if not Klass or not query.strip():
        return ""

    client = None
    try:
        client = Klass(base_url=base_url)

        def _sync_recall() -> str:
            results = client.recall(bank_id=bank_id, query=query)
            if isinstance(results, str):
                return results
            if not results:
                return ""
            # Extract text from RecallResult objects and join
            texts = []
            for item in results:
                if hasattr(item, "text") and item.text:
                    texts.append(item.text)
            return "\n\n".join(texts) if texts else ""

        result = await asyncio.wait_for(
            asyncio.to_thread(_sync_recall),
            timeout=timeout,
        )
        if result:
            logger.debug(f"Hindsight recall (bank={bank_id}): {result[:100]}...")
        return result
    except asyncio.TimeoutError:
        logger.warning("Hindsight recall timed out")
        return ""
    except Exception as e:
        logger.warning(f"Hindsight recall failed: {e}")
        return ""
    finally:
        if client:
            try:
                # Shield cleanup from cancellation to ensure connection closes
                await asyncio.wait_for(asyncio.shield(client.aclose()), timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                # If cleanup times out or fails, try to close synchronously as fallback
                try:
                    if hasattr(client, 'close'):
                        client.close()
                except Exception:
                    pass


async def reflect(base_url: str, bank_id: str, query: str, timeout: float = 15.0) -> str:
    """Reflect on memories; returns disposition-aware summary. Empty string on error."""
    Klass = _get_client(base_url)
    if not Klass or not query.strip():
        return ""

    client = None
    try:
        client = Klass(base_url=base_url)

        def _sync_reflect() -> str:
            result = client.reflect(bank_id=bank_id, query=query)
            if isinstance(result, str):
                return result
            return str(result) if result is not None else ""

        result = await asyncio.wait_for(
            asyncio.to_thread(_sync_reflect),
            timeout=timeout,
        )
        if result:
            logger.debug(f"Hindsight reflect (bank={bank_id}): {result[:100]}...")
        return result
    except asyncio.TimeoutError:
        logger.warning("Hindsight reflect timed out")
        return ""
    except Exception as e:
        logger.warning(f"Hindsight reflect failed: {e}")
        return ""
    finally:
        if client:
            try:
                # Shield cleanup from cancellation to ensure connection closes
                await asyncio.wait_for(asyncio.shield(client.aclose()), timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                # If cleanup times out or fails, try to close synchronously as fallback
                try:
                    if hasattr(client, 'close'):
                        client.close()
                except Exception:
                    pass


async def retain(
    base_url: str,
    bank_id: str,
    content: str,
    context: str | None = None,
    timeout: float = 15.0,
) -> None:
    """Store content in Hindsight (fire-and-forget). Logs and swallows errors."""
    Klass = _get_client(base_url)
    if not Klass or not content.strip():
        return

    client = None
    try:
        client = Klass(base_url=base_url)

        def _sync_retain() -> None:
            client.retain(bank_id=bank_id, content=content, context=context or "")

        await asyncio.wait_for(
            asyncio.to_thread(_sync_retain),
            timeout=timeout,
        )
        logger.info(f"Hindsight retain (bank={bank_id}): stored {len(content)} chars")
    except asyncio.TimeoutError:
        logger.warning("Hindsight retain timed out")
    except Exception as e:
        logger.warning(f"Hindsight retain failed: {e}")
    finally:
        if client:
            try:
                # Use shield to protect cleanup from cancellation, with longer timeout
                await asyncio.wait_for(asyncio.shield(client.aclose()), timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as e:
                # If cleanup times out or fails, try to close synchronously as fallback
                # This is best-effort cleanup; pending tasks will be cleaned up on process exit
                try:
                    if hasattr(client, 'close'):
                        client.close()
                except Exception:
                    pass
                # Suppress the warning about pending tasks - they'll be cleaned up eventually
                logger.debug(f"Hindsight retain cleanup completed with pending tasks (non-critical): {type(e).__name__}")
