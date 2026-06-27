from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.cron.types import CronJob, CronJobState, CronSchedule
from nanobot.session.manager import Session


async def _dispatch(raw: str, *, loop, session: Session | None = None):
    router = CommandRouter()
    register_builtin_commands(router)
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    ctx = CommandContext(
        msg=msg,
        session=session or Session("cli:direct"),
        key="cli:direct",
        raw=raw,
        loop=loop,
    )
    return await router.dispatch(ctx)


# --------------------------------------------------------------------------- #
# sessions / resume / fork
# --------------------------------------------------------------------------- #


class _FakeSessions:
    def __init__(self) -> None:
        self.listed = [
            {"key": "cli:direct", "title": "Current", "updated_at": "2026-06-13T10:00"},
            {"key": "cli:older", "title": "Older", "updated_at": "2026-06-10T10:00"},
        ]
        self.files = {
            "cli:older": {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]},
        }

    def list_sessions(self):
        return list(self.listed)

    def read_session_file(self, key: str):
        return self.files.get(key)

    def get_or_create(self, key: str) -> Session:
        return Session(key)

    def fork_session_before_user_index(self, source_key, target_key, before):
        forked = Session(target_key)
        forked.messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        return forked


def _sessions_loop() -> SimpleNamespace:
    return SimpleNamespace(sessions=_FakeSessions())


@pytest.mark.asyncio
async def test_sessions_lists_and_marks_current():
    result = await _dispatch("/sessions", loop=_sessions_loop())
    assert result is not None
    assert "cli:older" in result.content
    assert "→ `cli:direct`" in result.content


@pytest.mark.asyncio
async def test_resume_emits_switch_metadata():
    result = await _dispatch("/resume older", loop=_sessions_loop())
    assert result is not None
    assert result.metadata.get("cli_resume_session") == "older"
    assert "Resumed `cli:older`" in result.content


@pytest.mark.asyncio
async def test_resume_unknown_session():
    result = await _dispatch("/resume missing", loop=_sessions_loop())
    assert result is not None
    assert "cli_resume_session" not in result.metadata
    assert "No session" in result.content


@pytest.mark.asyncio
async def test_fork_creates_branch_and_switches():
    session = Session("cli:direct")
    session.messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    result = await _dispatch("/fork", loop=_sessions_loop(), session=session)
    assert result is not None
    assert result.metadata.get("cli_resume_session", "").startswith("fork-")
    assert "Forked" in result.content


# --------------------------------------------------------------------------- #
# cron
# --------------------------------------------------------------------------- #


class _FakeCron:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.jobs = [
            CronJob(
                id="job1",
                name="Daily report",
                enabled=True,
                schedule=CronSchedule(kind="cron", expr="0 9 * * *"),
                state=CronJobState(next_run_at_ms=0),
            )
        ]

    def list_jobs(self, include_disabled: bool = False):
        return self.jobs

    def enable_job(self, job_id: str, enabled: bool = True):
        self.calls.append(("enable", job_id, enabled))
        return self.jobs[0] if job_id == "job1" else None

    def remove_job(self, job_id: str):
        return "removed" if job_id == "job1" else "not_found"

    async def run_job(self, job_id: str, force: bool = False):
        self.calls.append(("run", job_id, force))
        return job_id == "job1"


@pytest.mark.asyncio
async def test_cron_list():
    result = await _dispatch("/cron", loop=SimpleNamespace(cron_service=_FakeCron()))
    assert result is not None
    assert "Daily report" in result.content
    assert "0 9 * * *" in result.content


@pytest.mark.asyncio
async def test_cron_disable_calls_service():
    cron = _FakeCron()
    result = await _dispatch("/cron disable job1", loop=SimpleNamespace(cron_service=cron))
    assert result is not None
    assert ("enable", "job1", False) in cron.calls
    assert "disabled" in result.content


@pytest.mark.asyncio
async def test_cron_remove_and_run():
    cron = _FakeCron()
    loop = SimpleNamespace(cron_service=cron)
    removed = await _dispatch("/cron remove job1", loop=loop)
    assert "Removed cron job" in removed.content
    ran = await _dispatch("/cron run job1", loop=loop)
    assert "Triggered cron job" in ran.content
    assert ("run", "job1", True) in cron.calls


@pytest.mark.asyncio
async def test_cron_unavailable():
    result = await _dispatch("/cron", loop=SimpleNamespace(cron_service=None))
    assert result is not None
    assert "not available" in result.content


# --------------------------------------------------------------------------- #
# skill enable / disable
# --------------------------------------------------------------------------- #


