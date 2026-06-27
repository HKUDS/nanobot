import hashlib
import hmac
import json

import pytest
from pydantic_core import ValidationError

from nanobot.bus.queue import MessageBus
from nanobot.config.schema import WebhookRouteConfig, WebhooksConfig
from nanobot.webhooks import WebhookRouter


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_generic_webhook_bearer_secret_queues_inbound_message() -> None:
    bus = MessageBus()
    route = WebhookRouteConfig(
        provider="generic",
        secret="topsecret",
        to="telegram:chat-42",
        prompt="Deploy {{ event.service }} from {{ delivery_id }}",
    )
    router = WebhookRouter(WebhooksConfig(routes={"deploy": route}), bus)
    body = b'{"service":"api"}'

    response = await router.handle(
        method="POST",
        path="/webhooks/deploy",
        headers={
            "Authorization": "Bearer topsecret",
            "X-Nanobot-Delivery": "delivery-1",
        },
        body=body,
        remote="127.0.0.1",
    )

    assert response is not None
    assert response.status == 202
    assert response.body["queued"] is True
    msg = await bus.consume_inbound()
    assert msg.channel == "telegram"
    assert msg.chat_id == "chat-42"
    assert msg.sender_id == "webhook"
    assert msg.session_key_override == "telegram:chat-42"
    assert msg.content == "Deploy api from delivery-1"
    assert "message_id" not in msg.metadata
    assert msg.metadata["webhook"] == {
        "route": "deploy",
        "provider": "generic",
        "event": "",
        "delivery_id": "delivery-1",
        "remote": "127.0.0.1",
    }


@pytest.mark.asyncio
async def test_generic_webhook_rejects_bad_secret_without_queueing() -> None:
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "deploy": WebhookRouteConfig(
                    provider="generic",
                    secret="topsecret",
                    to="telegram:chat-42",
                )
            }
        ),
        bus,
    )

    response = await router.handle(
        method="POST",
        path="/webhooks/deploy",
        headers={"Authorization": "Bearer wrong"},
        body=b"{}",
    )

    assert response is not None
    assert response.status == 401
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_generic_webhook_accepts_hmac_signature() -> None:
    bus = MessageBus()
    body = b'{"kind":"release"}'
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "release": WebhookRouteConfig(
                    provider="generic",
                    secret="topsecret",
                    to="slack:C123",
                )
            }
        ),
        bus,
    )

    response = await router.handle(
        method="POST",
        path="/webhooks/release",
        headers={"X-Nanobot-Signature-256": _sig("topsecret", body)},
        body=body,
    )

    assert response is not None
    assert response.status == 202
    msg = await bus.consume_inbound()
    assert msg.channel == "slack"
    assert "A webhook event arrived." in msg.content
    assert "release" in msg.content
    assert "untrusted external data" in msg.content


@pytest.mark.asyncio
async def test_custom_prompt_is_truncated_after_rendering() -> None:
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "big": WebhookRouteConfig(
                    auth="none",
                    to="websocket:ops",
                    prompt="{{ body }}",
                )
            }
        ),
        bus,
    )
    body = b"a" * 1_048_576

    response = await router.handle(
        method="POST",
        path="/webhooks/big",
        headers={},
        body=body,
    )

    assert response is not None
    assert response.status == 202
    msg = await bus.consume_inbound()
    assert len(msg.content) < len(body)
    assert msg.content.endswith("\n... (truncated)")


@pytest.mark.asyncio
async def test_webhook_without_delivery_id_is_not_deduped() -> None:
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "deploy": WebhookRouteConfig(
                    auth="none",
                    to="telegram:chat-42",
                    prompt="Deploy {{ event.service }}",
                )
            }
        ),
        bus,
    )

    first = await router.handle(
        method="POST",
        path="/webhooks/deploy",
        headers={},
        body=b'{"service":"api"}',
    )
    second = await router.handle(
        method="POST",
        path="/webhooks/deploy",
        headers={},
        body=b'{"service":"worker"}',
    )

    assert first is not None
    assert first.body["queued"] is True
    assert second is not None
    assert second.body["queued"] is True
    assert bus.inbound_size == 2


