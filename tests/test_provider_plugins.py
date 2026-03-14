from dataclasses import dataclass

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.cli.commands import _make_provider
from nanobot.config.schema import Config, ProviderConfig

runner = CliRunner()


@dataclass
class _FakeEntryPoint:
    name: str
    value: object

    def load(self):
        return self.value


class _FakeEntryPoints(list):
    def select(self, *, group: str):
        if group == "nanobot.provider_specs":
            return self
        return []


def test_registry_loads_provider_specs_from_entry_points(monkeypatch):
    import nanobot.providers.registry as registry

    plugin_spec = registry.ProviderSpec(
        name="plugin_demo",
        keywords=("plugin_demo", "demo"),
        env_key="PLUGIN_DEMO_API_KEY",
        display_name="Plugin Demo",
        litellm_prefix="plugin_demo",
        skip_prefixes=("plugin_demo/",),
    )

    monkeypatch.setattr(
        registry.importlib_metadata,
        "entry_points",
        lambda: _FakeEntryPoints([_FakeEntryPoint("plugin-demo", lambda: plugin_spec)]),
    )

    registry.reload_providers()
    loaded = registry.find_by_name("plugin_demo")
    assert loaded is not None
    assert loaded.display_name == "Plugin Demo"


def test_config_can_read_plugin_provider_config(monkeypatch):
    import nanobot.providers.registry as registry

    plugin_spec = registry.ProviderSpec(
        name="plugin_demo",
        keywords=("plugin_demo",),
        env_key="PLUGIN_DEMO_API_KEY",
        display_name="Plugin Demo",
        litellm_prefix="plugin_demo",
        skip_prefixes=("plugin_demo/",),
    )

    monkeypatch.setattr(
        registry.importlib_metadata,
        "entry_points",
        lambda: _FakeEntryPoints([_FakeEntryPoint("plugin-demo", lambda: plugin_spec)]),
    )

    registry.reload_providers()
    config = Config()
    config.providers.plugins["plugin_demo"] = ProviderConfig(api_key="plugin-key")
    config.agents.defaults.provider = "plugin-demo"

    assert config.get_provider_name() == "plugin_demo"
    assert config.get_api_key() == "plugin-key"


def test_make_provider_uses_plugin_factory(monkeypatch):
    config = Config()
    config.agents.defaults.model = "plugin-demo/some-model"
    config.agents.defaults.provider = "plugin_demo"
    config.providers.plugins["plugin_demo"] = ProviderConfig(api_key="plugin-key")

    sentinel = object()

    monkeypatch.setattr(
        "nanobot.providers.provider_plugins.get_provider_factory",
        lambda name: (lambda **kwargs: sentinel) if name == "plugin_demo" else None,
    )

    provider = _make_provider(config)

    assert provider is sentinel


def test_provider_reload_command(monkeypatch):
    import nanobot.providers.registry as registry

    builtin = registry.ProviderSpec(
        name="openai",
        keywords=("openai",),
        env_key="OPENAI_API_KEY",
    )
    plugin = registry.ProviderSpec(
        name="plugin_demo",
        keywords=("plugin_demo",),
        env_key="PLUGIN_DEMO_API_KEY",
    )

    monkeypatch.setattr("nanobot.providers.registry.BUILTIN_PROVIDERS", (builtin,))
    monkeypatch.setattr("nanobot.providers.registry.reload_providers", lambda: (builtin, plugin))
    monkeypatch.setattr("nanobot.providers.provider_plugins.load_provider_factories", lambda: {"plugin_demo": lambda **_: None})

    result = runner.invoke(app, ["provider", "reload"])

    assert result.exit_code == 0
    assert "Reloaded providers" in result.stdout
    assert "plugins: 1" in result.stdout
    assert "plugin-demo" in result.stdout
