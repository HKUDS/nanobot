"""Provider-local proxies cover inference, credentials, catalogs, and transcription."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from nanobot.config.schema import Config
from nanobot.providers import github_copilot_oauth, github_copilot_provider
from nanobot.providers import transcription as stt
from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider, _AzureTokenProvider
from nanobot.providers.factory import make_provider, validate_provider_setup

PROXY = "http://configured.proxy:8080"


@pytest.mark.parametrize("name,module,cls,model", [
    ("anthropic", "anthropic_provider", "AnthropicProvider", "claude-sonnet-4-6"),
    ("azure_openai", "azure_openai_provider", "AzureOpenAIProvider", "gpt-4o"),
    ("bedrock", "bedrock_provider", "BedrockProvider", "bedrock/model"),
    ("github_copilot", "github_copilot_provider", "GitHubCopilotProvider", "github-copilot/gpt-4.1"),
])
def test_factory_accepts_and_forwards_proxy(monkeypatch, name, module, cls, model):
    constructor = MagicMock()
    monkeypatch.setattr(f"nanobot.providers.{module}.{cls}", constructor)
    config = Config.model_validate({
        "agents": {"defaults": {"model": model, "provider": name}},
        "providers": {name: {"apiKey": "test-key", "apiBase": "https://api.example", "proxy": PROXY}},
    })
    validate_provider_setup(config)
    make_provider(config)
    assert constructor.call_args.kwargs["proxy"] == PROXY


@pytest.mark.parametrize("cls,kwargs", [
    (AnthropicProvider, {}),
    (AzureOpenAIProvider, {"api_base": "https://azure.example"}),
])
@pytest.mark.parametrize("proxy", [None, PROXY])
async def test_native_sdk_proxy_and_default_transport(monkeypatch, cls, kwargs, proxy):
    monkeypatch.setenv("HTTPS_PROXY", "http://environment.proxy:9999")
    monkeypatch.setenv("NO_PROXY", "*")
    before = dict(os.environ)
    provider = cls(api_key="test-key", proxy=proxy, **kwargs)
    client = provider._client._client
    try:
        assert client._trust_env is (not bool(proxy))
        if proxy:
            # Assert the actual SDK client has proxy transports, not just constructor kwargs.
            pools = [transport._pool for transport in client._mounts.values() if transport]
            assert pools
            assert all(pool._proxy_url.host == b"configured.proxy" for pool in pools)
        assert dict(os.environ) == before
    finally:
        await provider._client.close()


def test_azure_aad_proxy_reaches_credential_transport(monkeypatch):
    pytest.importorskip("azure.identity.aio")
    pytest.importorskip("aiohttp")
    credential = MagicMock()
    transport = MagicMock()
    monkeypatch.setattr("azure.identity.aio.DefaultAzureCredential", credential)
    monkeypatch.setattr("azure.core.pipeline.transport.AioHttpTransport", transport)
    _AzureTokenProvider(proxy=PROXY)
    transport.assert_called_once_with(use_env_settings=False)
    credential.assert_called_once_with(
        proxies={"http": PROXY, "https": PROXY}, transport=transport.return_value,
    )


async def test_azure_aad_real_pipeline_has_proxy_policy(monkeypatch):
    pytest.importorskip("azure.identity.aio")
    pytest.importorskip("aiohttp")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "secret")
    token_provider = _AzureTokenProvider(proxy=PROXY)
    try:
        # DefaultAzureCredential's first member is EnvironmentCredential. Inspect its
        # actual AAD pipeline without retrieving credentials or making network calls.
        pipeline = token_provider._credential.credentials[0]._credential._client._pipeline
        assert pipeline._transport._use_env_settings is False
        policies = [getattr(runner, "_policy", runner) for runner in pipeline._impl_policies]
        assert any(getattr(policy, "proxies", None) == {
            "http": PROXY, "https": PROXY,
        } for policy in policies)
    finally:
        await token_provider.aclose()


@pytest.mark.parametrize("proxy", [None, PROXY])
def test_bedrock_transport_and_bearer_are_session_local(monkeypatch, proxy):
    pytest.importorskip("boto3")
    from nanobot.providers.bedrock_provider import BedrockProvider

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "environment-token")
    monkeypatch.setenv("HTTPS_PROXY", "http://environment.proxy:9999")
    before = dict(os.environ)
    first = BedrockProvider(api_key="first-token", region="us-east-1", proxy=proxy)
    second = BedrockProvider(api_key="second-token", region="us-east-1", proxy=proxy)
    try:
        assert dict(os.environ) == before
        assert first._client._request_signer._auth_token.token == "first-token"
        assert second._client._request_signer._auth_token.token == "second-token"
        assert first._client.meta.config.proxies == (
            {"http": PROXY, "https": PROXY} if proxy else None
        )
    finally:
        first._client.close()
        second._client.close()


@pytest.mark.parametrize("proxy", [None, PROXY])
async def test_copilot_refresh_and_inference_use_same_proxy(monkeypatch, proxy):
    from openai import AsyncOpenAI

    from nanobot.providers import openai_compat_provider
    original = httpx.AsyncClient
    captured = []
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"token": "copilot-secret", "refresh_in": 1500})
        return httpx.Response(200, json={
            "id": "response", "choices": [{"message": {"role": "assistant", "content": "ok"},
                                            "finish_reason": "stop", "index": 0}],
        })

    class Client(original):
        def __init__(self, **kwargs):
            captured.append(kwargs)
            super().__init__(transport=httpx.MockTransport(handler), trust_env=False)

    def sdk(**kwargs):
        # The unset case uses the SDK default client; intercept it to keep the test offline.
        if kwargs.get("http_client") is None:
            kwargs["http_client"] = Client()
        return AsyncOpenAI(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(openai_compat_provider, "AsyncOpenAI", sdk)
    monkeypatch.setattr(github_copilot_provider, "_load_github_token",
                        lambda: SimpleNamespace(access="github-secret"))
    provider = github_copilot_provider.GitHubCopilotProvider(proxy=proxy)
    try:
        response = await provider.chat([{"role": "user", "content": "hello"}])
        assert response.content == "ok"
        assert requests[0].headers["Authorization"] == "token github-secret"
        assert requests[1].headers["Authorization"] == "Bearer copilot-secret"
        assert captured[0]["proxy"] == proxy
        assert captured[0]["trust_env"] is (not bool(proxy))
        if proxy:
            assert captured[1]["proxy"] == proxy
            assert captured[1]["trust_env"] is False
    finally:
        if provider._client is not None:
            await provider._client.close()


@pytest.mark.parametrize("proxy", [None, PROXY])
def test_copilot_device_login_and_catalog_proxy(monkeypatch, proxy):
    original = httpx.Client
    captured = []
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/device/code"):
            payload = {"device_code": "code", "user_code": "display-code", "expires_in": 60,
                       "verification_uri": "https://github.com/login/device", "interval": 1}
        elif request.url.path.endswith("/access_token"):
            payload = {"access_token": "github-token"}
        elif request.url.path.endswith("/user"):
            payload = {"login": "account"}
        elif request.url.path.endswith("/token"):
            payload = {"token": "copilot-token"}
        else:
            payload = {"data": []}
        return httpx.Response(200, json=payload)

    def client(**kwargs):
        captured.append(kwargs)
        return original(transport=httpx.MockTransport(handler), trust_env=False)

    monkeypatch.setattr(httpx, "Client", client)
    token = github_copilot_provider.login_github_copilot(
        proxy=proxy, open_browser=False, persist=False, print_fn=lambda _: None,
    )
    monkeypatch.setattr(github_copilot_provider, "get_storage",
                        lambda: SimpleNamespace(load=lambda: token))
    github_copilot_provider._fetch_github_copilot_models(proxy)
    assert len(paths) == 5  # Device prompt, approval poll, user lookup, exchange, model catalog.
    for kwargs in captured:
        if proxy:
            assert kwargs["proxy"] == proxy
            assert kwargs["trust_env"] is False
        else:
            assert kwargs.get("trust_env", True) is True


def test_copilot_gateway_flow_passes_proxy_to_login(monkeypatch):
    login = MagicMock(return_value=SimpleNamespace(access="token"))
    monkeypatch.setattr(github_copilot_oauth, "login_github_copilot", login)
    flow = github_copilot_oauth.GitHubCopilotOAuthFlow(proxy=PROXY)
    flow._run()
    assert login.call_args.kwargs["proxy"] == PROXY
    assert login.call_args.kwargs["persist"] is False


@pytest.mark.parametrize("cls", [
    stt.AssemblyAITranscriptionProvider, stt.OpenAITranscriptionProvider,
    stt.GroqTranscriptionProvider, stt.OpenRouterTranscriptionProvider,
    stt.XiaomiMiMoTranscriptionProvider, stt.StepFunTranscriptionProvider,
])
@pytest.mark.parametrize("proxy", [None, PROXY])
async def test_all_transcription_transports_use_configured_proxy(monkeypatch, tmp_path, cls, proxy):
    original = httpx.AsyncClient
    captured = []
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/upload"):
            return httpx.Response(200, json={"upload_url": "https://cdn.example/audio"})
        if request.url.path.endswith("/transcript/transcript"):
            return httpx.Response(200, json={"status": "completed", "text": "recognized"})
        if request.url.path.endswith("/transcript"):
            return httpx.Response(200, json={"id": "transcript"})
        if request.url.path.endswith("/sse"):
            return httpx.Response(200, text='data: {"type":"transcript.text.done","text":"recognized"}\n\n')
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "recognized"}}]})
        return httpx.Response(200, json={"text": "recognized"})

    def client(**kwargs):
        captured.append(kwargs)
        return original(transport=httpx.MockTransport(handler), trust_env=False)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    provider = cls(api_key="key", proxy=proxy)
    assert await provider.transcribe(audio) == "recognized"
    assert requests
    assert captured == ([{"proxy": proxy, "trust_env": False}] if proxy else [{}])
