"""Tests for redaction guard."""

import pytest
from pathlib import Path

from nanobot.agent.tools.redaction import (
    is_sensitive_path,
    redact_content,
    redact_messages,
    redact_text,
)


class TestSensitivePath:
    """Tests for is_sensitive_path function."""

    def test_env_files(self):
        """Test .env file detection."""
        assert is_sensitive_path(Path(".env")) is True
        assert is_sensitive_path(Path(".env.local")) is True
        assert is_sensitive_path(Path(".env.production")) is True

    def test_auth_files(self):
        """Test auth file detection."""
        assert is_sensitive_path(Path("auth.json")) is True
        assert is_sensitive_path(Path("oauth.json")) is True

    def test_ssh_keys(self):
        """Test SSH key detection."""
        assert is_sensitive_path(Path("id_rsa")) is True
        assert is_sensitive_path(Path("id_rsa.pub")) is True
        assert is_sensitive_path(Path("id_ed25519")) is True
        assert is_sensitive_path(Path("id_ed25519.pub")) is True

    def test_certificate_files(self):
        """Test certificate file detection."""
        assert is_sensitive_path(Path("server.pem")) is True
        assert is_sensitive_path(Path("client.p12")) is True
        assert is_sensitive_path(Path("keystore.pfx")) is True
        assert is_sensitive_path(Path("truststore.jks")) is True
        assert is_sensitive_path(Path("private.key")) is True

        # Backup files with sensitive extensions (SHOULD be blocked)
        assert is_sensitive_path(Path("server.pem.bak")) is True
        assert is_sensitive_path(Path("client.p12.old")) is True
        assert is_sensitive_path(Path("keystore.pfx.tmp")) is True
        assert is_sensitive_path(Path("private.key.backup")) is True
        assert is_sensitive_path(Path("cert.pem.save")) is True

        # Non-sensitive backups (should NOT be blocked)
        assert is_sensitive_path(Path("normal.txt.bak")) is False
        assert is_sensitive_path(Path("config.json.old")) is False

    def test_secret_files(self):
        """Test secrets/credentials file detection."""
        assert is_sensitive_path(Path("secrets.json")) is True
        assert is_sensitive_path(Path("secrets.yaml")) is True
        assert is_sensitive_path(Path("secrets.yml")) is True
        assert is_sensitive_path(Path("secrets.toml")) is True
        assert is_sensitive_path(Path("secrets.ini")) is True
        assert is_sensitive_path(Path("credentials.json")) is True
        assert is_sensitive_path(Path("credentials.yaml")) is True
        assert is_sensitive_path(Path(".secrets")) is True

    def test_paths_with_directories(self):
        """Test paths with directory prefixes."""
        assert is_sensitive_path(Path("/home/user/.env")) is True
        assert is_sensitive_path(Path("C:/Users/me/.env.local")) is True
        assert is_sensitive_path(Path("./config/.env")) is True
        assert is_sensitive_path(Path("/project/secrets.json")) is True

    def test_non_sensitive_files(self):
        """Test that normal files are not blocked."""
        assert is_sensitive_path(Path("src/app.py")) is False
        assert is_sensitive_path(Path("README.md")) is False
        assert is_sensitive_path(Path("package.json")) is False
        assert is_sensitive_path(Path("config/app.yaml")) is False
        assert is_sensitive_path(Path("data/credentials_sample.json")) is False

    def test_path_traversal_attacks(self):
        """Test that path traversal attacks are blocked."""
        assert is_sensitive_path(Path("../.env")) is True
        assert is_sensitive_path(Path("../../.env")) is True
        assert is_sensitive_path(Path("subdir/../.env")) is True
        assert is_sensitive_path(Path("./subdir/../.env")) is True

    def test_path_objects(self):
        """Test that Path objects work correctly."""
        assert is_sensitive_path(Path(".env")) is True
        assert is_sensitive_path(Path("../.env")) is True
        assert is_sensitive_path(Path("subdir/../secrets.json")) is True
        assert is_sensitive_path(Path("../auth.json")) is True
        assert is_sensitive_path(Path("/project/config/.env")) is True

    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive."""
        assert is_sensitive_path(Path(".ENV")) is True
        assert is_sensitive_path(Path(".Env.Local")) is True
        assert is_sensitive_path(Path("AUTH.JSON")) is True
        assert is_sensitive_path(Path("Server.PEM")) is True

    def test_empty_and_invalid_inputs(self):
        """Test empty and invalid inputs."""
        assert is_sensitive_path(Path("")) is False

    def test_complex_extensions(self):
        """Test files with backup extensions."""
        # Sensitive files are blocked
        assert is_sensitive_path(Path("file.pem")) is True
        assert is_sensitive_path(Path("file.key")) is True

        # Backup files with sensitive extensions are ALSO blocked
        assert is_sensitive_path(Path("file.pem.bak")) is True
        assert is_sensitive_path(Path("file.key.old")) is True
        assert is_sensitive_path(Path("cert.p12.tmp")) is True

        # Non-sensitive files and their backups are allowed
        assert is_sensitive_path(Path("file.txt")) is False
        assert is_sensitive_path(Path("file.txt.bak")) is False
        assert is_sensitive_path(Path("file.json")) is False
        assert is_sensitive_path(Path("file.json.old")) is False


class TestRedactText:
    """Tests for redact_text function."""

    def test_openai_api_key(self):
        """Test OpenAI API key redaction.

        The improved pattern requires sk-(proj-)? followed by at least 32 chars
        to reduce false positives.
        """
        # Direct sk- key format (34 chars - should be redacted)
        text = "My key is sk-1234567890abcdefghijklmnopqrstuv"
        result = redact_text(text)
        assert "sk-***" in result
        assert "sk-1234567890abcdefghijklmnopqrstuv" not in result

        # Key in middle of string with text after
        text2 = "Use key sk-1234567890abcdefghijklmnopqrstuv for production"
        result2 = redact_text(text2)
        assert "sk-***" in result2
        assert "for production" in result2  # Text after key preserved
        assert "sk-1234567890abcdefghijklmnopqrstuv" not in result2

        # Key followed by punctuation
        text3 = "API key: sk-1234567890abcdefghijklmnopqrstuv."
        result3 = redact_text(text3)
        assert "sk-***" in result3
        assert "sk-1234567890abcdefghijklmnopqrstuv" not in result3

        # Multiple keys in one string
        text4 = "Key1: sk-1234567890abcdefghijklmnopqrstuv and Key2: sk-9876543210zyxwvutsrqponmlkjihgfe"
        result4 = redact_text(text4)
        assert "sk-***" in result4
        # Both keys should be redacted
        assert "sk-1234567890abcdefghijklmnopqrstuv" not in result4
        assert "sk-9876543210zyxwvutsrqponmlkjihgfe" not in result4

        # Project keys (should be redacted)
        text5 = "Key: sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"
        result5 = redact_text(text5)
        assert "sk-***" in result5

        # Key in URL parameter (caught by api_key_kv pattern)
        text6 = "https://api.openai.com?key=sk-1234567890abcdefghijklmnopqrstuv&model=gpt-4"
        result6 = redact_text(text6)
        assert "***" in result6
        assert "sk-1234567890abcdefghijklmnopqrstuv" not in result6

        # Key in JSON format
        text7 = '{"api_key": "sk-1234567890abcdefghijklmnopqrstuv", "model": "gpt-4"}'
        result7 = redact_text(text7)
        assert '"api_key": "sk-***"' in result7
        assert "sk-1234567890abcdefghijklmnopqrstuv" not in result7

        # Too short (should NOT be redacted) - 27 chars
        text8 = "My short key sk-short12345678901234567"
        result8 = redact_text(text8)
        assert "sk-short12345678901234567" in result8  # Not redacted

    def test_github_pat(self):
        """Test GitHub PAT redaction."""
        text = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = redact_text(text)
        assert "gh***" in result
        assert "xxxxxxxxxxxxxxxxxxxxxxxx" not in result

        # GitHub PAT in middle of string
        text2 = "Use token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx for authentication"
        result2 = redact_text(text2)
        assert "gh***" in result2
        assert "for authentication" in result2  # Text after token preserved
        assert "xxxxxxxxxxxxxxxxxxxxxxxx" not in result2

    def test_slack_token(self):
        """Test Slack token redaction."""
        text = "xoxb-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = redact_text(text)
        assert "xox***" in result

        # Slack token in middle of sentence
        text2 = "Install with xoxb-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx and configure"
        result2 = redact_text(text2)
        assert "xox***" in result2
        assert "and configure" in result2  # Text after token preserved

    def test_bearer_token(self):
        """Test Bearer token redaction.

        The improved pattern requires at least 20 chars to reduce false positives.
        """
        # Valid bearer token (should be redacted)
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
        result = redact_text(text)
        assert "Bearer ***" in result
        assert "eyJ" not in result

        # Bearer token in middle of sentence
        text2 = "Send request with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 and check response"
        result2 = redact_text(text2)
        assert "Bearer ***" in result2
        assert "and check response" in result2  # Text after token preserved
        assert "eyJ" not in result2

        # Bearer token followed by comma
        text3 = 'Headers: {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"},'
        result3 = redact_text(text3)
        assert "Bearer ***" in result3
        assert "eyJ" not in result3

        # Too short (should NOT be redacted)
        text4 = "Bearer: shorttoken"
        result4 = redact_text(text4)
        assert "shorttoken" in result4  # Not redacted

    def test_api_key_kv(self):
        """Test API key key-value redaction.

        The improved pattern requires at least 8 chars to reduce false positives.
        """
        # Long key (should be redacted)
        text = 'api_key: "sk-abcdef1234567890"'
        result = redact_text(text)
        assert "api_key***" in result  # Non-JSON format: separator removed
        assert "sk-abcdef1234567890" not in result

        # JSON format (SHOULD be redacted - this is the fix)
        text2 = '"api_key": "sk-abcdef1234567890"'
        result2 = redact_text(text2)
        assert '"api_key": "***"' in result2  # JSON format: preserved
        assert "sk-abcdef1234567890" not in result2

        # Short value (should NOT be redacted)
        text3 = "api_key=x"
        result3 = redact_text(text3)
        assert "api_key=x" in result3  # Not redacted

        # Medium value (should be redacted, 8+ chars)
        text4 = "api_key=12345678"
        result4 = redact_text(text4)
        assert "api_key***" in result4  # Non-JSON: separator removed
        assert "12345678" not in result4

    def test_password_kv(self):
        """Test password key-value redaction."""
        text = 'password: "mypassword123"'
        result = redact_text(text)
        assert "password***" in result  # Non-JSON format
        assert "mypassword123" not in result

        # JSON format (SHOULD be redacted)
        text2 = '"password": "mypassword123"'
        result2 = redact_text(text2)
        assert '"password": "***"' in result2  # JSON format: preserved
        assert "mypassword123" not in result2

    def test_token_kv(self):
        """Test token key-value redaction."""
        text = "access_token=abc123xyz789"
        result = redact_text(text)
        assert "***" in result
        assert "abc123xyz789" not in result

    def test_secret_kv(self):
        """Test secret key-value redaction."""
        text = 'client_secret="supersecretvalue"'
        result = redact_text(text)
        assert "***" in result
        assert "supersecretvalue" not in result

    def test_private_key(self):
        """Test private key redaction.

        The pattern has a length limit ({1,10000}) to prevent DoS attacks
        on large files with incomplete key blocks.
        """
        # Normal private key (should be redacted)
        text = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj
-----END PRIVATE KEY-----"""
        result = redact_text(text)
        assert "[REDACTED_PRIVATE_KEY]" in result
        assert "PRIVATE KEY" not in result

    def test_multiple_secrets(self):
        """Test text with multiple secrets."""
        text = """
        api_key=sk-1234567890abcdefghijklmnop
        password: mysecretpassword
        Bearer eyJhbGciOiJIUzI1NiJ9
        """
        result = redact_text(text)
        # api_key=sk-xxx caught by api_key_kv -> api_key*** (separator removed)
        assert "api_key***" in result
        assert "password***" in result
        assert "Bearer ***" in result
        # Make sure the actual secrets are gone
        assert "sk-1234567890" not in result
        assert "mysecretpassword" not in result
        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    def test_no_sensitive_data(self):
        """Test text without sensitive data."""
        text = "This is a normal text with no secrets."
        result = redact_text(text)
        assert result == text

    def test_idempotent(self):
        """Test that redaction is idempotent."""
        text = "My API key is sk-1234567890abcdefghijklmnopqrstuv"
        result1 = redact_text(text)
        result2 = redact_text(result1)
        assert result1 == result2
        assert "sk-***" in result1

    def test_already_redacted(self):
        """Test that already redacted text is not modified again."""
        text = "My key is sk-***"
        result = redact_text(text)
        assert result == "My key is sk-***"

        text2 = "api_key=***"
        result2 = redact_text(text2)
        assert result2 == "api_key=***"

    def test_empty_string(self):
        """Test empty string handling."""
        assert redact_text("") == ""
        assert redact_text("   ") == "   "

    def test_non_string(self):
        """Test non-string input handling."""
        assert redact_text(123) == 123
        assert redact_text(None) is None

    def test_json_format_key_value(self):
        """Test JSON format key-value redaction.

        This tests the fix for the security issue where JSON format
        key-value pairs like "apiKey": "xxx" were not being redacted.
        """
        # JSON double quotes format (SHOULD be redacted)
        text = '"apiKey": "7b131231jefjajfas"'
        result = redact_text(text)
        assert '"apiKey": "***"' in result
        assert "7b131231jefjajfas" not in result

        # JSON in object context
        text2 = '{"apiKey": "7b131231jefjajfas", "apiBase": "https://api.z.ai/api/coding/paas/v4/"}'
        result2 = redact_text(text2)
        assert '"apiKey": "***"' in result2
        assert "7b131231jefjajfas" not in result2

        # JSON with indentation (from cat auth.json)
        text3 = '''{
  "apiKey": "7b131231jefjajfas",
  "apiBase": "https://api.z.ai/api/coding/paas/v4/"
}'''
        result3 = redact_text(text3)
        assert '"apiKey": "***"' in result3
        assert "7b131231jefjajfas" not in result3
        assert "apiBase" in result3  # Other keys preserved
        assert "https://api.z.ai" in result3  # URLs preserved

        # Password in JSON format
        text4 = '"password": "mypassword123"'
        result4 = redact_text(text4)
        assert '"password": "***"' in result4
        assert "mypassword123" not in result4

        # Token in JSON format
        text5 = '"access_token": "abc123def456"'
        result5 = redact_text(text5)
        assert '"access_token": "***"' in result5
        assert "abc123def456" not in result5

        # Secret in JSON format
        text6 = '"client_secret": "supersecretvalue"'
        result6 = redact_text(text6)
        assert '"client_secret": "***"' in result6
        assert "supersecretvalue" not in result6

        # Mixed: JSON and non-JSON formats
        text7 = 'apiKey=12345678 AND "apiKey": "yyy12345678"'
        result7 = redact_text(text7)
        assert "apiKey***" in result7  # Non-JSON: separator removed
        assert '"apiKey": "***"' in result7  # JSON: format preserved

        # Real-world auth.json example (bash cat output)
        text8 = '''     "apiKey": "7b131231jefjajfas",
       "apiBase": "https://api.z.ai/api/coding/paas/v4/"'''
        result8 = redact_text(text8)
        assert '"apiKey": "***"' in result8
        assert "7b131231jefjajfas" not in result8
        assert "https://api.z.ai" in result8  # URL preserved