@pytest.mark.asyncio
async def test_webhook_custom_path_and_thread_template() -> None:
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "deploy": WebhookRouteConfig(
                    auth="none",
                    path="/hooks/deploy",
                    to="websocket:ops",
                    thread="deploy:{{ event.service }}:{{ delivery_id }}",
                    prompt="Deploy {{ event.service }}",
                )
            }
        ),
        bus,
    )

    response = await router.handle(
        method="POST",
        path="/hooks/deploy/",
        headers={"X-Nanobot-Delivery": "delivery-2"},
        body=b'{"service":"api"}',
    )

    assert response is not None
    assert response.status == 202
    msg = await bus.consume_inbound()
    assert msg.channel == "websocket"
    assert msg.chat_id == "ops"
    assert msg.content == "Deploy api"
    assert msg.session_key_override == "deploy:api:delivery-2"


@pytest.mark.asyncio
async def test_webhook_rejects_overlong_thread_template_without_dedupe() -> None:
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "deploy": WebhookRouteConfig(
                    auth="none",
                    to="websocket:ops",
                    thread="deploy:{{ event.thread }}",
                    prompt="Deploy {{ event.service }}",
                )
            }
        ),
        bus,
    )

    failed = await router.handle(
        method="POST",
        path="/webhooks/deploy",
        headers={"X-Nanobot-Delivery": "delivery-3"},
        body=json.dumps({"service": "api", "thread": "x" * 600}).encode(),
    )
    accepted = await router.handle(
        method="POST",
        path="/webhooks/deploy",
        headers={"X-Nanobot-Delivery": "delivery-3"},
        body=json.dumps({"service": "api", "thread": "release"}).encode(),
    )

    assert failed is not None
    assert failed.status == 400
    assert "thread template rendered too long" in failed.body["error"]
    assert accepted is not None
    assert accepted.status == 202
    assert accepted.body["queued"] is True
    assert bus.inbound_size == 1
    msg = await bus.consume_inbound()
    assert msg.session_key_override == "deploy:release"


@pytest.mark.asyncio
async def test_github_webhook_validates_signature_and_dedupes_delivery() -> None:
    bus = MessageBus()
    body = json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": "HKUDS/nanobot"},
            "sender": {"login": "alice"},
            "pull_request": {"title": "Add webhook support"},
        }
    ).encode()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "github": WebhookRouteConfig(
                    provider="github",
                    secret="github-secret",
                    to="discord:repo-events",
                )
            }
        ),
        bus,
    )
    headers = {
        "X-Hub-Signature-256": _sig("github-secret", body),
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "uuid-1",
    }

    first = await router.handle(method="POST", path="/webhooks/github", headers=headers, body=body)
    second = await router.handle(method="POST", path="/webhooks/github", headers=headers, body=body)

    assert first is not None
    assert first.status == 202
    assert first.body["queued"] is True
    assert second is not None
    assert second.status == 202
    assert second.body == {
        "ok": True,
        "queued": False,
        "duplicate": True,
        "route": "github",
        "delivery_id": "uuid-1",
    }
    assert bus.inbound_size == 1
    msg = await bus.consume_inbound()
    assert msg.channel == "discord"
    assert msg.chat_id == "repo-events"
    assert msg.session_key_override == "discord:repo-events"
    assert "Provider: github" in msg.content
    assert "Event: pull_request" in msg.content
    assert "Repository: HKUDS/nanobot" in msg.content
    assert "Pull request: Add webhook support" in msg.content
    assert msg.metadata["webhook"]["event"] == "pull_request"


