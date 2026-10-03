import importlib

from nanobot.session import webui_turns
from nanobot.webui import thread_disk, transcript


def test_legacy_webui_utils_imports_resolve_to_new_modules() -> None:
    legacy_thread_disk = importlib.import_module("nanobot.utils.webui_thread_disk")
    legacy_transcript = importlib.import_module("nanobot.utils.webui_transcript")
    legacy_turn_helpers = importlib.import_module("nanobot.utils.webui_turn_helpers")

    assert legacy_thread_disk.delete_webui_thread is thread_disk.delete_webui_thread
    assert legacy_transcript.append_transcript_object is transcript.append_transcript_object
    assert legacy_turn_helpers.mark_webui_session is webui_turns.mark_webui_session
