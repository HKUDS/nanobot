#!/usr/bin/env python3
"""Start NanoCats backend: API server + WebSocket server"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("nanocats")


async def main():
    from nanobot.api.nanocats import start_api
    from nanobot.websocket import start_nanocats_ws

    # Start both servers
    logger.info("Starting NanoCats API server on port 18792...")
    await start_api("0.0.0.0", 18792)

    logger.info("Starting NanoCats WebSocket server on port 18791...")
    start_nanocats_ws("0.0.0.0", 18791)

    logger.info("=" * 50)
    logger.info("NanoCats Backend running!")
    logger.info("  - REST API: http://localhost:18792")
    logger.info("  - WebSocket: ws://localhost:18791")
    logger.info("=" * 50)

    # Keep running
    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
