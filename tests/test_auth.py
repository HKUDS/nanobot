"""Tests for nanobot auth module and CLI command."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from nanobot.auth import AuthInfo, delete_auth, load_auth, save_auth


# ---------------------------------------------------------------------------
# Token storage tests (nanobot/auth/__init__.py)
# ---------------------------------------------------------------------------


class TestAuthStorage:
    """Test save/load/delete cycle and edge cases."""

    def test_save_and_load(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            info = AuthInfo(token="nb_abc123", server_url="http://localhost:9999")
            save_auth(info)

            loaded = load_auth()
            assert loaded is not None
            assert loaded.token == "nb_abc123"
            assert loaded.server_url == "http://localhost:9999"
            assert loaded.expires_at is None

    def test_save_with_expires_at(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            info = AuthInfo(token="nb_test", server_url="http://test", expires_at=1234567890.0)
            save_auth(info)

            loaded = load_auth()
            assert loaded.expires_at == 1234567890.0

    def test_load_missing_file(self, tmp_path):
        auth_file = tmp_path / "nonexistent.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            assert load_auth() is None

    def test_load_corrupt_json(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        auth_file.write_text("{bad json", encoding="utf-8")
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            assert load_auth() is None

    def test_load_missing_token_key(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        auth_file.write_text('{"server_url": "http://test"}', encoding="utf-8")
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            assert load_auth() is None

    def test_delete_existing(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        auth_file.write_text("{}", encoding="utf-8")
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            assert delete_auth() is True
            assert not auth_file.exists()

    def test_delete_nonexistent(self, tmp_path):
        auth_file = tmp_path / "nonexistent.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            assert delete_auth() is False

    def test_save_creates_parent_dir(self, tmp_path):
        auth_file = tmp_path / "nested" / "dir" / "auth.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            save_auth(AuthInfo(token="nb_test", server_url="http://test"))
            assert auth_file.exists()


# ---------------------------------------------------------------------------
# CLI auth command tests (nanobot/cli/auth.py)
# ---------------------------------------------------------------------------


def _mock_httpx_response(status_code=200, json_data=None):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestCmdStatus:
    def test_not_authenticated(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            from nanobot.cli.auth import cmd_auth
            # Should not raise, just print
            cmd_auth(status=True)

    def test_authenticated_valid_token(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            save_auth(AuthInfo(token="nb_valid", server_url="http://localhost:9999"))

        mock_resp = _mock_httpx_response(json_data={"valid": True, "token": "nb_valid"})
        with patch("nanobot.auth._auth_file_path", return_value=auth_file), \
             patch("httpx.get", return_value=mock_resp) as mock_get:
            from nanobot.cli.auth import cmd_auth
            cmd_auth(status=True)
            mock_get.assert_called_once_with(
                "http://localhost:9999/auth/verify",
                headers={"Authorization": "Bearer nb_valid"},
                timeout=10,
            )

    def test_authenticated_invalid_token(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            save_auth(AuthInfo(token="nb_expired", server_url="http://localhost:9999"))

        mock_resp = _mock_httpx_response(json_data={"valid": False, "token": None})
        with patch("nanobot.auth._auth_file_path", return_value=auth_file), \
             patch("httpx.get", return_value=mock_resp):
            from nanobot.cli.auth import cmd_auth
            cmd_auth(status=True)  # Should print invalid message, not crash


class TestCmdLogout:
    def test_logout_when_authenticated(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            save_auth(AuthInfo(token="nb_test", server_url="http://test"))
            assert auth_file.exists()

        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            from nanobot.cli.auth import cmd_auth
            cmd_auth(logout=True)
            assert not auth_file.exists()

    def test_logout_when_not_authenticated(self, tmp_path):
        auth_file = tmp_path / "nonexistent.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file):
            from nanobot.cli.auth import cmd_auth
            cmd_auth(logout=True)  # Should print "Not logged in", not crash


class TestCmdAuthKey:
    def test_invalid_prefix(self):
        from nanobot.cli.auth import cmd_auth
        with pytest.raises(SystemExit):
            cmd_auth(auth_key="invalid_key")

    def test_valid_key(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        mock_resp = _mock_httpx_response(json_data={"valid": True, "token": "nb_goodkey"})
        mock_models_resp = _mock_httpx_response(json_data={
            "object": "list", "data": [{"id": "glm-5.1", "object": "model", "owned_by": "nanobot"}]
        })

        with patch("nanobot.auth._auth_file_path", return_value=auth_file), \
             patch("nanobot.config.loader.load_config", return_value=MagicMock()), \
             patch("nanobot.config.loader.save_config"), \
             patch("httpx.get", side_effect=[mock_resp, mock_models_resp]) as mock_get:
            from nanobot.cli.auth import cmd_auth
            cmd_auth(auth_key="nb_goodkey", server_url="http://localhost:9999")

            # First call: verify key
            first_call = mock_get.call_args_list[0]
            assert first_call[0][0] == "http://localhost:9999/auth/verify"
            assert first_call[1]["headers"] == {"Authorization": "Bearer nb_goodkey"}
            assert first_call[1]["timeout"] == 10
            # Auth file saved
            loaded = load_auth()
            assert loaded.token == "nb_goodkey"

    def test_invalid_key_rejected(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        mock_resp = _mock_httpx_response(json_data={"valid": False, "token": None})

        with patch("nanobot.auth._auth_file_path", return_value=auth_file), \
             patch("httpx.get", return_value=mock_resp):
            from nanobot.cli.auth import cmd_auth
            with pytest.raises(SystemExit):
                cmd_auth(auth_key="nb_badkey", server_url="http://localhost:9999")

    def test_server_unreachable(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        with patch("nanobot.auth._auth_file_path", return_value=auth_file), \
             patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            from nanobot.cli.auth import cmd_auth
            with pytest.raises(SystemExit):
                cmd_auth(auth_key="nb_test", server_url="http://localhost:9999")
