from pathlib import Path
from typing import Any
from types import SimpleNamespace

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config
from nanobot.providers.codex_oauth import get_codex_auth_path, read_codex_access_token
from nanobot.providers.codex_cli_provider import CodexCLIProvider
from nanobot.providers.litellm_provider import LiteLLMProvider


class SampleTool(Tool):
    @property
    def name(self) -> str:
        return "sample"

    @property
    def description(self) -> str:
        return "sample tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
                "mode": {"type": "string", "enum": ["fast", "full"]},
                "meta": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "flags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["tag"],
                },
            },
            "required": ["query", "count"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_validate_params_missing_required() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi"})
    assert "missing required count" in "; ".join(errors)


def test_validate_params_type_and_range() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 0})
    assert any("count must be >= 1" in e for e in errors)

    errors = tool.validate_params({"query": "hi", "count": "2"})
    assert any("count should be integer" in e for e in errors)


def test_validate_params_enum_and_min_length() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "h", "count": 2, "mode": "slow"})
    assert any("query must be at least 2 chars" in e for e in errors)
    assert any("mode must be one of" in e for e in errors)


def test_validate_params_nested_object_and_array() -> None:
    tool = SampleTool()
    errors = tool.validate_params(
        {
            "query": "hi",
            "count": 2,
            "meta": {"flags": [1, "ok"]},
        }
    )
    assert any("missing required meta.tag" in e for e in errors)
    assert any("meta.flags[0] should be string" in e for e in errors)


def test_validate_params_ignores_unknown_fields() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 2, "extra": "x"})
    assert errors == []


async def test_registry_returns_validation_error() -> None:
    reg = ToolRegistry()
    reg.register(SampleTool())
    result = await reg.execute("sample", {"query": "hi"})
    assert "Invalid parameters" in result


def _write_codex_auth(path: Path, access_token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'{{"tokens": {{"access_token": "{access_token}", "refresh_token": "r"}}}}',
        encoding="utf-8",
    )


def test_read_codex_access_token_from_auth_json(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    auth_path = get_codex_auth_path()
    _write_codex_auth(auth_path, "codex-token-1")

    assert read_codex_access_token() == "codex-token-1"


def test_config_prefers_openai_codex_for_codex_models(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    _write_codex_auth(codex_home / "auth.json", "codex-token-2")

    cfg = Config()
    cfg.agents.defaults.model = "openai-codex/gpt-5.3-codex"

    assert cfg.get_provider_name() == "openai_codex"
    assert cfg.get_api_key() == "codex-token-2"


def test_config_falls_back_to_api_key_when_oauth_unavailable(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    cfg = Config()
    cfg.agents.defaults.model = "openai-codex/gpt-5.3-codex"
    cfg.providers.openai.api_key = "openai-key"

    assert cfg.get_provider_name() == "openai"
    assert cfg.get_api_key() == "openai-key"


def test_litellm_provider_normalizes_codex_model_prefix() -> None:
    provider = LiteLLMProvider(
        api_key="dummy",
        default_model="openai-codex/gpt-5.3-codex",
        provider_name="openai_codex",
    )
    assert provider._resolve_model("openai-codex/gpt-5.3-codex") == "openai/gpt-5.3-codex"


def test_codex_model_fallback_mapping() -> None:
    assert LiteLLMProvider._codex_fallback_model("openai/gpt-5.3-codex") == "openai/gpt-5.2-codex"
    assert LiteLLMProvider._codex_fallback_model("openai/gpt-5.2-codex") == "openai/gpt-5.1-codex"
    assert LiteLLMProvider._codex_fallback_model("openai/gpt-5.1-codex") is None


async def test_codex_retries_on_model_not_found(monkeypatch) -> None:
    provider = LiteLLMProvider(
        api_key="dummy",
        default_model="openai-codex/gpt-5.3-codex",
        provider_name="openai_codex",
    )

    calls: list[str] = []

    async def fake_acompletion(**kwargs):
        model = kwargs.get("model")
        calls.append(str(model))
        if model == "openai/gpt-5.3-codex":
            raise Exception("The model gpt-5.3-codex does not exist or you do not have access to it.")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None), finish_reason="stop")],
            usage=None,
        )

    import nanobot.providers.litellm_provider as lp

    monkeypatch.setattr(lp, "acompletion", fake_acompletion)
    res = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert res.content == "ok"
    assert calls == ["openai/gpt-5.3-codex", "openai/gpt-5.2-codex"]


