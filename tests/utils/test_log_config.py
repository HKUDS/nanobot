import json
from io import StringIO

from loguru import logger

from nanobot.utils.log_config import add_console_log_sink


def test_console_log_sink_includes_context_and_escapes_message_newlines() -> None:
    output = StringIO()
    sink = add_console_log_sink(output, level="DEBUG")
    try:
        with logger.contextualize(
            request_id="request-1",
            turn_id="turn-1",
            session_key="channel:chat",
        ):
            logger.bind(channel="test").info("first line\nsecond line")
    finally:
        logger.remove(sink)

    rendered = output.getvalue()
    assert "request=request-1 turn=turn-1 session=channel:chat" in rendered
    assert "first line\\nsecond line" in rendered
    assert "first line\nsecond line" not in rendered


def test_console_log_sink_keeps_exception_traceback_multiline() -> None:
    output = StringIO()
    sink = add_console_log_sink(output)
    try:
        try:
            raise RuntimeError("broken")
        except RuntimeError:
            logger.opt(exception=True).error("operation failed")
    finally:
        logger.remove(sink)

    rendered = output.getvalue()
    assert "operation failed" in rendered
    assert "RuntimeError: broken" in rendered


def test_console_log_sink_hides_rejected_config_values_from_exception_frames(tmp_path) -> None:
    from nanobot.webui.nanobot_features_api import nanobot_features_payload

    path = tmp_path / "config.json"
    secret = "synthetic-proxy-password"
    path.write_text(json.dumps({"providers": {"openai": {"proxy": f"http://user:{secret}@host:8080"}}}), encoding="utf-8")
    output = StringIO()
    sink = add_console_log_sink(output)
    try:
        try:
            nanobot_features_payload(config_path=path)
        except ValueError:
            logger.exception("failed to load nanobot features")
    finally:
        logger.remove(sink)

    rendered = output.getvalue()
    assert "failed to load nanobot features" in rendered
    assert "Legacy proxy settings" in rendered
    assert secret not in rendered



def _log_sdk_configuration_failure(path) -> None:
    from nanobot import Nanobot

    try:
        Nanobot.from_config(path)
    except ValueError:
        logger.exception("failed to load SDK configuration")


def test_sdk_config_error_is_safe_with_diagnostic_traceback(tmp_path) -> None:
    path = tmp_path / "config.json"
    secret = "synthetic-sdk-proxy-password"
    path.write_text(json.dumps({"providers": {"openai": {"proxy": f"http://user:{secret}@host:8080"}}}), encoding="utf-8")
    output = StringIO()
    sink = logger.add(output, diagnose=True)
    try:
        _log_sdk_configuration_failure(path)
    finally:
        logger.remove(sink)

    rendered = output.getvalue()
    assert "failed to load SDK configuration" in rendered
    assert "Legacy proxy settings" in rendered
    assert secret not in rendered
