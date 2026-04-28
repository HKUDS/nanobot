from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.factory import ProviderSnapshot


def _provider(default_model: str, max_tokens: int = 123) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(max_tokens=max_tokens)
    return provider


def test_provider_refresh_updates_all_model_dependents(tmp_path: Path) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model", max_tokens=456)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="old-model",
        context_window_tokens=1000,
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )

    loop._refresh_provider_snapshot()

    assert loop.provider is new_provider
    assert loop.model == "new-model"
    assert loop.context_window_tokens == 2000
    assert loop.runner.provider is new_provider
    assert loop.subagents.provider is new_provider
    assert loop.subagents.model == "new-model"
    assert loop.subagents.runner.provider is new_provider
    assert loop.consolidator.provider is new_provider
    assert loop.consolidator.model == "new-model"
    assert loop.consolidator.context_window_tokens == 2000
    assert loop.consolidator.max_completion_tokens == 456
    assert loop.dream.provider is new_provider
    assert loop.dream.model == "new-model"
    assert loop.dream._runner.provider is new_provider
