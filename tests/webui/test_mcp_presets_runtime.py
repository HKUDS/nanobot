from __future__ import annotations

from nanobot.webui import mcp_presets_runtime


def test_mcp_preset_session_extra_only_persists_structured_mentions() -> None:
    assert mcp_presets_runtime.session_extra({}) == {}
    assert mcp_presets_runtime.session_extra({
        "mcp_presets": [{"name": "browserbase"}],
    }) == {"mcp_presets": [{"name": "browserbase"}]}
