from nanobot.config.schema import AgentDefaults


def test_agent_defaults_has_session_backend():
    defaults = AgentDefaults()
    assert defaults.session_backend == "normal"


def test_agent_defaults_has_memory_backend():
    defaults = AgentDefaults()
    assert defaults.memory_backend == "normal"


def test_agent_defaults_accepts_custom_backend():
    defaults = AgentDefaults(session_backend="redis", memory_backend="redis")
    assert defaults.session_backend == "redis"
    assert defaults.memory_backend == "redis"


def test_agent_defaults_camelcase_alias():
    """Config files use camelCase (sessionBackend, memoryBackend)."""
    defaults = AgentDefaults.model_validate(
        {"sessionBackend": "custom", "memoryBackend": "custom"}
    )
    assert defaults.session_backend == "custom"
    assert defaults.memory_backend == "custom"