class _FakeSkills:
    def __init__(self) -> None:
        self.disabled_skills: set[str] = set()

    def list_skills(self, filter_unavailable: bool = True):
        return [{"name": "summarize"}, {"name": "weather"}]

    def _get_skill_description(self, name: str) -> str:
        return f"desc {name}"


def _skills_loop() -> SimpleNamespace:
    return SimpleNamespace(context=SimpleNamespace(skills=_FakeSkills()))


@pytest.mark.asyncio
async def test_skill_disable_toggles_runtime_and_persists(monkeypatch):
    saved: dict = {}
    monkeypatch.setattr(
        "nanobot.config.loader.load_config",
        lambda *a, **k: SimpleNamespace(
            agents=SimpleNamespace(defaults=SimpleNamespace(disabled_skills=[]))
        ),
    )
    monkeypatch.setattr(
        "nanobot.config.loader.save_config",
        lambda config, *a, **k: saved.update(skills=list(config.agents.defaults.disabled_skills)),
    )
    loop = _skills_loop()
    result = await _dispatch("/skill disable summarize", loop=loop)
    assert result is not None
    assert "summarize" in loop.context.skills.disabled_skills
    assert "disabled" in result.content
    assert saved["skills"] == ["summarize"]


@pytest.mark.asyncio
async def test_skill_enable_unknown():
    result = await _dispatch("/skill enable nope", loop=_skills_loop())
    assert result is not None
    assert "Unknown skill" in result.content


@pytest.mark.asyncio
async def test_skill_list_shows_toggle_hint():
    result = await _dispatch("/skill", loop=_skills_loop())
    assert result is not None
    assert "summarize" in result.content
    assert "Toggle with" in result.content


# --------------------------------------------------------------------------- #
# usage (cumulative by source)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_usage_shows_cumulative_by_source(monkeypatch):
    monkeypatch.setattr(
        "nanobot.webui.token_usage.read_token_usage_state",
        lambda: {
            "days": {
                "2026-06-13": {
                    "total_tokens": 300,
                    "requests": 3,
                    "sources": {
                        "user": {"total_tokens": 200},
                        "cron": {"total_tokens": 100},
                    },
                }
            }
        },
    )
    loop = SimpleNamespace(_last_usage={"prompt_tokens": 10, "total_tokens": 15})
    result = await _dispatch("/usage", loop=loop)
    assert result is not None
    assert "Cumulative:" in result.content
    assert "300" in result.content
    assert "user: 200" in result.content
    assert "cron: 100" in result.content


# --------------------------------------------------------------------------- #
# mcp add / remove
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_mcp_add_writes_config_and_reloads(monkeypatch):
    servers: dict = {}
    fake_config = SimpleNamespace(tools=SimpleNamespace(mcp_servers=servers))
    saved: list = []
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda *a, **k: fake_config)
    monkeypatch.setattr("nanobot.config.loader.save_config", lambda c, *a, **k: saved.append(c))

    async def _fake_reload(state, registry):
        return {"connected": ["weather"], "message": "MCP config reloaded."}

    monkeypatch.setattr("nanobot.agent.tools.mcp.reload_servers", _fake_reload)

    loop = SimpleNamespace(tools={})
    result = await _dispatch("/mcp add weather npx -y weather-mcp", loop=loop)
    assert result is not None
    assert "weather" in servers
    assert servers["weather"].command == "npx"
    assert servers["weather"].args == ["-y", "weather-mcp"]
    assert saved  # persisted
    assert "connected" in result.content


@pytest.mark.asyncio
async def test_mcp_add_http_url(monkeypatch):
    servers: dict = {}
    monkeypatch.setattr(
        "nanobot.config.loader.load_config",
        lambda *a, **k: SimpleNamespace(tools=SimpleNamespace(mcp_servers=servers)),
    )
    monkeypatch.setattr("nanobot.config.loader.save_config", lambda c, *a, **k: None)

    async def _fake_reload(state, registry):
        return {"connected": [], "message": "ok"}

    monkeypatch.setattr("nanobot.agent.tools.mcp.reload_servers", _fake_reload)

    result = await _dispatch("/mcp add docs https://example.com/mcp", loop=SimpleNamespace(tools={}))
    assert servers["docs"].url == "https://example.com/mcp"
    assert "configured" in result.content


@pytest.mark.asyncio
async def test_mcp_remove_unknown(monkeypatch):
    monkeypatch.setattr(
        "nanobot.config.loader.load_config",
        lambda *a, **k: SimpleNamespace(tools=SimpleNamespace(mcp_servers={})),
    )
    result = await _dispatch("/mcp remove ghost", loop=SimpleNamespace(tools={}))
    assert "No MCP server" in result.content
