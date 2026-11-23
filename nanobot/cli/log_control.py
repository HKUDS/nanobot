from loguru import logger

__all__ = ["_set_nanobot_logs"]


def _set_nanobot_logs(enabled: bool) -> None:
    if enabled:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")
