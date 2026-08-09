import logging

from nanobot.utils.logging_bridge import redirect_lib_logging


def _reset_logger(name: str) -> None:
    lib_logger = logging.getLogger(name)
    lib_logger.handlers = []
    lib_logger.setLevel(logging.NOTSET)
    lib_logger.propagate = True


def test_redirect_lib_logging_sets_logger_level_so_records_reach_the_handler() -> None:
    """Without an explicit logger level, records below root's default WARNING
    never reach the bridge handler regardless of what the handler filters."""
    name = "test_lib_no_level"
    _reset_logger(name)
    try:
        redirect_lib_logging(name)

        lib_logger = logging.getLogger(name)
        assert lib_logger.isEnabledFor(logging.DEBUG)
        assert lib_logger.propagate is False
    finally:
        _reset_logger(name)


def test_redirect_lib_logging_with_level_filters_at_logger_and_handler() -> None:
    name = "test_lib_warning_level"
    _reset_logger(name)
    try:
        redirect_lib_logging(name, level="WARNING")

        lib_logger = logging.getLogger(name)
        assert not lib_logger.isEnabledFor(logging.INFO)
        assert lib_logger.isEnabledFor(logging.WARNING)
        assert lib_logger.handlers[0].level == logging.WARNING
    finally:
        _reset_logger(name)


def test_redirect_lib_logging_is_idempotent() -> None:
    name = "test_lib_idempotent"
    _reset_logger(name)
    try:
        redirect_lib_logging(name)
        redirect_lib_logging(name)

        lib_logger = logging.getLogger(name)
        assert len(lib_logger.handlers) == 1
    finally:
        _reset_logger(name)
