from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import AgentModel, AgentsConfig


def _mk_loop(agents_config: AgentsConfig | None = None) -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop.agents_config = agents_config
    return loop


def _agents() -> AgentsConfig:
    return AgentsConfig(
        haiku={"model": "anthropic/claude-3-5-haiku-20241022", "aliases": ["fast", "cheap"]},
        opus={"model": "anthropic/claude-opus-4-20250514", "aliases": ["smart", "deep"]},
    )


# -- resolve_model ---------------------------------------------------------

def test_resolve_by_name() -> None:
    cfg = _agents()
    assert cfg.resolve_model("haiku") == "anthropic/claude-3-5-haiku-20241022"


def test_resolve_by_alias() -> None:
    cfg = _agents()
    assert cfg.resolve_model("fast") == "anthropic/claude-3-5-haiku-20241022"


def test_resolve_case_insensitive() -> None:
    cfg = _agents()
    assert cfg.resolve_model("HAIKU") == "anthropic/claude-3-5-haiku-20241022"
    assert cfg.resolve_model("Smart") == "anthropic/claude-opus-4-20250514"


def test_resolve_unknown() -> None:
    cfg = _agents()
    assert cfg.resolve_model("nonexistent") is None


# -- _parse_model_prefix ----------------------------------------------------

def test_prefix_match_by_name() -> None:
    loop = _mk_loop(_agents())
    model, content = loop._parse_model_prefix("@haiku what's the weather?")
    assert model == "anthropic/claude-3-5-haiku-20241022"
    assert content == "what's the weather?"


def test_prefix_match_by_alias() -> None:
    loop = _mk_loop(_agents())
    model, content = loop._parse_model_prefix("@smart explain recursion")
    assert model == "anthropic/claude-opus-4-20250514"
    assert content == "explain recursion"


def test_prefix_no_match() -> None:
    loop = _mk_loop(_agents())
    model, content = loop._parse_model_prefix("@unknown hello")
    assert model is None
    assert content == "@unknown hello"


def test_prefix_no_at_sign() -> None:
    loop = _mk_loop(_agents())
    model, content = loop._parse_model_prefix("hello world")
    assert model is None
    assert content == "hello world"


def test_prefix_no_body() -> None:
    loop = _mk_loop(_agents())
    model, content = loop._parse_model_prefix("@haiku")
    assert model is None
    assert content == "@haiku"


def test_prefix_whitespace_only_body() -> None:
    loop = _mk_loop(_agents())
    model, content = loop._parse_model_prefix("@haiku   ")
    assert model is None
    assert content == "@haiku   "


def test_prefix_no_agents_config() -> None:
    loop = _mk_loop(None)
    model, content = loop._parse_model_prefix("@haiku hello")
    assert model is None
    assert content == "@haiku hello"


def test_prefix_case_insensitive() -> None:
    loop = _mk_loop(_agents())
    model, content = loop._parse_model_prefix("@OPUS tell me a joke")
    assert model == "anthropic/claude-opus-4-20250514"
    assert content == "tell me a joke"


def test_prefix_not_at_start() -> None:
    loop = _mk_loop(_agents())
    model, content = loop._parse_model_prefix("please use @haiku for this")
    assert model is None
    assert content == "please use @haiku for this"
