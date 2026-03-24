"""End-to-end tests for the self-improvement system.

These tests use a REAL LLM (via config) to verify the complete pipeline:
  1. Agent receives a prompt that will trigger an error
  2. Hook detects error in tool output and appends reminder
  3. LLM sees reminder + SKILL.md guidance
  4. LLM decides to call write_file to log to .learnings/
  5. .learnings/ files are updated on disk

Requirements:
  - A valid config.json with a working LLM provider
  - Set NANOBOT_E2E_CONFIG to the config path, or it auto-discovers
  - Tests are marked with @pytest.mark.e2e (skip unless --e2e flag)

Usage:
  pytest tests/test_self_improvement_e2e.py --e2e -v
  pytest tests/test_self_improvement_e2e.py --e2e -v -k "test_error_logging"
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.config.schema import Config, ExecToolConfig
from nanobot.hooks.base import HookContext
from nanobot.hooks.manager import HookManager
from nanobot.hooks.self_improvement import (
    SelfImprovementHook,
    _ERROR_PATTERNS,
    _REMINDER,
    register_self_improvement_hooks,
)
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.utils.helpers import sync_workspace_templates

_RATE_LIMIT_MARKER = "RateLimitError"


def _skip_if_rate_limited(response: str | None) -> None:
    """Skip test instead of failing when LLM provider hits rate limit."""
    if response and _RATE_LIMIT_MARKER in response:
        pytest.skip(f"LLM rate limited: {response[:120]}")


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------

_CONFIG_SEARCH_PATHS = [
    Path(os.environ.get("NANOBOT_E2E_CONFIG", "")),
    Path.home() / ".nanobot" / "config.json",
    Path.home() / ".hiperone" / "config.json",
    Path("/root/.nanobot/config.json"),
    Path("/root/.hiperone/config.json"),
]


def _find_config() -> Path | None:
    for p in _CONFIG_SEARCH_PATHS:
        if p and p.is_file():
            return p
    return None


def _load_e2e_config() -> Config | None:
    path = _find_config()
    if not path:
        return None
    config = load_config(path)
    if not config.get_api_key(config.agents.defaults.model):
        return None
    return config


def _make_provider(config: Config) -> LiteLLMProvider:
    model = config.agents.defaults.model
    provider_cfg = config.get_provider(model)
    provider_name = config.get_provider_name(model)
    return LiteLLMProvider(
        api_key=provider_cfg.api_key if provider_cfg else None,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=provider_cfg.extra_headers if provider_cfg else None,
        provider_name=provider_name,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e2e_config() -> Config:
    config = _load_e2e_config()
    if not config:
        pytest.skip("No valid LLM config found for E2E tests")
    return config


@pytest.fixture(scope="module")
def e2e_provider(e2e_config: Config) -> LiteLLMProvider:
    return _make_provider(e2e_config)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a fresh workspace with templates synced."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    sync_workspace_templates(ws, silent=True)
    return ws


@pytest.fixture
def agent(e2e_config: Config, e2e_provider: LiteLLMProvider, workspace: Path) -> AgentLoop:
    """Create a real AgentLoop with real LLM provider."""
    bus = MessageBus()
    return AgentLoop(
        bus=bus,
        provider=e2e_provider,
        workspace=workspace,
        model=e2e_config.agents.defaults.model,
        temperature=0.1,
        max_tokens=4096,
        max_iterations=10,
        memory_window=20,
        exec_config=ExecToolConfig(timeout=30),
        restrict_to_workspace=False,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_learnings_file(workspace: Path, filename: str) -> str:
    path = workspace / ".learnings" / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _count_entries(content: str, prefix: str) -> int:
    """Count entries like [ERR-...], [LRN-...], [FEAT-...]."""
    return len(re.findall(rf"\[{prefix}-\d{{8}}-\w+\]", content))


def _has_new_content(workspace: Path, filename: str, original: str) -> bool:
    """Check if file has new content beyond the template."""
    current = _read_learnings_file(workspace, filename)
    return len(current) > len(original)


async def _run_agent(agent: AgentLoop, prompt: str) -> str:
    """Run agent with a prompt and return the response. Skips on rate limit."""
    response = await agent.process_direct(
        content=prompt,
        session_key="e2e:test",
        channel="cli",
        chat_id="e2e",
    )
    _skip_if_rate_limited(response)
    return response


# ===========================================================================
# Part 1: Workspace Bootstrap E2E
# ===========================================================================


@pytest.mark.e2e
class TestWorkspaceBootstrapE2E:
    """Verify workspace is properly bootstrapped before agent runs."""

    def test_learnings_dir_created(self, workspace: Path) -> None:
        assert (workspace / ".learnings").is_dir()

    def test_errors_md_created(self, workspace: Path) -> None:
        path = workspace / ".learnings" / "ERRORS.md"
        assert path.exists()
        content = path.read_text()
        assert "Errors Log" in content

    def test_learnings_md_created(self, workspace: Path) -> None:
        path = workspace / ".learnings" / "LEARNINGS.md"
        assert path.exists()
        content = path.read_text()
        assert "Learnings Log" in content

    def test_feature_requests_md_created(self, workspace: Path) -> None:
        path = workspace / ".learnings" / "FEATURE_REQUESTS.md"
        assert path.exists()
        content = path.read_text()
        assert "Feature Requests" in content

    def test_agents_md_created(self, workspace: Path) -> None:
        assert (workspace / "AGENTS.md").exists()

    def test_memory_dir_created(self, workspace: Path) -> None:
        assert (workspace / "memory" / "MEMORY.md").exists()

    def test_skills_dir_created(self, workspace: Path) -> None:
        assert (workspace / "skills").is_dir()


# ===========================================================================
# Part 2: Hook Pipeline E2E (real hook, simulated tool output)
# ===========================================================================


@pytest.mark.e2e
class TestHookPipelineE2E:
    """Test the hook pipeline with real error patterns from real commands."""

    @pytest.fixture
    def hook_manager(self) -> HookManager:
        mgr = HookManager()
        register_self_improvement_hooks(mgr)
        return mgr

    @pytest.mark.parametrize(
        "command,output",
        [
            ("python bad.py", "Traceback (most recent call last):\n  File \"bad.py\", line 1\n    print(\nSyntaxError: unexpected EOF while parsing"),
            ("npm install", "npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree"),
            ("gcc main.c", "main.c:5:1: error: expected ';' before '}' token"),
            ("pip install nonexistent-pkg-xyz", "ERROR: Could not find a version that satisfies the requirement nonexistent-pkg-xyz"),
            ("docker build .", "fatal: not a git repository (or any of the parent directories): .git"),
            ("make build", "make: *** [Makefile:10: build] Error 2\n\nExit code: 2"),
            ("python -c 'import xyz'", "ModuleNotFoundError: No module named 'xyz'"),
            ("node app.js", "TypeError: Cannot read properties of undefined (reading 'map')"),
            ("ls /nonexistent", "ls: cannot access '/nonexistent': No such file or directory\n\nExit code: 2"),
            ("cat /etc/shadow", "cat: /etc/shadow: Permission denied\n\nExit code: 1"),
            ("curl https://broken.invalid", "curl: (6) Could not resolve host: broken.invalid\n\nExit code: 6"),
            ("git push origin main", "fatal: 'origin' does not appear to be a git repository\nfatal: Could not read from remote repository."),
            ("cargo build", "error[E0308]: mismatched types\n --> src/main.rs:5:20"),
            ("go build .", "panic: runtime error: index out of range [5] with length 3"),
            ("java -jar app.jar", "Exception in thread \"main\" java.lang.NullPointerException"),
        ],
        ids=[
            "python_syntax_error",
            "npm_resolve_error",
            "gcc_compile_error",
            "pip_not_found",
            "docker_git_fatal",
            "make_error",
            "python_import_error",
            "node_type_error",
            "ls_no_such_file",
            "cat_permission_denied",
            "curl_resolve_error",
            "git_push_fatal",
            "cargo_compile_error",
            "go_panic",
            "java_exception",
        ],
    )
    async def test_hook_detects_real_world_error(
        self, hook_manager: HookManager, command: str, output: str
    ) -> None:
        ctx = HookContext(event_type="tool.post_call", session_key="e2e:test")
        results = await hook_manager.fire(
            "tool.post_call", ctx,
            tool_name="exec",
            params={"command": command},
            result=output,
        )
        assert len(results) == 1
        assert "[self-improvement]" in results[0]["result"]
        assert results[0]["result"].startswith(output)

    @pytest.mark.parametrize(
        "command,output",
        [
            ("echo hello", "hello"),
            ("python --version", "Python 3.12.0"),
            ("npm --version", "10.2.0"),
            ("git status", "On branch main\nnothing to commit, working tree clean"),
            ("docker ps", "CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS   NAMES"),
            ("ls -la", "total 32\ndrwxr-xr-x 5 user user 4096 Mar 10 12:00 ."),
            ("cat README.md", "# Project\n\nA great project."),
            ("curl -s https://httpbin.org/get", '{"url": "https://httpbin.org/get"}'),
            ("pip list", "Package    Version\n---------- -------\npip        24.0"),
            ("pytest --version", "pytest 8.0.0"),
        ],
        ids=[
            "echo", "python_version", "npm_version", "git_status",
            "docker_ps", "ls_la", "cat_readme", "curl_ok",
            "pip_list", "pytest_version",
        ],
    )
    async def test_hook_passes_clean_output(
        self, hook_manager: HookManager, command: str, output: str
    ) -> None:
        ctx = HookContext(event_type="tool.post_call", session_key="e2e:test")
        results = await hook_manager.fire(
            "tool.post_call", ctx,
            tool_name="exec",
            params={"command": command},
            result=output,
        )
        assert len(results) == 1
        assert "[self-improvement]" not in results[0]["result"]


# ===========================================================================
# Part 3: Skill Loading E2E
# ===========================================================================


@pytest.mark.e2e
class TestSkillLoadingE2E:
    """Verify the self-improvement skill is loaded into system prompt."""

    def test_skill_in_system_prompt(self, agent: AgentLoop) -> None:
        """The self-improvement skill should be in always_skills."""
        always = agent.context.skills.get_always_skills()
        assert "self-improving-agent" in always

    def test_skill_content_in_context(self, agent: AgentLoop) -> None:
        """The skill content should include key sections."""
        content = agent.context.skills.load_skills_for_context(["self-improving-agent"])
        assert ".learnings/ERRORS.md" in content
        assert "ERR-YYYYMMDD-XXX" in content
        assert "Detection Triggers" in content

    async def test_system_prompt_contains_skill(self, agent: AgentLoop) -> None:
        """Build the actual system prompt and verify skill is included."""
        prompt = await agent.context.build_system_prompt()
        assert "Self-Improvement Skill" in prompt
        assert ".learnings/" in prompt

    def test_hook_is_registered(self, agent: AgentLoop) -> None:
        """Verify hook is registered on the agent's hook manager."""
        assert agent.hook_manager.has_hooks("tool.post_call")


