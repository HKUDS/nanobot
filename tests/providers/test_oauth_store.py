"""Tests for OAuthCredentialStore and OAuthCredentials."""
import json
import time
import pytest
from pathlib import Path

from nanobot.providers.oauth_store import OAuthCredentials, OAuthCredentialStore


def test_credentials_is_expired_when_past_expiry():
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-xxx",
        refresh_token="sk-ant-ort01-xxx",
        expires_at_ms=int(time.time() * 1000) - 10_000,
    )
    assert creds.is_expired(margin_ms=0)


def test_credentials_not_expired_when_future():
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-xxx",
        refresh_token="sk-ant-ort01-xxx",
        expires_at_ms=int(time.time() * 1000) + 3_600_000,
    )
    assert not creds.is_expired(margin_ms=0)


def test_credentials_expired_within_margin():
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-xxx",
        refresh_token="sk-ant-ort01-xxx",
        expires_at_ms=int(time.time() * 1000) + 2 * 60 * 1000,
    )
    assert creds.is_expired(margin_ms=5 * 60 * 1000)


def test_store_save_and_load(tmp_path):
    store_path = tmp_path / "oauth_credentials.json"
    store = OAuthCredentialStore(store_path=store_path)
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-abc",
        refresh_token="sk-ant-ort01-xyz",
        expires_at_ms=1_000_000_000_000,
    )
    store.save(creds)
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "sk-ant-oat01-abc"
    assert loaded.refresh_token == "sk-ant-ort01-xyz"
    assert loaded.expires_at_ms == 1_000_000_000_000


def test_store_load_returns_none_when_missing(tmp_path):
    store = OAuthCredentialStore(
        store_path=tmp_path / "nonexistent.json",
        claude_cli_creds_path=tmp_path / "also_nonexistent.json",
    )
    assert store.load() is None


def test_store_load_from_claude_cli(tmp_path):
    cli_creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-cli",
            "refreshToken": "sk-ant-ort01-cli",
            "expiresAt": 1_800_000_000_000,
        }
    }
    cli_path = tmp_path / ".credentials.json"
    cli_path.write_text(json.dumps(cli_creds))
    store = OAuthCredentialStore(
        store_path=tmp_path / "nonexistent.json",
        claude_cli_creds_path=cli_path,
    )
    creds = store.load()
    assert creds is not None
    assert creds.access_token == "sk-ant-oat01-cli"
    assert creds.refresh_token == "sk-ant-ort01-cli"
    assert creds.expires_at_ms == 1_800_000_000_000


def test_store_nanobot_file_takes_precedence_over_cli(tmp_path):
    store_path = tmp_path / "oauth_credentials.json"
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-nanobot",
        refresh_token="sk-ant-ort01-nanobot",
        expires_at_ms=1_900_000_000_000,
    )
    store = OAuthCredentialStore(store_path=store_path)
    store.save(creds)

    cli_creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-cli",
            "refreshToken": "sk-ant-ort01-cli",
            "expiresAt": 1_800_000_000_000,
        }
    }
    cli_path = tmp_path / ".credentials.json"
    cli_path.write_text(json.dumps(cli_creds))

    store2 = OAuthCredentialStore(store_path=store_path, claude_cli_creds_path=cli_path)
    loaded = store2.load()
    assert loaded.access_token == "sk-ant-oat01-nanobot"
