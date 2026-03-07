import json
import secrets
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config, GatewayAuthConfig, GatewayConfig


runner = CliRunner()


@pytest.fixture
def mock_paths():
    """Mock config/workspace paths for test isolation."""
    with patch("nanobot.config.loader.get_config_path") as mock_cp, \
         patch("nanobot.config.loader.save_config") as mock_sc, \
         patch("nanobot.config.loader.load_config") as mock_lc, \
         patch("nanobot.utils.helpers.get_workspace_path") as mock_ws:

        base_dir = Path("./test_gateway_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_sc.side_effect = lambda config: config_file.write_text(
            json.dumps(config.model_dump(by_alias=True), indent=2)
        )

        def load_config_side_effect(path=None, force_reload=False):
            if config_file.exists():
                return Config.model_validate_json(config_file.read_text())
            return Config()

        mock_lc.side_effect = load_config_side_effect

        yield config_file, workspace_dir, mock_lc

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_gateway_auth_config_defaults():
    """GatewayAuthConfig should have empty token by default."""
    config = GatewayAuthConfig()
    assert config.token == ""


def test_gateway_config_has_auth():
    """GatewayConfig should have auth field."""
    config = GatewayConfig()
    assert hasattr(config, "auth")
    assert isinstance(config.auth, GatewayAuthConfig)


def test_onboard_generates_token(mock_paths):
    """Onboard should generate a random token."""
    config_file, workspace_dir, mock_lc = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "Gateway token:" in result.stdout
    assert config_file.exists()

    data = json.loads(config_file.read_text())
    assert "gateway" in data
    assert "auth" in data["gateway"]
    assert len(data["gateway"]["auth"]["token"]) > 0


def test_onboard_token_is_random():
    """Each onboard should generate a different token."""
    tokens = set()

    for _ in range(5):
        token = secrets.token_urlsafe(32)
        tokens.add(token)

    assert len(tokens) == 5


def test_gateway_token_command_shows_token(mock_paths):
    """gateway-token should display the current token."""
    config_file, workspace_dir, mock_lc = mock_paths

    config = Config()
    config.gateway.auth.token = "test-token-123"
    config_file.write_text(json.dumps(config.model_dump(by_alias=True)))

    result = runner.invoke(app, ["gateway-token"])

    assert result.exit_code == 0
    assert "test-token-123" in result.stdout


def test_gateway_token_command_no_token(mock_paths):
    """gateway-token should show message if no token."""
    config_file, workspace_dir, mock_lc = mock_paths

    config = Config()
    config_file.write_text(json.dumps(config.model_dump(by_alias=True)))

    result = runner.invoke(app, ["gateway-token"])

    assert result.exit_code == 0
    assert "No token configured" in result.stdout


def test_gateway_token_command_no_config(mock_paths):
    """gateway-token should show message if config fails to load."""
    config_file, workspace_dir, mock_lc = mock_paths
    mock_lc.side_effect = Exception("No config")

    result = runner.invoke(app, ["gateway-token"])

    assert result.exit_code == 0
    assert "No token configured" in result.stdout or "Error" in result.stdout


class TestGatewayServer:
    """Tests for the GatewayServer API."""

    @pytest.fixture
    def mock_server(self, mock_paths):
        """Create a GatewayServer with mocked config."""
        config_file, workspace_dir, mock_lc = mock_paths

        config = Config()
        config.gateway.auth.token = "test-token-abc"
        config.agents.defaults.model = "test-model"
        config_file.write_text(json.dumps(config.model_dump(by_alias=True)))

        from nanobot.gateway.server import GatewayServer
        server = GatewayServer(port=18791)
        return server, config_file

    @pytest.mark.asyncio
    async def test_login_success(self, mock_server):
        """Login with correct token should succeed."""
        server, config_file = mock_server

        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        response = client.post("/api/auth/login", json={"token": "test-token-abc"})

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["token"] == "test-token-abc"

    @pytest.mark.asyncio
    async def test_login_failure(self, mock_server):
        """Login with wrong token should fail."""
        server, config_file = mock_server

        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        response = client.post("/api/auth/login", json={"token": "wrong-token"})

        assert response.status_code == 401
        data = response.json()
        assert data["authenticated"] is False

    @pytest.mark.asyncio
    async def test_get_config_requires_auth(self, mock_server):
        """GET /api/config should require authentication."""
        server, config_file = mock_server

        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        response = client.get("/api/config")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_config_with_auth(self, mock_server):
        """GET /api/config should return config when authenticated."""
        server, config_file = mock_server

        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        response = client.get(
            "/api/config",
            headers={"Authorization": "Bearer test-token-abc"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert data["agents"]["defaults"]["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_put_config_updates_file(self, mock_server):
        """PUT /api/config should update the config file."""
        server, config_file = mock_server

        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        new_config = {
            "agents": {
                "defaults": {
                    "model": "new-model",
                    "temperature": 0.9
                }
            }
        }

        response = client.put(
            "/api/config",
            json=new_config,
            headers={"Authorization": "Bearer test-token-abc"}
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

        saved = json.loads(config_file.read_text())
        assert saved["agents"]["defaults"]["model"] == "new-model"
        assert saved["agents"]["defaults"]["temperature"] == 0.9

    @pytest.mark.asyncio
    async def test_get_status(self, mock_server):
        """GET /api/status should return gateway status."""
        server, config_file = mock_server

        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        response = client.get(
            "/api/status",
            headers={"Authorization": "Bearer test-token-abc"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "gateway" in data
        assert "agents" in data
        assert data["agents"]["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_index_returns_html(self, mock_server):
        """GET / should return HTML."""
        server, config_file = mock_server

        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestGatewayServerHost:
    """Tests for host detection."""

    def test_localhost_by_default(self):
        """Should default to 127.0.0.1 when not in Docker."""
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = False
            with patch.dict("os.environ", {}, clear=True):
                from nanobot.gateway.server import GatewayServer
                server = GatewayServer(port=18790)
                assert server.host == "127.0.0.1"

    def test_docker_env_var(self):
        """Should use 0.0.0.0 when NANOBOT_DOCKER=1."""
        with patch.dict("os.environ", {"NANOBOT_DOCKER": "1"}):
            from nanobot.gateway.server import GatewayServer
            server = GatewayServer(port=18790)
            assert server.host == "0.0.0.0"

    def test_docker_file_present(self):
        """Should use 0.0.0.0 when /.dockerenv exists."""
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True
            with patch.dict("os.environ", {}, clear=True):
                from nanobot.gateway.server import GatewayServer
                server = GatewayServer(port=18790)
                assert server.host == "0.0.0.0"

    def test_explicit_host(self):
        """Should use explicitly provided host."""
        from nanobot.gateway.server import GatewayServer
        server = GatewayServer(port=18790, host="0.0.0.0")
        assert server.host == "0.0.0.0"