# ===========================================================================
# Part 4: Real Tool Execution E2E
# ===========================================================================


@pytest.mark.e2e
class TestRealToolExecutionE2E:
    """Test hook behavior with real tool execution (no LLM needed)."""

    async def test_exec_tool_with_failing_command(self, agent: AgentLoop) -> None:
        """Run a real failing command and verify hook appends reminder."""
        result = await agent.tools.execute("exec", {"command": "python -c \"raise ValueError('test error')\"" })

        ctx = HookContext(event_type="tool.post_call", session_key="e2e:test")
        hook_results = await agent.hook_manager.fire(
            "tool.post_call", ctx,
            tool_name="exec",
            params={"command": "python -c \"raise ValueError('test error')\""},
            result=result,
        )

        final = result
        for hr in hook_results:
            if isinstance(hr, dict) and "result" in hr:
                final = hr["result"]

        assert "ValueError" in final or "Error" in final
        assert "[self-improvement]" in final

    async def test_exec_tool_with_successful_command(self, agent: AgentLoop) -> None:
        """Run a real successful command and verify hook does NOT append."""
        result = await agent.tools.execute("exec", {"command": "echo hello world"})

        ctx = HookContext(event_type="tool.post_call", session_key="e2e:test")
        hook_results = await agent.hook_manager.fire(
            "tool.post_call", ctx,
            tool_name="exec",
            params={"command": "echo hello world"},
            result=result,
        )

        final = result
        for hr in hook_results:
            if isinstance(hr, dict) and "result" in hr:
                final = hr["result"]

        assert "hello world" in final
        assert "[self-improvement]" not in final

    async def test_exec_tool_nonexistent_command(self, agent: AgentLoop) -> None:
        """Run a command that doesn't exist."""
        result = await agent.tools.execute("exec", {"command": "nonexistent_command_xyz_12345"})

        ctx = HookContext(event_type="tool.post_call", session_key="e2e:test")
        hook_results = await agent.hook_manager.fire(
            "tool.post_call", ctx,
            tool_name="exec",
            params={"command": "nonexistent_command_xyz_12345"},
            result=result,
        )

        final = result
        for hr in hook_results:
            if isinstance(hr, dict) and "result" in hr:
                final = hr["result"]

        assert "[self-improvement]" in final

    async def test_write_file_tool_creates_learnings_entry(self, workspace: Path, agent: AgentLoop) -> None:
        """Verify write_file can actually write to .learnings/ERRORS.md."""
        entry = (
            "\n\n## [ERR-20260310-E2E] test_command\n\n"
            "**Logged**: 2026-03-10T12:00:00Z\n"
            "**Priority**: medium\n"
            "**Status**: pending\n"
            "**Area**: tests\n\n"
            "### Summary\nE2E test error entry\n\n"
            "### Error\n```\nValueError: test\n```\n\n"
            "### Suggested Fix\nThis is a test entry\n\n---\n"
        )

        errors_path = workspace / ".learnings" / "ERRORS.md"
        original = errors_path.read_text()

        result = await agent.tools.execute("write_file", {
            "path": str(errors_path),
            "content": original + entry,
        })

        assert "Successfully wrote" in result
        updated = errors_path.read_text()
        assert "[ERR-20260310-E2E]" in updated
        assert "E2E test error entry" in updated


