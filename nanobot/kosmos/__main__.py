"""Kosmos server entry point.

Usage:
    python -m nanobot.kosmos [--host HOST] [--port PORT] [--db-path PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from loguru import logger

from nanobot.kosmos.server import KosmosServer


def setup_logging(level: str = "INFO"):
    """Configure logging for the Kosmos server."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level=level,
    )


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kosmos - Project/Task Management Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=18794,
        help="REST API port (default: 18794, WebSocket on port+1)",
    )
    parser.add_argument(
        "--db-path",
        default="~/.nanobot/kosmos.db",
        help="Path to SQLite database (default: ~/.nanobot/kosmos.db)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    return parser.parse_args()


async def async_main(args):
    """Async main entry point."""
    from pathlib import Path

    db_path = Path(args.db_path).expanduser()

    server = KosmosServer(
        host=args.host,
        port=args.port,
        db_path=db_path,
    )

    logger.info("=" * 50)
    logger.info("Kosmos Server")
    logger.info("=" * 50)
    logger.info("REST API: http://{}:{}", args.host, args.port)
    logger.info("WebSocket: ws://{}:{}", args.host, args.port + 1)
    logger.info("Database: {}", db_path)
    logger.info("=" * 50)

    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await server.close_db()


def main():
    """Main entry point."""
    args = parse_args()
    setup_logging(args.log_level)
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
