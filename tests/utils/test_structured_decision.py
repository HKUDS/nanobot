from __future__ import annotations

import asyncio
import json
from typing import cast

import httpx
import pytest

from nanobot.config.schema import Config
from nanobot.utils.structured_decision import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionClientClosedError,
    DecisionHttpError,
    DecisionProtocolError,
    DecisionRequest,
    DecisionTimeoutError,
    DecisionTransportError,
    IncompleteDecisionResponseError,
    MalformedDecisionJsonError,
    MissingCredentialsError,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    StructuredDecisionClient,
    StructuredInput,
)
from nanobot.utils.structured_decision import providers as decision_providers
from nanobot.utils.structured_decision.providers import (
    DecisionProviderProfile,
    DecisionProviderSettings,
    registered_decision_provider_names,
)


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _make_client(
    *,
    model: str = "typesafe/jev-1.13",
    api_key: str | None = "sk-test",
    timeout: float = 15.0,
    proxy: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> StructuredDecisionClient:
    provider_config: dict[str, str] = {}
    if api_key is not None:
        provider_config["apiKey"] = api_key
    if proxy is not None:
        provider_config["proxy"] = proxy
    config = Config.model_validate(
        {
            "structuredDecision": {"model": model, "timeoutS": timeout},
            "providers": {"openrouter": provider_config},
        }
    )
    return StructuredDecisionClient.from_config(config, transport=transport)


def test_client_from_config_uses_named_provider_settings_and_injected_transport():
    transport = _Transport(lambda request: httpx.Response(200, json={}))
    config = Config.model_validate(
        {
            "structuredDecision": {
                "model": "openai/model-name-does-not-select-provider",
                "provider": "openrouter",
                "timeoutS": 25,
            },
            "providers": {
                "openrouter": {
                    "apiKey": "selected-key",
                    "apiBase": "https://chat.example/v1",
                    "proxy": "http://proxy.example:8080",
                },
                "openai": {"apiKey": "different-key"},
            },
        }
    )

    client = StructuredDecisionClient.from_config(config, transport=transport)

    assert client.model == "openai/model-name-does-not-select-provider"
    assert client.provider == "openrouter"
    assert client.protocol == "system_one"
    assert client._wire_transport.endpoint_url == "https://openrouter.ai/api/alpha/decisions"
    assert client._wire_transport.api_key == "selected-key"
    assert client._wire_transport.proxy == "http://proxy.example:8080"
    assert client._wire_transport.timeout == 25
    assert client._wire_transport.transport is transport


def test_config_environment_references_resolve_before_provider_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fallback-key")
    monkeypatch.setenv("STRUCTURED_DECISION_KEY", "configured-key")
    monkeypatch.setenv("STRUCTURED_DECISION_PROXY", "http://proxy.example:8080")
    config = Config.model_validate(
        {
            "providers": {
                "openrouter": {
                    "apiKey": "${STRUCTURED_DECISION_KEY}",
                    "proxy": "${STRUCTURED_DECISION_PROXY}",
                }
            }
        }
    )

    client = StructuredDecisionClient.from_config(config)

    assert client._wire_transport.api_key == "configured-key"
    assert client._wire_transport.proxy == "http://proxy.example:8080"


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
                "answers": {"safe_to_run": {"type": "noul", "noul": 0.95}},
                "usage": {"input_tokens": 492, "output_tokens": 22},
            },
        )

    client = _make_client(transport=_Transport(handler))

    result = await client.evaluate(
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
    noul_answer = result.answers["safe_to_run"]
    assert isinstance(noul_answer, NoulAnswer)
    assert noul_answer.noul == pytest.approx(0.95)
    assert result.usage is not None
    assert result.usage.input_tokens == 492
    assert result.usage.output_tokens == 22


@pytest.mark.asyncio
async def test_structured_json_inputs_and_optional_noul_criteria_are_preserved():
    request_count = 0
    state = {"task": "classify", "message": ["Help", {"context": None}]}
    noul_instructions = {"question": "Notify?", "context": ["urgent", None]}
    choice_instructions = ["Select a category", {"locale": "en"}]
    choice_criteria = {
        "yes": {"description": "Relevant", "tags": ["user", None]},
        "no": None,
    }
    score_criteria = ["Low", {"label": "High", "metadata": {"source": "agent"}}]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        payload = json.loads(request.content.decode())
        assert payload["state"] == state
        assert payload["questions"]["notify"]["instructions"] == noul_instructions
        assert "criteria" not in payload["questions"]["notify"]
        assert payload["questions"]["category"]["instructions"] == choice_instructions
        assert payload["questions"]["category"]["criteria"] == choice_criteria
        assert payload["questions"]["score"]["criteria"] == score_criteria
        return httpx.Response(
            200,
            json={
                "id": "gen-structured",
                "model": "typesafe/jev-1.13-20260917",
                "answers": {
                    "notify": {"type": "noul", "noul": 0.9},
                    "category": {
                        "type": "choice",
                        "choice": "yes",
                        "probabilities": {"yes": 1.0, "no": 0.0},
                        "confidence": 0.9,
                    },
                    "score": {
                        "type": "score",
                        "score": 1.0,
                        "legend": {"0": "Low", "1": "High"},
                        "probabilities": {"0": 0.0, "1": 1.0},
                        "confidence": 0.9,
                    },
                },
                "usage": {"input_tokens": 40, "output_tokens": 10},
            },
        )

    client = _make_client(api_key="sk-structured", transport=_Transport(handler))
    result = await client.evaluate(
        state=state,
        questions={
            "notify": NoulQuestion(instructions=noul_instructions),
            "category": ChoiceQuestion(
                instructions=choice_instructions,
                criteria=choice_criteria,
            ),
            "score": ScoreQuestion(
                instructions={"instruction": "Rate the result"},
                criteria=score_criteria,
            ),
        },
    )

    assert request_count == 1
    assert isinstance(result.answers["notify"], NoulAnswer)
    assert result.answers["notify"].noul == pytest.approx(0.9)
    category_answer = result.answers["category"]
    assert isinstance(category_answer, ChoiceAnswer)
    assert category_answer.choice == "yes"
    assert category_answer.probabilities == {"yes": 1.0, "no": 0.0}
    assert category_answer.confidence == pytest.approx(0.9)
    score_answer = result.answers["score"]
    assert isinstance(score_answer, ScoreAnswer)
    assert score_answer.score == pytest.approx(1.0)
    assert score_answer.legend == {"0": "Low", "1": "High"}
    assert score_answer.probabilities == {"0": 0.0, "1": 1.0}
    assert score_answer.confidence == pytest.approx(0.9)


def test_initial_provider_registry_contains_only_openrouter():
    assert registered_decision_provider_names() == ("openrouter",)


def test_provider_settings_repr_hides_api_key():
    api_key = "repr-test-secret"
    settings = DecisionProviderSettings(
        name="openrouter",
        protocol="system_one",
        endpoint_url="https://openrouter.ai/api/alpha/decisions",
        api_key=api_key,
        proxy=None,
        requires_api_key=True,
    )

    assert settings.api_key == api_key
    assert api_key not in repr(settings)


@pytest.mark.asyncio
async def test_test_only_registered_profile_supplies_endpoint_and_credentials(monkeypatch):
    monkeypatch.setitem(
        decision_providers._PROVIDER_PROFILES,
        "test_decider",
        DecisionProviderProfile(
            name="test_decider",
            base_url="https://decision.example/api/",
            route="/alpha/decisions",
            api_key_env="TEST_DECIDER_API_KEY",
            protocols=("system_one",),
        ),
    )
    monkeypatch.setenv("TEST_DECIDER_API_KEY", "test-profile-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://decision.example/api/alpha/decisions"
        assert request.headers["Authorization"] == "Bearer test-profile-key"
        payload = json.loads(request.content.decode())
        assert payload["model"] == "test-model"
        assert payload["state"] == {"status": "ready"}
        return httpx.Response(
            200,
            json={
                "model": "test-model-v2",
                "answers": {"notify": {"type": "noul", "noul": 1}},
            },
        )

    config = Config.model_validate(
        {
            "structuredDecision": {
                "provider": "test_decider",
                "model": "test-model",
            },
            "providers": {
                "test_decider": {"proxy": "http://test-proxy:8080"}
            },
        }
    )
    client = StructuredDecisionClient.from_config(config, transport=_Transport(handler))

    result = await client.evaluate(
        state={"status": "ready"},
        questions={"notify": NoulQuestion(instructions="Notify?")},
    )

    assert client._wire_transport.proxy == "http://test-proxy:8080"
    assert result.model == "test-model-v2"
    assert result.response_id is None
    assert result.usage is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_state", "error_message"),
    [
        ("  ", "cannot be blank"),
        ({"value": float("inf")}, "non-finite"),
        ({1: "value"}, "object keys must be strings"),
        ({"value": object()}, "not JSON-compatible"),
    ],
)
async def test_rejects_invalid_structured_state(invalid_state: object, error_message: str):
    client = _make_client()

    with pytest.raises(DecisionProtocolError, match=error_message):
        await client.evaluate(
            state=cast(StructuredInput, invalid_state),
            questions={"notify": NoulQuestion(instructions="Notify?")},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("instructions", "error_message"),
    [
        ("  ", "cannot be blank"),
        ({"value": float("inf")}, "non-finite"),
        ({1: "value"}, "object keys must be strings"),
        ({"value": object()}, "not JSON-compatible"),
    ],
)
async def test_rejects_invalid_structured_instructions(instructions, error_message):
    client = _make_client()

    with pytest.raises(DecisionProtocolError, match=error_message):
        await client.evaluate(
            state="state",
            questions={"q": NoulQuestion(instructions=cast(StructuredInput, instructions))},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "answers", "expected_error"),
    [
        (
            NoulQuestion(instructions="Notify?"),
            {},
            IncompleteDecisionResponseError,
        ),
        (
            NoulQuestion(instructions="Notify?"),
            {
                "q": {"type": "noul", "noul": 0.5},
                "unrequested": {"type": "noul", "noul": 0.5},
            },
            DecisionProtocolError,
        ),
        (
            NoulQuestion(instructions="Notify?"),
            {"q": {"type": "choice", "choice": "yes"}},
            DecisionProtocolError,
        ),
        (
            NoulQuestion(instructions="Notify?"),
            {"q": {"type": "noul", "noul": 1.1}},
            DecisionProtocolError,
        ),
        (
            ChoiceQuestion(instructions="Choose", criteria={"yes": "Yes", "no": "No"}),
            {
                "q": {
                    "type": "choice",
                    "choice": "other",
                    "probabilities": {"yes": 1.0, "no": 0.0},
                    "confidence": 0.8,
                }
            },
            DecisionProtocolError,
        ),
        (
            ChoiceQuestion(instructions="Choose", criteria={"yes": "Yes", "no": "No"}),
            {
                "q": {
                    "type": "choice",
                    "choice": "yes",
                    "probabilities": {"yes": 1.0},
                    "confidence": 0.8,
                }
            },
            DecisionProtocolError,
        ),
        (
            ChoiceQuestion(instructions="Choose", criteria={"yes": "Yes", "no": "No"}),
            {
                "q": {
                    "type": "choice",
                    "choice": "yes",
                    "probabilities": {"yes": 1.0, "no": 0.0},
                    "confidence": True,
                }
            },
            DecisionProtocolError,
        ),
        (
            ScoreQuestion(instructions="Rate", criteria=["Low", "High"]),
            {
                "q": {
                    "type": "score",
                    "score": 1.1,
                    "legend": {"0": "Low", "1": "High"},
                    "probabilities": {"0": 0.0, "1": 1.0},
                    "confidence": 0.8,
                }
            },
            DecisionProtocolError,
        ),
        (
            ScoreQuestion(instructions="Rate", criteria=["Low", "High"]),
            {
                "q": {
                    "type": "score",
                    "score": 1.0,
                    "legend": {"0": "Low"},
                    "probabilities": {"0": 0.0, "1": 1.0},
                    "confidence": 0.8,
                }
            },
            DecisionProtocolError,
        ),
    ],
)
async def test_invalid_answer_contracts_are_rejected(question, answers, expected_error):
    client = _make_client(
        transport=_Transport(
            lambda request: httpx.Response(
                200,
                json={"model": "test-model", "answers": answers},
            )
        )
    )

    with pytest.raises(expected_error):
        await client.evaluate(state="state", questions={"q": question})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question_id", "question"),
    [
        ("  ", NoulQuestion(instructions="Notify?")),
        ("q", object()),
        ("q", NoulQuestion(instructions="Notify?", criteria={"true": "Only true"})),
        ("q", ChoiceQuestion(instructions="Choose", criteria={})),
        ("q", ScoreQuestion(instructions="Rate", criteria=["Only one"])),
    ],
)
async def test_rejects_invalid_question_ids_and_shapes(question_id, question):
    client = _make_client()

    with pytest.raises(DecisionProtocolError):
        await client.evaluate(state="state", questions={question_id: question})