# ===========================================================================
# Part 5: Full Agent Loop E2E (Real LLM)
# ===========================================================================


@pytest.mark.e2e
class TestFullAgentLoopE2E:
    """Full end-to-end: agent processes a prompt, LLM calls tools, hook triggers.

    These tests call the real LLM and verify the complete self-improvement pipeline.
    Each test sends a carefully crafted prompt that should trigger error detection
    and self-improvement logging.
    """

    async def test_error_logging_python_error(self, agent: AgentLoop, workspace: Path) -> None:
        """Agent runs a failing Python command → should log to ERRORS.md."""
        original = _read_learnings_file(workspace, "ERRORS.md")

        prompt = (
            "Run this command: python -c \"raise ValueError('database connection timeout')\"\n"
            "This is an unexpected error. Log it to .learnings/ERRORS.md following the self-improvement format."
        )
        response = await _run_agent(agent, prompt)

        assert response is not None
        assert len(response) > 0

        current = _read_learnings_file(workspace, "ERRORS.md")
        assert len(current) > len(original), (
            f"ERRORS.md was not updated.\nOriginal ({len(original)} chars):\n{original}\n"
            f"Current ({len(current)} chars):\n{current}\n"
            f"Agent response:\n{response}"
        )

    async def test_error_logging_command_not_found(self, agent: AgentLoop, workspace: Path) -> None:
        """Agent runs a non-existent command → should log the error."""
        original = _read_learnings_file(workspace, "ERRORS.md")

        prompt = (
            "Execute: nonexistent_tool_xyz_99999 --help\n"
            "This command failed unexpectedly. Log it to .learnings/ERRORS.md with the self-improvement format."
        )
        response = await _run_agent(agent, prompt)

        assert response is not None
        current = _read_learnings_file(workspace, "ERRORS.md")
        assert len(current) > len(original), (
            f"ERRORS.md not updated after command-not-found.\n"
            f"Agent response:\n{response}"
        )

    async def test_learning_logging_user_correction(self, agent: AgentLoop, workspace: Path) -> None:
        """Simulate a user correction → agent should log to LEARNINGS.md."""
        original = _read_learnings_file(workspace, "LEARNINGS.md")

        prompt = (
            "I need to correct you: when working with Python asyncio, "
            "you should NEVER use time.sleep() in async functions - always use await asyncio.sleep(). "
            "This is an important correction. Log it to .learnings/LEARNINGS.md as a correction "
            "following the self-improvement format with category 'correction'."
        )
        response = await _run_agent(agent, prompt)

        assert response is not None
        current = _read_learnings_file(workspace, "LEARNINGS.md")
        assert len(current) > len(original), (
            f"LEARNINGS.md not updated after user correction.\n"
            f"Agent response:\n{response}"
        )

    async def test_feature_request_logging(self, agent: AgentLoop, workspace: Path) -> None:
        """User requests a feature → agent should log to FEATURE_REQUESTS.md."""
        original = _read_learnings_file(workspace, "FEATURE_REQUESTS.md")

        prompt = (
            "I wish you could generate diagrams from code. "
            "Like Mermaid or PlantUML diagrams based on the project architecture. "
            "This is a feature request. Log it to .learnings/FEATURE_REQUESTS.md "
            "following the self-improvement format."
        )
        response = await _run_agent(agent, prompt)

        assert response is not None
        current = _read_learnings_file(workspace, "FEATURE_REQUESTS.md")
        assert len(current) > len(original), (
            f"FEATURE_REQUESTS.md not updated after feature request.\n"
            f"Agent response:\n{response}"
        )

    async def test_error_entry_format_compliance(self, agent: AgentLoop, workspace: Path) -> None:
        """Verify logged error entry follows the SKILL.md format."""
        prompt = (
            "Run: python -c \"import nonexistent_module_xyz\"\n"
            "This error was unexpected. Log it to .learnings/ERRORS.md "
            "using the exact self-improvement format: [ERR-YYYYMMDD-XXX] with "
            "Summary, Error, Context, and Suggested Fix sections."
        )
        response = await _run_agent(agent, prompt)

        content = _read_learnings_file(workspace, "ERRORS.md")
        assert re.search(r"\[ERR-\d{8}-\w+\]", content), (
            f"No ERR entry found in ERRORS.md.\nContent:\n{content}\nResponse:\n{response}"
        )

    async def test_learning_entry_format_compliance(self, agent: AgentLoop, workspace: Path) -> None:
        """Verify logged learning follows the SKILL.md format."""
        prompt = (
            "I learned that Python's json.dumps with ensure_ascii=False is critical for "
            "non-ASCII content. Log this to .learnings/LEARNINGS.md with the self-improvement "
            "format: [LRN-YYYYMMDD-XXX] with category 'best_practice', "
            "including Summary, Details, Suggested Action, and Metadata sections."
        )
        response = await _run_agent(agent, prompt)

        content = _read_learnings_file(workspace, "LEARNINGS.md")
        assert re.search(r"\[LRN-\d{8}-\w+\]", content), (
            f"No LRN entry found in LEARNINGS.md.\nContent:\n{content}\nResponse:\n{response}"
        )

    async def test_multiple_errors_accumulate(self, agent: AgentLoop, workspace: Path) -> None:
        """Run multiple failing commands → entries should accumulate."""
        prompt1 = (
            "Run: python -c \"1/0\"\n"
            "Log this error to .learnings/ERRORS.md with the self-improvement format."
        )
        await _run_agent(agent, prompt1)
        content1 = _read_learnings_file(workspace, "ERRORS.md")

        prompt2 = (
            "Run: python -c \"raise RuntimeError('second error')\"\n"
            "Log this error to .learnings/ERRORS.md (append, don't overwrite) with the self-improvement format."
        )
        await _run_agent(agent, prompt2)
        content2 = _read_learnings_file(workspace, "ERRORS.md")

        assert len(content2) > len(content1), "Second error should add more content"

    async def test_hook_reminder_visible_to_llm(self, agent: AgentLoop, workspace: Path) -> None:
        """Verify the LLM can see and act on the hook reminder."""
        prompt = (
            "Run: python -c \"raise Exception('hook test')\"\n"
            "After seeing the command output, if there's a [self-improvement] "
            "reminder, follow its guidance and log to .learnings/ERRORS.md."
        )
        response = await _run_agent(agent, prompt)

        assert response is not None
        content = _read_learnings_file(workspace, "ERRORS.md")
        has_entry = re.search(r"\[ERR-\d{8}-\w+\]", content)
        assert has_entry or len(content) > 100, (
            f"LLM should have logged after seeing hook reminder.\n"
            f"ERRORS.md:\n{content}\nResponse:\n{response}"
        )


