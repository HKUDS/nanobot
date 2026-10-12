"""The committed Docker deploy template must always bake into a startable config.

`entrypoint.sh` initializes `~/.nanobot/config.json` from `docker-config.json`
on first boot (see docker-compose.yml). A template that drifts out of sync with
the config schema would crash-loop every container on a fresh `docker compose
up`, so pin the contract here: the baked config validates, and its wildcard
binds carry the secrets their security validators require.
"""

import json
from pathlib import Path

from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.config.schema import Config

repo_root = Path(__file__).resolve().parents[1]

WEB_TOKEN_PLACEHOLDER = "${NANOBOT_WEB_TOKEN}"
API_KEY_PLACEHOLDER = "${NANOBOT_API_KEY}"


def _template() -> dict:
    return json.loads((repo_root / "docker-config.json").read_text())


def _baked() -> dict:
    """The template as the entrypoint writes it, with both secrets substituted."""
    raw = (repo_root / "docker-config.json").read_text()
    raw = raw.replace(WEB_TOKEN_PLACEHOLDER, "test-web-token")
    raw = raw.replace(API_KEY_PLACEHOLDER, "test-api-key")
    return json.loads(raw)


def test_docker_template_bakes_to_a_valid_container_config():
    config = Config.model_validate(_baked())

    # Binds must survive the container boundary: a loopback bind inside the
    # container is unreachable through the ports docker-compose.yml publishes.
    assert config.gateway.host == "0.0.0.0"
    assert config.api.host == "0.0.0.0"
    assert config.api.api_key == "test-api-key"


def test_docker_template_websocket_satisfies_wildcard_host_auth():
    ws = WebSocketConfig.model_validate(_baked()["channels"]["websocket"])

    assert ws.enabled is True
    assert ws.host == "0.0.0.0"
    assert ws.port == 8765
    assert ws.token_issue_secret
    assert ws.websocket_requires_token is True


def test_docker_template_secrets_are_wired_for_entrypoint_substitution():
    # entrypoint.sh substitutes exactly these placeholders when writing
    # config.json (env value if provided, generated otherwise). A renamed
    # placeholder would survive substitution and reach the runtime as a
    # literal string, breaking every client that needs the real secret.
    template = _template()

    assert template["channels"]["websocket"]["tokenIssueSecret"] == WEB_TOKEN_PLACEHOLDER
    assert template["api"]["api_key"] == API_KEY_PLACEHOLDER
    assert "${" not in json.dumps(_baked())


def test_docker_template_uses_the_same_shape_as_the_render_template():
    docker_template = _template()
    render_template = json.loads((repo_root / "render-config.json").read_text())

    assert set(docker_template["channels"]["websocket"]) == set(
        render_template["channels"]["websocket"]
    )
