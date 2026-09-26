from __future__ import annotations

import json

import httpx
import pytest

from nanobot.utils.jev import (
    ChoiceQuestion,
    JevClient,
    JevHttpError,
    JevIncompleteResponseError,
    JevMalformedJsonError,
    JevMissingCredentialsError,
    JevProtocolError,
    JevTimeoutError,
    JevTransportError,
    NoulQuestion,
    ScoreQuestion,
)


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


@pytest.mark.asyncio
async def test_noul_decide_parses_successful_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://openrouter.ai/api/alpha/decisions"
        assert request.headers["Authorization"] == "Bearer sk-test"
        assert request.headers["Content-Type"] == "application/json"
        payload = json.loads(request.content.decode())
        assert payload["model"] == "typesafe/jev-1.13"
        assert payload["state"] == "Task: deploy\nContext: see logs"
        assert payload["questions"]["safe_to_run"]["type"] == "noul"
        assert payload["questions"]["safe_to_run"]["criteria"]["true"]
        return httpx.Response(
            200,
            json={
                "id": "gen-dec-1",
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": {"safe_to_run": {"type": "noul", "noul": 0.95}},
                "usage": {"input_tokens": 492, "output_tokens": 22, "cost": 0.000020664},
            },
        )

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-test",
        timeout=15.0,
        transport=_Transport(handler),
    )

    result = await client.decide(
        state="Task: deploy\nContext: see logs",
        questions={
            "safe_to_run": NoulQuestion(
                instructions="Decide if this should notify the user.",
                criteria={"true": "Actionable or failed.", "false": "Routine or empty."},
            )
        },
    )

    assert result.response_id == "gen-dec-1"
    assert result.model == "typesafe/jev-1.13-20260917"
    assert result.provider == "TypeSafe"
    assert result.answers["safe_to_run"].noul == pytest.approx(0.95)
    assert result.usage.input_tokens == 492
    assert result.usage.output_tokens == 22
    assert result.usage.cost == pytest.approx(0.000020664)


@pytest.mark.asyncio
async def test_choice_decide_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "gen-dec-choice",
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": {
                    "team": {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": {"technical": 0.0, "billing": 1.0, "sales": 0.0},
                        "confidence": 0.99,
                    }
                },
                "usage": {"input_tokens": 200, "output_tokens": 20, "cost": 0.00001},
            },
        )

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-choice",
        timeout=15.0,
        transport=_Transport(handler),
    )

    result = await client.decide(
        state="Payout failed.",
        questions={
            "team": ChoiceQuestion(
                instructions="Which team should handle this?",
                criteria={"billing": "Payments", "technical": "Bugs", "sales": "Pricing"},
            )
        },
    )

    answer = result.answers["team"]
    assert answer.choice == "billing"
    assert answer.probabilities["billing"] == pytest.approx(1.0)
    assert answer.confidence == pytest.approx(0.99)


@pytest.mark.asyncio
async def test_score_decide_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "gen-dec-score",
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": {
                    "buying_intent": {
                        "type": "score",
                        "score": 2.97,
                        "legend": {"0": "A", "1": "B", "2": "C", "3": "D"},
                        "probabilities": {"0": 0.0, "1": 0.0, "2": 0.03, "3": 0.97},
                        "confidence": 0.97,
                    }
                },
                "usage": {"input_tokens": 300, "output_tokens": 30, "cost": 0.00002},
            },
        )

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-score",
        timeout=15.0,
        transport=_Transport(handler),
    )

    result = await client.decide(
        state="Pricing for 40 seats",
        questions={
            "buying_intent": ScoreQuestion(
                instructions="How ready is this lead to buy?",
                criteria=["A", "B", "C", "D"],
            )
        },
    )

    answer = result.answers["buying_intent"]
    assert answer.score == pytest.approx(2.97)
    assert answer.legend["2"] == "C"
    assert answer.probabilities["3"] == pytest.approx(0.97)
    assert answer.confidence == pytest.approx(0.97)


@pytest.mark.asyncio
async def test_uses_env_openrouter_key_when_not_explicitly_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer env-key"
        return httpx.Response(
            200,
            json={
                "id": "gen-dec-env",
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": {"safe_to_run": {"type": "noul", "noul": 0.5}},
                "usage": {"input_tokens": 8, "output_tokens": 2, "cost": 0.0},
            },
        )

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key=None,
        timeout=15.0,
        transport=_Transport(handler),
    )

    result = await client.decide(
        state="Task: check",
        questions={
            "safe_to_run": NoulQuestion(
                instructions="Decide if should notify.",
                criteria={"true": "Notify.", "false": "Skip."},
            )
        },
    )

    assert result.provider == "TypeSafe"
    assert result.answers["safe_to_run"].noul == pytest.approx(0.5)