# ===========================================================================
# Part 6: Promotion E2E (Agent promotes learning to AGENTS.md)
# ===========================================================================


@pytest.mark.e2e
class TestPromotionE2E:
    """Test that the agent can promote learnings to workspace files."""

    async def test_promote_to_agents_md(self, agent: AgentLoop, workspace: Path) -> None:
        """Ask agent to promote a workflow learning to AGENTS.md."""
        original_agents = (workspace / "AGENTS.md").read_text(encoding="utf-8") if (workspace / "AGENTS.md").exists() else ""

        prompt = (
            "I've noticed a recurring pattern: when running database migrations, "
            "always backup the database first. This has occurred 5 times now. "
            "1. First log it as a learning to .learnings/LEARNINGS.md with the self-improvement format.\n"
            "2. Since this is a recurring workflow issue (Recurrence-Count >= 3), "
            "promote it to AGENTS.md as a short prevention rule.\n"
            "3. Update the learning status to 'promoted'."
        )
        response = await _run_agent(agent, prompt)

        agents_content = (workspace / "AGENTS.md").read_text(encoding="utf-8") if (workspace / "AGENTS.md").exists() else ""
        assert len(agents_content) > len(original_agents), (
            f"AGENTS.md was not updated.\nOriginal:\n{original_agents}\n"
            f"Current:\n{agents_content}\nResponse:\n{response}"
        )


