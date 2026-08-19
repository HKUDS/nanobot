from nanobot.cli.entry import _native_tui_candidate


def test_native_agent_invocations_use_the_lightweight_entrypoint() -> None:
    assert _native_tui_candidate(["agent"])
    assert _native_tui_candidate(["agent", "--session", "websocket:chat"])
    assert _native_tui_candidate(["agent", "--theme=light"])


def test_classic_and_one_shot_agent_invocations_keep_the_full_cli_entrypoint() -> None:
    assert not _native_tui_candidate(["agent", "--classic"])
    assert not _native_tui_candidate(["agent", "-m", "hello"])
    assert not _native_tui_candidate(["agent", "-mhello"])
    assert not _native_tui_candidate(["agent", "--message=hello"])
    assert not _native_tui_candidate(["status"])
