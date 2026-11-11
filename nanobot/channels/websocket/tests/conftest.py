from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_websocket_runtime_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep transcripts and other runtime files out of the active user data directory."""
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    # In-process routes must not intercept a later test's real listener on a reused port.
    monkeypatch.setattr("nanobot.channels.websocket.tests.ws_test_client._IN_PROCESS_HTTP_CHANNELS", {})