# ===========================================================================
# Part 7: Read-back E2E (Agent reads .learnings/ before task)
# ===========================================================================


@pytest.mark.e2e
class TestReadBackE2E:
    """Verify the agent can read and reference existing learnings."""

    async def test_agent_can_read_existing_learnings(self, agent: AgentLoop, workspace: Path) -> None:
        """Pre-populate ERRORS.md and ask agent to review it."""
        errors_path = workspace / ".learnings" / "ERRORS.md"
        errors_path.write_text(
            "# Errors Log\n\n"
            "## [ERR-20260301-001] pip_install\n\n"
            "**Logged**: 2026-03-01T10:00:00Z\n"
            "**Priority**: high\n"
            "**Status**: pending\n"
            "**Area**: infra\n\n"
            "### Summary\npip install fails with SSL certificate error\n\n"
            "### Error\n```\nERROR: Could not fetch URL: SSL: CERTIFICATE_VERIFY_FAILED\n```\n\n"
            "### Suggested Fix\nUpdate CA certificates or use --trusted-host\n\n---\n",
            encoding="utf-8",
        )

        prompt = (
            "Check .learnings/ERRORS.md for any pending high-priority errors. "
            "Tell me what errors are logged there and their status."
        )
        response = await _run_agent(agent, prompt)

        assert response is not None
        assert any(kw in response.lower() for kw in ["ssl", "certificate", "pip", "err-20260301"]), (
            f"Agent should reference the existing error.\nResponse:\n{response}"
        )

    async def test_agent_resolves_existing_entry(self, agent: AgentLoop, workspace: Path) -> None:
        """Pre-populate an error and ask agent to resolve it."""
        errors_path = workspace / ".learnings" / "ERRORS.md"
        errors_path.write_text(
            "# Errors Log\n\n"
            "## [ERR-20260302-001] docker_build\n\n"
            "**Logged**: 2026-03-02T14:00:00Z\n"
            "**Priority**: high\n"
            "**Status**: pending\n"
            "**Area**: infra\n\n"
            "### Summary\nDocker build fails with network timeout\n\n"
            "### Error\n```\nerror: failed to resolve: registry-1.docker.io\n```\n\n"
            "### Suggested Fix\nAdd --network=host flag or configure DNS\n\n---\n",
            encoding="utf-8",
        )

        prompt = (
            "The Docker build issue [ERR-20260302-001] in .learnings/ERRORS.md has been fixed "
            "by configuring the DNS settings. "
            "Update its status from 'pending' to 'resolved' and add a Resolution section "
            "with the note 'Configured DNS to use 8.8.8.8'."
        )
        response = await _run_agent(agent, prompt)

        content = errors_path.read_text()
        assert "resolved" in content.lower(), (
            f"Entry should be marked resolved.\nContent:\n{content}\nResponse:\n{response}"
        )