@pytest.mark.asyncio
async def test_choice_decide_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "gen-dec-choice",
                "model": "typesafe/jev-1.13-20260917",
                "answers": {
                    "team": {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": {"technical": 0.0, "billing": 1.0, "sales": 0.0},
                        "confidence": 0.99,
                    }
                },
                "usage": {"input_tokens": 200, "output_tokens": 20},
            },
        )

    client = _make_client(api_key="sk-choice", transport=_Transport(handler))

    result = await client.evaluate(
        state="Payout failed.",
        questions={
            "team": ChoiceQuestion(
                instructions="Which team should handle this?",
                criteria={"billing": "Payments", "technical": "Bugs", "sales": "Pricing"},
            )
        },
    )

    answer = result.answers["team"]
    assert isinstance(answer, ChoiceAnswer)
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
                "answers": {
                    "buying_intent": {
                        "type": "score",
                        "score": 2.97,
                        "legend": {"0": "A", "1": "B", "2": "C", "3": "D"},
                        "probabilities": {"0": 0.0, "1": 0.0, "2": 0.03, "3": 0.97},
                        "confidence": 0.97,
                    }
                },
                "usage": {"input_tokens": 300, "output_tokens": 30},
            },
        )

    client = _make_client(api_key="sk-score", transport=_Transport(handler))

    result = await client.evaluate(
        state="Pricing for 40 seats",
        questions={
            "buying_intent": ScoreQuestion(
                instructions="How ready is this lead to buy?",
                criteria=["A", "B", "C", "D"],
            )
        },
    )

    answer = result.answers["buying_intent"]
    assert isinstance(answer, ScoreAnswer)
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
                "answers": {"safe_to_run": {"type": "noul", "noul": 0.5}},
                "usage": {"input_tokens": 8, "output_tokens": 2},
            },
        )

    client = _make_client(api_key=None, transport=_Transport(handler))

    result = await client.evaluate(
        state="Task: check",
        questions={
            "safe_to_run": NoulQuestion(
                instructions="Decide if should notify.",
                criteria={"true": "Notify.", "false": "Skip."},
            )
        },
    )

    assert result.response_id == "gen-dec-env"
    noul_answer = result.answers["safe_to_run"]
    assert isinstance(noul_answer, NoulAnswer)
    assert noul_answer.noul == pytest.approx(0.5)


