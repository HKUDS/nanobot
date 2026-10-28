"""Setup contract and validation ownership for the Agent Platform channel."""

from __future__ import annotations

import httpx
import pytest

from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.plugin import load_channel_package
from nanobot.channels.whatsapp_agent.validation import validate

_CONTEXT = ChannelValidationContext(allow_local_service_access=False)


def test_manifest_and_setup_contract_match_the_runtime_fields():
    plugin = load_channel_package("whatsapp_agent")

    assert plugin is not None
    assert plugin.name == "whatsapp_agent"
    assert plugin.display_name == "WhatsApp Agent Platform"
    assert plugin.runtime == "nanobot.channels.whatsapp_agent.runtime:WhatsAppAgentChannel"
    # No optional platform SDK: the API is plain HTTPS.
    assert plugin.dependencies == ()
    assert plugin.default_enabled is False
    assert plugin.setup is not None
    assert plugin.setup.simple_required_fields == ("token",)


def test_token_is_a_secret_and_setup_does_not_require_a_second_step():
    spec = channel_setup_spec("whatsapp_agent")

    assert spec is not None
    assert spec.secrets == {"token"}
    assert spec.route_field_types["token"] == "secret"
    # There is no QR or terminal login step; the token alone completes setup.
    assert spec.is_configured({"token": "abc"}) is True
    assert spec.is_configured({"token": ""}) is False


def test_public_contract_exposes_every_writable_field_only_once():
    spec = channel_setup_spec("whatsapp_agent")

    assert spec is not None
    public = spec.to_public_dict("whatsapp_agent")
    fields = [field["field"] for field in public["fields"]]

    assert fields == list(spec.fields)
    assert "token" in fields
    assert public["verifies_connection"] is True
    assert public["official_url"].startswith("https://faq.whatsapp.com/")


def test_progress_defaults_are_off_in_the_setup_contract():
    spec = channel_setup_spec("whatsapp_agent")

    assert spec is not None
    # Progress traffic spends the shared 12-per-minute send budget.
    assert spec.fields["sendProgress"].default is False
    assert spec.fields["sendToolHints"].default is False
    assert spec.fields["retryAmbiguousSends"].default is False


def test_missing_token_reports_needs_setup():
    payload = validate({}, _CONTEXT)

    assert payload["status"] == "needs_setup"
    assert payload["can_enable"] is False
    assert "token" in payload["missing_fields"]


def test_valid_token_is_reported_as_connected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(204))

    payload = validate({"token": "abc"}, _CONTEXT)

    assert payload["status"] == "connected"
    assert payload["can_enable"] is True


def test_invalid_token_uses_the_400_code_100_contract(monkeypatch: pytest.MonkeyPatch):
    response = httpx.Response(400, json={"error": {"code": 100}})
    monkeypatch.setattr(httpx, "get", lambda *a, **k: response)

    payload = validate({"token": "abc"}, _CONTEXT)

    assert payload["status"] == "invalid"
    assert payload["can_enable"] is False


def test_missing_authorization_header_is_reported(monkeypatch: pytest.MonkeyPatch):
    response = httpx.Response(401, json={"error": {"code": 190}})
    monkeypatch.setattr(httpx, "get", lambda *a, **k: response)

    payload = validate({"token": "abc"}, _CONTEXT)

    assert payload["status"] == "invalid"


def test_duplicate_poller_is_valid_but_warned(monkeypatch: pytest.MonkeyPatch):
    response = httpx.Response(409, json={"error": {"code": 1752041}})
    monkeypatch.setattr(httpx, "get", lambda *a, **k: response)

    payload = validate({"token": "abc"}, _CONTEXT)

    assert payload["status"] == "connected"
    assert payload["can_enable"] is True


def test_network_failure_warns_without_invalidating_the_token(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", fail)

    payload = validate({"token": "abc"}, _CONTEXT)

    assert payload["status"] == "configured"
    assert payload["can_enable"] is True