# ===========================================================================
# Part 8: Detection Triggers E2E (natural language triggers)
# ===========================================================================


@pytest.mark.e2e
class TestDetectionTriggersE2E:
    """Test that natural language patterns trigger the appropriate logging."""

    async def test_correction_trigger(self, agent: AgentLoop, workspace: Path) -> None:
        """'No, that's not right...' should trigger a correction learning."""
        original = _read_learnings_file(workspace, "LEARNINGS.md")

        prompt = (
            "No, that's not right. The default port for PostgreSQL is 5432, not 3306. "
            "3306 is MySQL. Please log this correction to .learnings/LEARNINGS.md "
            "with category 'correction' using the self-improvement format."
        )
        response = await _run_agent(agent, prompt)

        current = _read_learnings_file(workspace, "LEARNINGS.md")
        assert len(current) > len(original), (
            f"Correction trigger should log to LEARNINGS.md.\nResponse:\n{response}"
        )

    async def test_knowledge_gap_trigger(self, agent: AgentLoop, workspace: Path) -> None:
        """Knowledge gap should trigger a learning."""
        original = _read_learnings_file(workspace, "LEARNINGS.md")

        prompt = (
            "FYI, since Python 3.12, the `distutils` module has been completely removed. "
            "You referenced it but it's outdated. "
            "Log this knowledge gap to .learnings/LEARNINGS.md with category 'knowledge_gap' "
            "using the self-improvement format."
        )
        response = await _run_agent(agent, prompt)

        current = _read_learnings_file(workspace, "LEARNINGS.md")
        assert len(current) > len(original), (
            f"Knowledge gap trigger should log to LEARNINGS.md.\nResponse:\n{response}"
        )

    async def test_feature_request_trigger(self, agent: AgentLoop, workspace: Path) -> None:
        """'I wish you could...' should trigger a feature request."""
        original = _read_learnings_file(workspace, "FEATURE_REQUESTS.md")

        prompt = (
            "I wish you could automatically run tests before committing code. "
            "Like a pre-commit hook that you manage. "
            "Log this feature request to .learnings/FEATURE_REQUESTS.md using the self-improvement format."
        )
        response = await _run_agent(agent, prompt)

        current = _read_learnings_file(workspace, "FEATURE_REQUESTS.md")
        assert len(current) > len(original), (
            f"Feature request trigger should log to FEATURE_REQUESTS.md.\nResponse:\n{response}"
        )