def test_injected_transport_takes_precedence_over_proxy():
    transport = _Transport(lambda request: httpx.Response(200, json={}))
    client = _make_client(
        proxy="http://proxy:8080",
        transport=transport,
    )

    assert client._wire_transport._make_http_transport() is transport


def test_timeout_must_be_positive():
    with pytest.raises(ValueError):
        _make_client(timeout=0.0)


@pytest.mark.asyncio
async def test_missing_credentials_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = _make_client(api_key=None)
    with pytest.raises(MissingCredentialsError):
        await client.evaluate(state="x", questions={"safe_to_run": NoulQuestion(
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
                "answers": {"safe_to_run": {"type": "noul", "noul": True}},
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        )

    client = _make_client(api_key="sk-bool", transport=_Transport(handler))

    with pytest.raises(DecisionProtocolError):
        await client.evaluate(
            state="Task: check",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_optional_metadata_can_be_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "typesafe/jev-1.13-20260917",
                "answers": {"safe_to_run": {"type": "noul", "noul": 0.9}},
            },
        )

    client = _make_client(api_key="sk-metadata", transport=_Transport(handler))

    result = await client.evaluate(
        state="Task: check",
        questions={
            "safe_to_run": NoulQuestion(
                instructions="Decide if should notify.",
                criteria={"true": "Notify.", "false": "Skip."},
            )
        },
    )

    assert result.model == "typesafe/jev-1.13-20260917"
    assert result.response_id is None
    assert result.usage is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"usage": "invalid"},
        {"usage": {"input_tokens": True}},
        {"usage": {"output_tokens": -1}},
    ],
)
async def test_invalid_usage_metadata_is_rejected(metadata):
    def handler(request: httpx.Request) -> httpx.Response:
        response = {
            "model": "typesafe/jev-1.13-20260917",
            "answers": {"safe_to_run": {"type": "noul", "noul": 0.9}},
        }
        response.update(metadata)
        return httpx.Response(200, json=response)

    client = _make_client(api_key="sk-metadata", transport=_Transport(handler))

    with pytest.raises(DecisionProtocolError):
        await client.evaluate(
            state="Task: check",
            questions={"safe_to_run": NoulQuestion(instructions="Decide if should notify.")},
        )


