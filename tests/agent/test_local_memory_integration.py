import asyncio

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.local_memory import (
    LocalMemoryConfig,
    build_capture_request,
    forget_local_memory,
    has_local_memory_server,
    search_local_memory,
    should_capture_candidate,
)
from nanobot.agent.local_memory_hook import LocalMemoryHook
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.loop import AgentLoop
from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


class _FakeTool:
    def __init__(self, name, result):
        self.name = name
        self.description = name
        self.parameters = {"type": "object", "properties": {}, "additionalProperties": True}
        self._result = result
        self.calls = []

    def cast_params(self, params):
        return params

    def validate_params(self, params):
        return []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return self._result

    def to_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _registry_with_tool(name, result):
    registry = ToolRegistry()
    tool = _FakeTool(name, result)
    registry.register(tool)
    return registry


def _registry_with_tools(*tool_specs):
    registry = ToolRegistry()
    tools = {}
    for name, result in tool_specs:
        tool = _FakeTool(name, result)
        registry.register(tool)
        tools[name] = tool
    return registry, tools


def test_has_local_memory_server_accepts_flat_memory_search_name():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_search",
        {"matches": []},
    )
    assert has_local_memory_server(registry, "local_memory") is True


def test_has_local_memory_server_accepts_flat_memory_build_context_name():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_build_context",
        {"context": "remembered context"},
    )
    assert has_local_memory_server(registry, "local_memory") is True


def test_search_local_memory_prefers_build_context_flat_name():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_build_context",
        {"context": "compact retained context"},
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(search_local_memory(registry, "continue", cfg))

    assert result is not None
    assert result.heading == "Supplemental local-memory recall"
    assert "compact retained context" in result.content