async def test_codex_retries_multiple_fallback_tiers(monkeypatch) -> None:
    provider = LiteLLMProvider(
        api_key="dummy",
        default_model="openai-codex/gpt-5.3-codex",
        provider_name="openai_codex",
    )

    calls: list[str] = []

    async def fake_acompletion(**kwargs):
        model = str(kwargs.get("model"))
        calls.append(model)
        if model in {"openai/gpt-5.3-codex", "openai/gpt-5.2-codex"}:
            raise Exception("The model does not exist or you do not have access to it.")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None), finish_reason="stop")],
            usage=None,
        )

    import nanobot.providers.litellm_provider as lp

    monkeypatch.setattr(lp, "acompletion", fake_acompletion)
    res = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert res.content == "ok"
    assert calls == [
        "openai/gpt-5.3-codex",
        "openai/gpt-5.2-codex",
        "openai/gpt-5.1-codex",
    ]


def test_codex_cli_provider_normalizes_model() -> None:
    provider = CodexCLIProvider(default_model="openai-codex/gpt-5.3-codex")
    assert provider._normalize_model("openai-codex/gpt-5.3-codex") == "gpt-5.3-codex"
    assert provider._normalize_model("openai/gpt-5.2-codex") == "gpt-5.2-codex"


async def test_codex_cli_provider_parses_jsonl(monkeypatch) -> None:
    provider = CodexCLIProvider(default_model="openai-codex/gpt-5.3-codex")

    async def fake_run_codex(model: str, prompt: str) -> tuple[int, str, str]:
        assert model == "gpt-5.3-codex"
        assert "USER: hello" in prompt
        out = (
            '{"item":{"type":"message","text":"first line"}}\n'
            '{"item":{"type":"reasoning","text":"ignore"}}\n'
            '{"item":{"type":"assistant_message","text":"second line"}}\n'
        )
        return 0, out, ""

    monkeypatch.setattr(provider, "_run_codex", fake_run_codex)
    res = await provider.chat(messages=[{"role": "user", "content": "hello"}])
    assert res.content == "first line\nsecond line"


async def test_codex_cli_provider_fallback_on_missing_model(monkeypatch) -> None:
    provider = CodexCLIProvider(default_model="openai-codex/gpt-5.3-codex")
    calls: list[str] = []

    async def fake_run_codex(model: str, prompt: str) -> tuple[int, str, str]:
        del prompt
        calls.append(model)
        if model == "gpt-5.3-codex":
            return 1, "", "The model gpt-5.3-codex does not exist or you do not have access to it."
        return 0, '{"item":{"type":"message","text":"ok"}}\n', ""

    monkeypatch.setattr(provider, "_run_codex", fake_run_codex)
    res = await provider.chat(messages=[{"role": "user", "content": "hello"}])
    assert res.content == "ok"
    assert calls == ["gpt-5.3-codex", "gpt-5.2-codex"]


def test_make_provider_uses_codex_cli_for_openai_codex(monkeypatch) -> None:
    from nanobot.cli.commands import _make_provider

    cfg = Config()
    cfg.agents.defaults.model = "openai-codex/gpt-5.3-codex"
    cfg.providers.openai_codex.api_key = "dummy"

    provider = _make_provider(cfg)
    assert isinstance(provider, CodexCLIProvider)