@pytest.mark.parametrize(
    "probabilities",
    [
        {"technical": 0.2, "billing": 0.3, "sales": 0.49},
        {"technical": 0.2, "billing": 0.8, "sales": 0.0001},
    ],
)
@pytest.mark.asyncio
async def test_probability_values_are_preserved_without_sum_constraint(probabilities):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "bad-probs",
                "model": "typesafe/jev-1.13-20260917",
                "answers": {
                    "team": {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": probabilities,
                        "confidence": 0.99,
                    }
                },
                "usage": {"input_tokens": 50, "output_tokens": 5},
            },
        )

    client = _make_client(api_key="sk-invalid", transport=_Transport(handler))

    result = await client.evaluate(
        state="Payout failed.",
        questions={
            "team": ChoiceQuestion(
                instructions="Which team?",
                criteria={"billing": "Payments", "technical": "Bugs", "sales": "Pricing"},
            )
        },
    )

    answer = result.answers["team"]
    assert isinstance(answer, ChoiceAnswer)
    assert answer.probabilities == probabilities


@pytest.mark.asyncio
async def test_http_error_raises_decision_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _make_client(api_key="sk-http", transport=_Transport(handler))

    with pytest.raises(DecisionHttpError):
        await client.evaluate(
            state="Task",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_redirect_response_raises_decision_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://redirect.example"},
            json={
                "model": "test-model",
                "answers": {"safe_to_run": {"type": "noul", "noul": 0.9}},
            },
        )

    client = _make_client(api_key="sk-redirect", transport=_Transport(handler))

    with pytest.raises(DecisionHttpError):
        await client.evaluate(
            state="Task",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_malformed_json_raises_decision_malformed_json_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not valid json")

    client = _make_client(api_key="sk-json", transport=_Transport(handler))

    with pytest.raises(MalformedDecisionJsonError):
        await client.evaluate(
            state="Task: malformed payload",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_timeout_raises_decision_timeout_error():
    class TimeoutTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

    client = _make_client(api_key="sk-timeout", transport=TimeoutTransport())

    with pytest.raises(DecisionTimeoutError):
        await client.evaluate(
            state="Task: timeout",
            questions={
                "safe_to_run": NoulQuestion(
                    instructions="Decide if should notify.",
                    criteria={"true": "Notify.", "false": "Skip."},
                )
            },
        )


@pytest.mark.asyncio
async def test_transport_error_raises_decision_transport_error():
    class FailingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.TransportError("connection lost")

    client = _make_client(api_key="sk-transport", transport=FailingTransport())

    with pytest.raises(DecisionTransportError):
        await client.evaluate(
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

    client = _make_client(api_key="sk-secret", transport=_Transport(handler))

    with pytest.raises(DecisionHttpError) as exc:
        await client.evaluate(
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


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, gate: asyncio.Event | None = None):
        self.requests: list[httpx.Request] = []
        self.close_count = 0
        self.started = asyncio.Event()
        self._gate = gate

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.started.set()
        if self._gate is not None:
            await self._gate.wait()
        return httpx.Response(
            200,
            json={"model": "m", "answers": {"notify": {"type": "noul", "noul": 1}}},
        )

    async def aclose(self) -> None:
        self.close_count += 1


async def _evaluate_once(client: StructuredDecisionClient):
    return await client.evaluate(
        state={"status": "ready"},
        questions={"notify": NoulQuestion(instructions="Notify?")},
    )


@pytest.mark.asyncio
async def test_multiple_evaluations_reuse_open_injected_transport_until_close():
    transport = _RecordingTransport()
    client = _make_client(transport=transport)

    await _evaluate_once(client)
    await _evaluate_once(client)

    assert len(transport.requests) == 2
    assert transport.close_count == 0

    await client.aclose()

    assert transport.close_count == 1


@pytest.mark.asyncio
async def test_aclose_is_idempotent():
    transport = _RecordingTransport()
    client = _make_client(transport=transport)
    await _evaluate_once(client)

    await client.aclose()
    await client.aclose()

    assert transport.close_count == 1


@pytest.mark.asyncio
async def test_async_context_closes_on_normal_exit_and_on_exception():
    normal = _RecordingTransport()
    async with _make_client(transport=normal) as client:
        await _evaluate_once(client)
    assert normal.close_count == 1

    failing = _RecordingTransport()
    with pytest.raises(RuntimeError, match="boom"):
        async with _make_client(transport=failing) as client:
            await _evaluate_once(client)
            raise RuntimeError("boom")
    assert failing.close_count == 1


@pytest.mark.asyncio
async def test_evaluate_after_close_raises_closed_error():
    transport = _RecordingTransport()
    client = _make_client(transport=transport)
    await _evaluate_once(client)
    await client.aclose()

    with pytest.raises(DecisionClientClosedError):
        await _evaluate_once(client)
    with pytest.raises(DecisionClientClosedError):
        await client._wire_transport.evaluate(
            DecisionRequest(
                model="m",
                state="s",
                questions={"notify": NoulQuestion(instructions="Notify?")},
            )
        )
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_unused_client_creates_no_http_client_and_closes_safely():
    client = _make_client()

    assert client._wire_transport._http_client is None

    await client.aclose()

    assert client._wire_transport._http_client is None


@pytest.mark.asyncio
async def test_unused_client_closes_injected_transport():
    transport = _RecordingTransport()
    client = _make_client(transport=transport)

    await client.aclose()
    await client.aclose()

    assert transport.close_count == 1


@pytest.mark.asyncio
async def test_aclose_closes_default_internal_transport(monkeypatch):
    created: list[_FakeHttpTransport] = []

    class _FakeHttpTransport(_RecordingTransport):
        def __init__(self, **kwargs):
            super().__init__()
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", _FakeHttpTransport)
    client = _make_client(proxy="http://proxy.example:8080")

    await _evaluate_once(client)
    await _evaluate_once(client)
    await client.aclose()

    assert len(created) == 1
    assert len(created[0].requests) == 2
    assert created[0].close_count == 1
    assert created[0].kwargs["proxy"] == "http://proxy.example:8080"
    assert created[0].kwargs["trust_env"] is False
    limits = created[0].kwargs["limits"]
    assert limits.max_keepalive_connections == 2
    assert limits.keepalive_expiry == 30


@pytest.mark.asyncio
async def test_aclose_waits_for_in_flight_evaluation_and_rejects_new_ones():
    gate = asyncio.Event()
    transport = _RecordingTransport(gate)
    client = _make_client(transport=transport)

    in_flight = asyncio.create_task(_evaluate_once(client))
    await transport.started.wait()
    closing = asyncio.create_task(client.aclose())
    await asyncio.sleep(0)

    assert not closing.done()
    assert transport.close_count == 0
    with pytest.raises(DecisionClientClosedError):
        await _evaluate_once(client)

    gate.set()
    result = await in_flight
    await closing

    assert isinstance(result.answers["notify"], NoulAnswer)
    assert transport.close_count == 1


@pytest.mark.asyncio
async def test_concurrent_aclose_calls_return_only_after_close_completes():
    gate = asyncio.Event()
    transport = _RecordingTransport(gate)
    client = _make_client(transport=transport)
    in_flight = asyncio.create_task(_evaluate_once(client))
    await transport.started.wait()

    first = asyncio.create_task(client.aclose())
    second = asyncio.create_task(client.aclose())
    await asyncio.sleep(0)
    assert not first.done()
    assert not second.done()

    gate.set()
    await in_flight
    await asyncio.gather(first, second)

    assert transport.close_count == 1


@pytest.mark.asyncio
async def test_failed_and_cancelled_evaluations_do_not_block_close():
    transport = _RecordingTransport(asyncio.Event())
    client = _make_client(transport=transport)

    cancelled = asyncio.create_task(_evaluate_once(client))
    await transport.started.wait()
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    await asyncio.wait_for(client.aclose(), timeout=1)

    assert transport.close_count == 1

    failing = _make_client(transport=_Transport(lambda request: httpx.Response(500, json={})))
    with pytest.raises(DecisionHttpError):
        await _evaluate_once(failing)
    await asyncio.wait_for(failing.aclose(), timeout=1)