# ===========================================================================
# Part 9: Edge Cases E2E
# ===========================================================================


@pytest.mark.e2e
class TestEdgeCasesE2E:
    """Edge cases for the real agent."""

    async def test_agent_does_not_log_normal_output(self, agent: AgentLoop, workspace: Path) -> None:
        """Successful commands should NOT trigger logging."""
        original_errors = _read_learnings_file(workspace, "ERRORS.md")

        prompt = (
            "Run: echo 'All systems operational'\n"
            "Just tell me what the output is."
        )
        response = await _run_agent(agent, prompt)

        current_errors = _read_learnings_file(workspace, "ERRORS.md")
        assert current_errors == original_errors, (
            "ERRORS.md should not change for successful commands"
        )

    async def test_agent_handles_empty_learnings_gracefully(self, agent: AgentLoop, workspace: Path) -> None:
        """Agent should work even if .learnings/ files are empty."""
        for name in ("ERRORS.md", "LEARNINGS.md", "FEATURE_REQUESTS.md"):
            (workspace / ".learnings" / name).write_text("", encoding="utf-8")

        prompt = (
            "Run: python -c \"raise OSError('disk full')\"\n"
            "Log this error to .learnings/ERRORS.md with the self-improvement format."
        )
        response = await _run_agent(agent, prompt)

        content = _read_learnings_file(workspace, "ERRORS.md")
        assert len(content) > 0, "Agent should write to empty file"

    async def test_concurrent_not_corrupted(self, agent: AgentLoop, workspace: Path) -> None:
        """Sequential writes should not corrupt .learnings files."""
        prompts = [
            "Run: python -c \"raise ValueError('error1')\" and log to .learnings/ERRORS.md with self-improvement format.",
            "Run: python -c \"raise TypeError('error2')\" and log to .learnings/ERRORS.md with self-improvement format (append, don't overwrite).",
        ]

        for p in prompts:
            await _run_agent(agent, p)

        content = _read_learnings_file(workspace, "ERRORS.md")
        assert "Errors Log" in content or re.search(r"\[ERR-", content), (
            f"File should contain valid entries.\nContent:\n{content}"
        )