@pytest.mark.asyncio
async def test_github_webhook_event_and_action_filters_ignore_unmatched_events() -> None:
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "github": WebhookRouteConfig(
                    provider="github",
                    secret="github-secret",
                    to="discord:repo-events",
                    events=["pull_request"],
                    actions=["opened", "synchronize"],
                )
            }
        ),
        bus,
    )

    async def send(payload: dict[str, object], event: str, delivery: str):
        body = json.dumps(payload).encode()
        return await router.handle(
            method="POST",
            path="/webhooks/github",
            headers={
                "X-Hub-Signature-256": _sig("github-secret", body),
                "X-GitHub-Event": event,
                "X-GitHub-Delivery": delivery,
            },
            body=body,
        )

    ping = await send({"zen": "Keep it logically awesome."}, "ping", "ping-1")
    closed = await send(
        {
            "action": "closed",
            "repository": {"full_name": "HKUDS/nanobot"},
            "pull_request": {"title": "Add webhook support"},
        },
        "pull_request",
        "pr-closed-1",
    )
    opened = await send(
        {
            "action": "opened",
            "repository": {"full_name": "HKUDS/nanobot"},
            "pull_request": {"title": "Add webhook support"},
        },
        "pull_request",
        "pr-opened-1",
    )

    assert ping is not None
    assert ping.status == 202
    assert ping.body["queued"] is False
    assert ping.body["ignored"] is True
    assert ping.body["event"] == "ping"
    assert closed is not None
    assert closed.status == 202
    assert closed.body["queued"] is False
    assert closed.body["ignored"] is True
    assert closed.body["action"] == "closed"
    assert opened is not None
    assert opened.status == 202
    assert opened.body["queued"] is True
    assert bus.inbound_size == 1
    msg = await bus.consume_inbound()
    assert "Event: pull_request" in msg.content
    assert "Action: opened" in msg.content


@pytest.mark.asyncio
async def test_github_webhook_rejects_invalid_signature() -> None:
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "github": WebhookRouteConfig(
                    provider="github",
                    secret="github-secret",
                    to="discord:repo-events",
                )
            }
        ),
        bus,
    )

    response = await router.handle(
        method="POST",
        path="/webhooks/github",
        headers={"X-Hub-Signature-256": "sha256=bad"},
        body=b"{}",
    )

    assert response is not None
    assert response.status == 401
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_template_failure_does_not_enqueue_or_dedupe() -> None:
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "bad": WebhookRouteConfig(
                    provider="generic",
                    secret="topsecret",
                    to="telegram:chat-42",
                    prompt="{{ missing.call() }}",
                )
            }
        ),
        bus,
    )

    response = await router.handle(
        method="POST",
        path="/webhooks/bad",
        headers={
            "Authorization": "Bearer topsecret",
            "X-Nanobot-Delivery": "delivery-1",
        },
        body=b"{}",
    )

    assert response is not None
    assert response.status == 400
    assert "template failed" in response.body["error"]
    assert bus.inbound_size == 0


def test_webhook_config_rejects_duplicate_paths() -> None:
    with pytest.raises(ValidationError, match="share path"):
        WebhooksConfig(
            routes={
                "one": WebhookRouteConfig(auth="none", to="telegram:1", path="/hook"),
                "two": WebhookRouteConfig(auth="none", to="telegram:2", path="/hook/"),
            }
        )


def test_webhook_config_rejects_health_path() -> None:
    with pytest.raises(ValidationError, match="/health"):
        WebhooksConfig(
            routes={
                "health": WebhookRouteConfig(auth="none", to="telegram:1", path="/health")
            }
        )


def test_webhook_config_requires_target_for_enabled_routes() -> None:
    with pytest.raises(ValidationError, match="channel:chat"):
        WebhooksConfig(routes={"bad": WebhookRouteConfig(auth="none", to="telegram")})


def test_webhook_router_rejects_unregistered_provider() -> None:
    config = WebhooksConfig(
        routes={
            "stripe": WebhookRouteConfig(
                provider="stripe",
                auth="none",
                to="telegram:1",
            )
        }
    )

    with pytest.raises(ValueError, match="not registered"):
        WebhookRouter(config, MessageBus())


def test_webhook_config_allows_incomplete_routes_when_webhooks_disabled() -> None:
    config = WebhooksConfig(
        enabled=False,
        routes={"draft": WebhookRouteConfig(secret="", to="")},
    )

    assert config.enabled is False
