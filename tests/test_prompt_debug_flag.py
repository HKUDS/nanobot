from types import SimpleNamespace

from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import ChannelsConfig


def _mk_loop(prompt_debug: bool) -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop.channels_config = ChannelsConfig(promptDebug=prompt_debug)
    return loop


def test_log_prompt_debug_disabled(monkeypatch):
    loop = _mk_loop(False)
    calls = []

    def fake_info(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("nanobot.agent.loop.logger.info", fake_info)
    loop._log_prompt_debug("stage", [{"role": "user", "content": "hello"}])
    assert calls == []


def test_log_prompt_debug_enabled(monkeypatch):
    loop = _mk_loop(True)
    calls = []

    def fake_info(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("nanobot.agent.loop.logger.info", fake_info)
    loop._log_prompt_debug("stage", [{"role": "user", "content": "hello"}])
    assert len(calls) >= 2


def test_channels_config_accepts_prompt_debug_flag():
    cfg = ChannelsConfig(promptDebug=True)
    assert cfg.prompt_debug is True