class TestRedactContent:
    """Tests for redact_content function."""

    def test_string_content(self):
        """Test string content redaction."""
        text = "My key is sk-1234567890abcdefghijklmnopqrstuv"
        result = redact_content(text)
        assert "sk-***" in result

    def test_list_content(self):
        """Test list of content blocks redaction."""
        content = [
            {"type": "text", "text": "My key is sk-1234567890abcdefghijklmnopqrstuv"},
            {"type": "text", "text": "This is normal text"},
        ]
        result = redact_content(content)
        assert isinstance(result, list)
        assert result[0]["text"] == "My key is sk-***"
        assert result[1]["text"] == "This is normal text"

    def test_mixed_content(self):
        """Test mixed content (non-text items)."""
        content = [
            {"type": "text", "text": "Key: sk-1234567890abcdefghijklmnopqrstuv"},
            {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
        ]
        result = redact_content(content)
        assert result[0]["text"] == "Key: sk-***"
        # Non-text items should be preserved
        assert result[1]["type"] == "image_url"


class TestRedactMessages:
    """Tests for redact_messages function."""

    def test_redact_history(self):
        """Test message history redaction."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "My API key is sk-1234567890abcdefghijklmnopqrstuv"},
            {"role": "user", "content": "Thanks"},
        ]
        result = redact_messages(messages)
        assert result[1]["content"] == "My API key is sk-***"

    def test_preserve_message_structure(self):
        """Test that message structure is preserved."""
        messages = [
            {"role": "user", "content": "Test", "name": "test_user"},
        ]
        result = redact_messages(messages)
        assert result[0]["role"] == "user"
        assert result[0]["name"] == "test_user"
        assert result[0]["content"] == "Test"

    def test_empty_content(self):
        """Test messages with empty content."""
        messages = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": None},
        ]
        result = redact_messages(messages)
        assert result[0]["content"] == ""
        assert result[1].get("content") is None