def test_injected_transport_takes_precedence_over_proxy():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "id": "gen-dec-proxy",
        "model": "typesafe/jev-1.13-20260917",
        "provider": "TypeSafe",
        "answers": {"safe_to_run": {"type": "noul", "noul": 0.5}},
        "usage": {"input_tokens": 1, "output_tokens": 1, "cost": 0.0},
    }))

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-test",
        timeout=15.0,
        proxy="http://proxy:8080",
        transport=transport,
    )

    assert client._make_transport() is transport


def test_timeout_must_be_positive():
    with pytest.raises(ValueError):
        JevClient(model="typesafe/jev-1.13", api_key="sk-test", timeout=0.0)


@pytest.mark.asyncio
async def test_missing_credentials_error():
    client = JevClient(model="typesafe/jev-1.13", api_key="", timeout=15.0)
    with pytest.raises(JevMissingCredentialsError):
        await client.decide(state="x", questions={"safe_to_run": NoulQuestion(
            instructions="Decide if should notify.",
            criteria={"true": "Notify.", "false": "Skip."},
        )})


@pytest.mark.asyncio
async def test_rejects_boolean_numeric_values():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "bad-bool",
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": {"safe_to_run": {"type": "noul", "noul": True}},
                "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.0},
            },
        )

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-bool",
        timeout=15.0,
        transport=_Transport(handler),
    )

    with pytest.raises(JevProtocolError):
        await client.decide(
            state="Task: check",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_missing_required_metadata_raises_incomplete_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "gen-dec-missing-metadata",
                "model": "typesafe/jev-1.13-20260917",
                "answers": {"safe_to_run": {"type": "noul", "noul": 0.9}},
            },
        )

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-metadata",
        timeout=15.0,
        transport=_Transport(handler),
    )

    with pytest.raises(JevIncompleteResponseError):
        await client.decide(
            state="Task: check",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_invalid_probability_values_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "bad-probs",
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": {
                    "team": {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": {"technical": 0.2, "billing": 0.2, "sales": 0.2},
                        "confidence": 0.99,
                    }
                },
                "usage": {"input_tokens": 50, "output_tokens": 5, "cost": 0.00001},
            },
        )

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-invalid",
        timeout=15.0,
        transport=_Transport(handler),
    )

    with pytest.raises(JevProtocolError):
        await client.decide(
            state="Payout failed.",
            questions={
                "team": ChoiceQuestion(
                    instructions="Which team?",
                    criteria={"billing": "Payments", "technical": "Bugs", "sales": "Pricing"},
                )
            },
        )


@pytest.mark.asyncio
async def test_http_error_raises_jev_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-http",
        timeout=15.0,
        transport=_Transport(handler),
    )

    with pytest.raises(JevHttpError):
        await client.decide(
            state="Task",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_malformed_json_raises_jev_malformed_json_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not valid json")

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-json",
        timeout=15.0,
        transport=_Transport(handler),
    )

    with pytest.raises(JevMalformedJsonError):
        await client.decide(
            state="Task: malformed payload",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_timeout_raises_jev_timeout_error():
    class TimeoutTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-timeout",
        timeout=15.0,
        transport=TimeoutTransport(),
    )

    with pytest.raises(JevTimeoutError):
        await client.decide(
            state="Task: timeout",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_transport_error_raises_jev_transport_error():
    class FailingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.TransportError("connection lost")

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-transport",
        timeout=15.0,
        transport=FailingTransport(),
    )

    with pytest.raises(JevTransportError):
        await client.decide(
            state="Task: network",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_errors_do_not_expose_sensitive_payloads():
    secret_state = "super-secret-state-123"
    secret_instructions = "Internal instructions: do not leak token abc123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": secret_state, "details": secret_instructions})

    client = JevClient(
        model="typesafe/jev-1.13",
        api_key="sk-secret",
        timeout=15.0,
        transport=_Transport(handler),
    )

    with pytest.raises(JevHttpError) as exc:
        await client.decide(
            state=secret_state,
            questions={
                "safe_to_run": NoulQuestion(
                    instructions=secret_instructions,
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )

    message = str(exc.value)
    assert "super-secret-state-123" not in message
    assert "abc123" not in message
    assert "do not leak" not in message.lower()
    assert "HTTP 401" in message
