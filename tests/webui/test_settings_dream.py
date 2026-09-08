import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.webui.settings_contracts import WebUISettingsError
from nanobot.webui.settings_dream import dream_prompt_payload, update_dream_prompt


def test_dream_prompt_roundtrip_and_reset(tmp_path):
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    before = config_path.read_bytes()
    assert not dream_prompt_payload(config)["custom"]
    result = update_dream_prompt("Organize memory in Chinese.\n", config_path=config_path)
    assert result["custom"]
    assert result["content"] == "Organize memory in Chinese.\n"
    store = MemoryStore(config.workspace_path)
    assert store._dream_template() == "Organize memory in Chinese."
    result = update_dream_prompt(None, config_path=config_path)
    assert not result["custom"]
    assert store._dream_template() == MemoryStore.default_dream_prompt()
    assert config_path.read_bytes() == before


@pytest.mark.parametrize("content", ["", "  ", "x" * 32001, 1, {}, False])
def test_invalid_prompt_preserves_file(tmp_path, content):
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    update_dream_prompt("Existing prompt", config_path=config_path)
    with pytest.raises(WebUISettingsError):
        update_dream_prompt(content, config_path=config_path)
    assert dream_prompt_payload(config)["content"] == "Existing prompt"


def test_prompt_symlink_cannot_escape_workspace(tmp_path):
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    prompts = config.workspace_path / "prompts"
    prompts.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")
    try:
        (prompts / "dream.md").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks unavailable")
    assert not dream_prompt_payload(config)["editable"]
    assert dream_prompt_payload(config)["content"] != "private"
    with pytest.raises(WebUISettingsError):
        update_dream_prompt("replace", config_path=config_path)
    assert outside.read_text() == "private"