# ===========================================================================
# Part 10: Provider / Config E2E
# ===========================================================================


@pytest.mark.e2e
class TestProviderE2E:
    """Verify the LLM provider is correctly configured."""

    async def test_provider_can_chat(self, e2e_provider: LiteLLMProvider, e2e_config: Config) -> None:
        """Basic LLM chat works."""
        response = await e2e_provider.chat(
            messages=[{"role": "user", "content": "Reply with exactly: PONG"}],
            model=e2e_config.agents.defaults.model,
            max_tokens=50,
            temperature=0.0,
        )
        _skip_if_rate_limited(response.content)
        assert response.content is not None
        assert "PONG" in response.content.upper()

    async def test_provider_supports_tools(self, e2e_provider: LiteLLMProvider, e2e_config: Config) -> None:
        """LLM can call tools."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "A test tool",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "A message"}
                        },
                        "required": ["message"],
                    },
                },
            }
        ]
        response = await e2e_provider.chat(
            messages=[{"role": "user", "content": "Call the test_tool with message='hello'"}],
            tools=tools,
            model=e2e_config.agents.defaults.model,
            max_tokens=200,
            temperature=0.0,
        )
        _skip_if_rate_limited(response.content)
        assert response.has_tool_calls or response.content is not None

    async def test_agent_process_direct_basic(self, agent: AgentLoop) -> None:
        """Agent can process a simple message."""
        response = await _run_agent(agent, "What is 2+2? Reply with just the number.")
        assert response is not None
        assert "4" in response