def test_search_local_memory_preference_query_includes_profile_terms():
    registry, tools = _registry_with_tools(
        (
            "mcp_local_memory_memory_build_context",
            {"context": "compact retained context"},
        ),
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(search_local_memory(registry, "what's my username", cfg))

    assert result is not None
    call = tools["mcp_local_memory_memory_build_context"].calls[0]
    assert "profile facts" in call["query"]
    assert "username" in call["query"]


def test_search_local_memory_profile_resume_query_classifies_as_preferences():
    registry, tools = _registry_with_tools(
        (
            "mcp_local_memory_memory_build_context",
            {"context": "profile recall"},
        ),
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(search_local_memory(registry, "what should you call me", cfg))

    assert result is not None
    call = tools["mcp_local_memory_memory_build_context"].calls[0]
    assert "preferred name" in call["query"]
    assert "profile facts" in call["query"]


def test_search_local_memory_falls_back_to_flat_memory_search_name():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_search",
        {"matches": [{"title": "Restart path", "summary": "Use the agent restart script."}]},
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(search_local_memory(registry, "continue", cfg))

    assert result is not None
    assert "Restart path" in result.content
    assert "agent restart script" in result.content


def test_search_local_memory_ranks_profile_facts_first_for_preference_queries():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_search",
        {
            "matches": [
                {"title": "Restart path", "summary": "Use the agent restart script.", "domain": "operations", "tags": ["restart"]},
                {
                    "title": "User preferred name",
                    "summary": "Personal fact",
                    "domain": "profile",
                    "tags": ["profile", "identity", "preferred_name"],
                    "metadata": {"profile_fields": {"preferred_name": "Bob", "full_name": "Bob Johnson"}},
                },
            ]
        },
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(search_local_memory(registry, "what should I call you / what's my preferred name", cfg))

    assert result is not None
    lines = result.content.splitlines()
    assert lines[0] == "- User preferred name: Preferred name: Bob"


def test_forget_local_memory_deprecates_matching_record():
    registry, tools = _registry_with_tools(
        (
            "mcp_local_memory_memory_search",
            {"matches": [{"record_id": "rec_1", "title": "Restart path", "summary": "Use restart-by-agent.sh"}]},
        ),
        ("mcp_local_memory_memory_deprecate", {"ok": True}),
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(forget_local_memory(registry, "restart path", cfg))

    assert result is True
    assert tools["mcp_local_memory_memory_deprecate"].calls
    call = tools["mcp_local_memory_memory_deprecate"].calls[0]
    assert call["record_id"] == "rec_1"
    assert "forget" in call["reason"].lower()



def test_forget_local_memory_prefers_duplicate_for_dedup():
    registry, tools = _registry_with_tools(
        (
            "mcp_local_memory_memory_search",
            {
                "matches": [
                    {"record_id": "rec_old", "title": "Preferred Git authentication on this host uses SSH", "summary": "Use SSH remotes."},
                    {"record_id": "rec_new", "title": "Preferred Git authentication on this host uses SSH", "summary": "Use SSH remotes."},
                ]
            },
        ),
        ("mcp_local_memory_memory_deprecate", {"ok": True}),
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(forget_local_memory(registry, "preferred git authentication on this host uses ssh", cfg))

    assert result is True
    call = tools["mcp_local_memory_memory_deprecate"].calls[0]
    assert call["record_id"] == "rec_new"
    assert "dedup" in call["reason"].lower()



def test_forget_local_memory_semantic_dedup_matches_near_duplicates():
    registry, tools = _registry_with_tools(
        (
            "mcp_local_memory_memory_search",
            {
                "matches": [
                    {
                        "record_id": "git_github_ssh_key_auth",
                        "title": "Git remotes use GitHub SSH key authentication",
                        "summary": "This environment uses SSH remotes for GitHub and an explicit ed25519 key configured in ssh config.",
                    },
                    {
                        "record_id": "lm_fact_preferred_git_ssh",
                        "title": "Preferred Git authentication on this host uses SSH",
                        "summary": "Git operations on this host should use GitHub SSH remotes rather than HTTPS auth.",
                    },
                ]
            },
        ),
        ("mcp_local_memory_memory_deprecate", {"ok": True}),
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(forget_local_memory(registry, "preferred git authentication on this host uses ssh", cfg))

    assert result is True
    call = tools["mcp_local_memory_memory_deprecate"].calls[0]
    assert call["record_id"] == "lm_fact_preferred_git_ssh"
    assert "dedup" in call["reason"].lower()


def test_local_memory_hook_marks_forget_request_before_iteration():
    cfg = LocalMemoryConfig(enabled=True, search_first=True)
    hook = LocalMemoryHook(cfg)
    registry = _registry_with_tool("mcp_local_memory_memory_search", {"matches": []})
    context = AgentHookContext(
        iteration=1,
        messages=[{"role": "user", "content": "forget that restart path"}],
        agent=type("Agent", (), {"tools": registry})(),
    )

    asyncio.run(hook.before_iteration(context))

    assert context.memory_action == "forget"
    assert context.memory_target_query == "restart path"
    assert context.messages[0]["role"] == "system"
    assert "forget" in context.messages[0]["content"].lower()


def test_local_memory_hook_bootstrap_query_includes_profile_and_project_terms():
    cfg = LocalMemoryConfig(enabled=True, search_first=True, enable_bootstrap_recall=True)
    hook = LocalMemoryHook(cfg)
    registry, tools = _registry_with_tools(
        (
            "mcp_local_memory_memory_build_context",
            {"context": "bootstrap recall"},
        ),
    )
    context = AgentHookContext(
        iteration=1,
        messages=[],
        agent=type("Agent", (), {"tools": registry})(),
    )

    asyncio.run(hook.before_iteration(context))

    call = tools["mcp_local_memory_memory_build_context"].calls[0]
    assert "active project context" in call["query"]
    assert "preferred name" in call["query"]
    assert context.messages[0]["role"] == "system"
    assert "bootstrap recall" in context.messages[0]["content"]


def test_local_memory_hook_inserts_after_primary_system_prompt():
    cfg = LocalMemoryConfig(enabled=True, search_first=True)
    hook = LocalMemoryHook(cfg)
    registry = _registry_with_tool(
        "mcp_local_memory_memory_build_context",
        {"context": "supplemental recall"},
    )
    context = AgentHookContext(
        iteration=1,
        messages=[
            {"role": "system", "content": "Primary system prompt"},
            {"role": "user", "content": "what's my username"},
        ],
        agent=type("Agent", (), {"tools": registry})(),
    )

    asyncio.run(hook.before_iteration(context))

    assert context.messages[0] == {"role": "system", "content": "Primary system prompt"}
    assert context.messages[1]["role"] == "system"
    assert "Supplemental local-memory recall" in context.messages[1]["content"]
    assert context.messages[2] == {"role": "user", "content": "what's my username"}


def test_should_capture_candidate_for_personal_preference_even_without_auto_capture_candidates():
    cfg = LocalMemoryConfig(enabled=True, auto_capture_candidates=False, auto_capture_personal_facts=True)

    assert should_capture_candidate("My favorite food is pizza", None, cfg) is True


def test_build_capture_request_for_preferred_name_personal_fact():
    cfg = LocalMemoryConfig(enabled=True, auto_capture_personal_facts=True)

    request = build_capture_request("My name is Bob Johnson but you can call me Bob", "", cfg)

    assert request is not None
    assert request.type == "user_identity"
    assert request.domain == "profile"
    assert request.title == "User preferred name"
    assert request.summary == "Preferred name: Bob"
    assert "identity" in request.tags
    assert request.metadata["source"] == "user_stated"
    assert request.metadata["profile_fields"]["full_name"] == "Bob Johnson"
    assert request.metadata["profile_fields"]["preferred_name"] == "Bob"


def test_build_capture_request_for_sensitive_health_fact_with_date():
    cfg = LocalMemoryConfig(enabled=True, auto_capture_personal_facts=True)

    request = build_capture_request("I had a heart attack on April 10th", "", cfg)

    assert request is not None
    assert request.type == "user_health_fact"
    assert request.metadata["sensitivity"] == "high"
    assert request.metadata["event_date"] == "2026-04-10"
    assert request.metadata["profile_fields"]["event_date"] == "2026-04-10"
    assert "health" in request.tags


def test_build_capture_request_for_username_and_favorite_food_fields():
    cfg = LocalMemoryConfig(enabled=True, auto_capture_personal_facts=True)

    username_request = build_capture_request("My username is bjohnson", "", cfg)
    favorite_request = build_capture_request("My favorite food is pizza", "", cfg)

    assert username_request is not None
    assert username_request.metadata["profile_fields"]["username"] == "bjohnson"
    assert username_request.summary == "Username: bjohnson"
    assert favorite_request is not None
    assert favorite_request.metadata["profile_fields"]["favorite_food"] == "pizza"
    assert favorite_request.summary == "Favorite food: pizza"


class _RunnerTestProvider(LLMProvider):
    def __init__(self):
        self.calls = []
        self.generation = GenerationSettings()

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    ):
        self.calls.append({
            "messages": messages,
            "tools": tools,
            "model": model,
        })
        return LLMResponse(content="runner final", finish_reason="stop")

    def get_default_model(self) -> str:
        return "test-model"


def test_agent_runner_passes_hook_mutated_messages_to_model_request():
    class InjectingHook(LocalMemoryHook):
        async def before_iteration(self, context):
            context.messages.insert(1, {"role": "system", "content": "Injected by hook"})

    provider = _RunnerTestProvider()
    runner = AgentRunner(provider)
    registry = _registry_with_tool(
        "mcp_local_memory_memory_build_context",
        {"context": "runner bootstrap recall"},
    )
    runner.tools = registry
    hook = InjectingHook(LocalMemoryConfig(enabled=True, search_first=True))
    spec = AgentRunSpec(
        initial_messages=[
            {"role": "system", "content": "Primary system prompt"},
            {"role": "user", "content": "what should you call me"},
        ],
        tools=registry,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=4000,
        hook=hook,
    )

    result = asyncio.run(runner.run(spec))

    assert result.final_content == "runner final"
    sent = provider.calls[0]["messages"]
    assert sent[0] == {"role": "system", "content": "Primary system prompt"}
    assert sent[1] == {"role": "system", "content": "Injected by hook"}
    assert sent[2] == {"role": "user", "content": "what should you call me"}
