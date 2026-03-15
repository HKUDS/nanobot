from nanobot.config.schema import Config


def test_agents_config_collects_members() -> None:
    data = {
        "agents": {
            "defaults": {
                "workspace": "~/.nanobot/workspace",
                "model": "gpt-5.2-codex",
            },
            "coder": {
                "workspace": "~/.nanobot/coder",
                "model": "gpt-5.4-codex",
            },
        }
    }

    config = Config.model_validate(data)

    assert "coder" in config.agents.members
    assert config.agents.get_member("coder").model == "gpt-5.4-codex"

    members = config.agents.list_members()
    assert "defaults" in members
    assert "coder" in members


def test_agents_config_defaults_fallbacks_to_first_member() -> None:
    data = {
        "agents": {
            "coder": {
                "workspace": "~/.nanobot/coder",
                "model": "gpt-5.4-codex",
            },
            "tester": {
                "workspace": "~/.nanobot/tester",
                "model": "gpt-5.2-codex",
            },
        }
    }

    config = Config.model_validate(data)
    assert config.agents.defaults.model == "gpt-5.4-codex"
