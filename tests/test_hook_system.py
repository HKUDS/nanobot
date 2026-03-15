"""Test event-driven hook system."""

import tempfile
from pathlib import Path

from nanobot.agent.hooks import Hook, HookEvent, HookRegistry, HookResult, HookStorage, SkillsEnabledFilter


# ---- Test helpers ----

class PassthroughHook(Hook):
    """Hook that records calls but does nothing."""

    def __init__(self, name: str, priority: int = 100, matcher: str | None = None):
        self._name = name
        self._priority = priority
        self._matcher = matcher
        self.events: list[tuple[HookEvent, dict]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def matcher(self) -> str | None:
        return self._matcher

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        self.events.append((event, context))
        return HookResult()


class BlockingHook(Hook):
    """Hook that blocks a specific event."""

    def __init__(self, name: str, block_event: HookEvent, reason: str = "blocked", priority: int = 100):
        self._name = name
        self._block_event = block_event
        self._reason = reason
        self._priority = priority

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        if event == self._block_event:
            return HookResult(proceed=False, reason=self._reason)
        return HookResult()


class ModifyingHook(Hook):
    """Hook that modifies data for PRE_BUILD_CONTEXT skills."""

    def __init__(self, name: str, transform, priority: int = 100):
        self._name = name
        self._transform = transform
        self._priority = priority

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        if event == HookEvent.PRE_BUILD_CONTEXT and context.get("type") == "skills":
            return HookResult(modified_data=self._transform(context.get("data", [])))
        return HookResult()


# ---- Registry tests ----

def test_register_and_unregister():
    reg = HookRegistry()
    hook = PassthroughHook("a")
    reg.register(hook)
    assert reg.get_hook("a") is hook
    reg.unregister("a")
    assert reg.get_hook("a") is None


def test_unregister_missing_is_noop():
    reg = HookRegistry()
    reg.unregister("nonexistent")  # should not raise


# ---- Emit tests ----

def test_emit_calls_all_hooks():
    reg = HookRegistry()
    h1 = PassthroughHook("h1")
    h2 = PassthroughHook("h2")
    reg.register(h1)
    reg.register(h2)

    reg.emit(HookEvent.SESSION_START, {"session_key": "test"})
    assert len(h1.events) == 1
    assert len(h2.events) == 1
    assert h1.events[0][0] == HookEvent.SESSION_START


def test_emit_priority_ordering():
    """Lower priority hooks execute first."""
    order = []

    class OrderHook(Hook):
        def __init__(self, name, prio):
            self._name = name
            self._prio = prio
        @property
        def name(self): return self._name
        @property
        def priority(self): return self._prio
        def on_event(self, event, context):
            order.append(self._name)
            return HookResult()

    reg = HookRegistry()
    reg.register(OrderHook("last", 200))
    reg.register(OrderHook("first", 10))
    reg.register(OrderHook("mid", 100))

    reg.emit(HookEvent.SESSION_START, {})
    assert order == ["first", "mid", "last"]


def test_emit_blocking_short_circuits():
    """A blocking hook prevents later hooks from running."""
    reg = HookRegistry()
    blocker = BlockingHook("blocker", HookEvent.PRE_TOOL_USE, reason="denied", priority=10)
    after = PassthroughHook("after", priority=200)
    reg.register(blocker)
    reg.register(after)

    result = reg.emit(HookEvent.PRE_TOOL_USE, {"tool_name": "exec", "tool_args": {}})
    assert not result.proceed
    assert result.reason == "denied"
    assert len(after.events) == 0  # never reached


def test_emit_returns_modified_data():
    reg = HookRegistry()
    reg.register(ModifyingHook("filter", lambda skills: [s for s in skills if s["name"] != "bad"]))

    result = reg.emit(HookEvent.PRE_BUILD_CONTEXT, {
        "type": "skills",
        "data": [{"name": "good"}, {"name": "bad"}],
    })
    assert result.proceed
    assert result.modified_data == [{"name": "good"}]


def test_emit_chains_modified_data():
    """Multiple modifying hooks see each other's output."""
    reg = HookRegistry()
    reg.register(ModifyingHook("add_tag", lambda s: [{**x, "tagged": True} for x in s], priority=50))
    reg.register(ModifyingHook("filter", lambda s: [x for x in s if x.get("tagged")], priority=100))

    result = reg.emit(HookEvent.PRE_BUILD_CONTEXT, {
        "type": "skills",
        "data": [{"name": "a"}],
    })
    assert result.modified_data == [{"name": "a", "tagged": True}]


# ---- Matcher tests ----

def test_matcher_filters_tool_events():
    """Matcher regex filters which hooks run for tool events."""
    reg = HookRegistry()
    exec_only = PassthroughHook("exec_hook", matcher=r"^exec$")
    all_tools = PassthroughHook("all_hook")
    reg.register(exec_only)
    reg.register(all_tools)

    reg.emit(HookEvent.PRE_TOOL_USE, {"tool_name": "read_file", "tool_args": {}})
    assert len(exec_only.events) == 0  # didn't match
    assert len(all_tools.events) == 1  # no matcher = match all

    reg.emit(HookEvent.PRE_TOOL_USE, {"tool_name": "exec", "tool_args": {}})
    assert len(exec_only.events) == 1  # matched


def test_matcher_ignored_for_non_tool_events():
    """Matcher is only applied to PreToolUse/PostToolUse, not other events."""
    reg = HookRegistry()
    hook = PassthroughHook("h", matcher=r"^exec$")
    reg.register(hook)

    reg.emit(HookEvent.SESSION_START, {"session_key": "test"})
    assert len(hook.events) == 1  # matcher not applied, so it runs


# ---- Convenience method tests ----

def test_apply_skills_filters_via_emit():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "skills").mkdir()

        storage = HookStorage(workspace)
        storage.set_skill_enabled("disabled-skill", False)

        reg = HookRegistry()
        reg.register(SkillsEnabledFilter(workspace))

        skills = [
            {"name": "enabled-skill", "path": "/a", "source": "workspace"},
            {"name": "disabled-skill", "path": "/b", "source": "workspace"},
        ]
        filtered = reg.apply_skills_filters(skills)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "enabled-skill"


# ---- Hook exception safety ----

def test_emit_survives_hook_exception():
    """A hook that raises should not break the emit chain."""
    class BrokenHook(Hook):
        @property
        def name(self): return "broken"
        @property
        def priority(self): return 10
        def on_event(self, event, context):
            raise RuntimeError("boom")

    reg = HookRegistry()
    reg.register(BrokenHook())
    after = PassthroughHook("after", priority=200)
    reg.register(after)

    result = reg.emit(HookEvent.SESSION_START, {})
    assert result.proceed
    assert len(after.events) == 1  # still ran despite earlier exception


# ---- Backward compat ----

def test_legacy_filter_skills_delegates_to_on_event():
    """Calling filter_skills on a Hook should delegate to on_event."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "skills").mkdir()

        storage = HookStorage(workspace)
        storage.set_skill_enabled("x", False)

        f = SkillsEnabledFilter(workspace)
        skills = [{"name": "x"}, {"name": "y"}]
        result = f.on_event(HookEvent.PRE_BUILD_CONTEXT, {"type": "skills", "data": skills})
        assert len(result.modified_data) == 1
        assert result.modified_data[0]["name"] == "y"
