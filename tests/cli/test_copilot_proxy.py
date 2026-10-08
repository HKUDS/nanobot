import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nanobot.cli.provider import _login_github_copilot
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


@pytest.mark.parametrize("proxy", [None, "${COPILOT_CLI_TEST_PROXY}"])
def test_copilot_cli_login_passes_configured_proxy(monkeypatch, tmp_path, proxy):
    monkeypatch.setenv("COPILOT_CLI_TEST_PROXY", "http://127.0.0.1:7890")
    config = Config()
    config.providers.github_copilot.proxy = proxy
    path = tmp_path / "config.json"
    save_config(config, path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", path)
    login = Mock(return_value=SimpleNamespace(account_id="test-account"))
    monkeypatch.setattr("nanobot.providers.github_copilot_provider.login_github_copilot", login)
    _login_github_copilot()
    assert login.call_args.kwargs["proxy"] == ("http://127.0.0.1:7890" if proxy else None)


def test_copilot_proxy_persistence_does_not_save_oauth_credentials(tmp_path):
    config = Config()
    config.providers.github_copilot.api_key = "must-not-save"
    config.providers.github_copilot.proxy = "http://127.0.0.1:7890"
    path = tmp_path / "config.json"
    save_config(config, path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["providers"]["githubCopilot"] == {"proxy": "http://127.0.0.1:7890"}
    assert load_config(path).providers.github_copilot.proxy == "http://127.0.0.1:7890"
