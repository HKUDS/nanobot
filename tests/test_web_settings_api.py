from contextlib import ExitStack
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from nanobot.agent.context import ContextBuilder
from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore
from nanobot.session.manager import Session, SessionManager
from nanobot.web.server import create_app


class _FakeAgentLoop:
    def __init__(self, *args, **kwargs) -> None:
        self.workspace = kwargs["workspace"]
        self.context = ContextBuilder(kwargs["workspace"])
        self.provider = object()
        self.model = kwargs["model"]
        self.web_search_config = kwargs["web_search_config"]
        self.subagents = type(
            "Subagents",
            (),
            {
                "provider": object(),
                "model": kwargs["model"],
                "web_search_config": kwargs["web_search_config"],
            },
        )()
        self.memory_consolidator = type(
            "MemoryConsolidator",
            (),
            {
                "provider": object(),
                "model": kwargs["model"],
                "context_window_tokens": kwargs["context_window_tokens"],
            },
        )()
        self.tools = {}

    async def _connect_mcp(self) -> None:
        return None

    async def close_mcp(self) -> None:
        return None


class _FakeCronService:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self._store = CronStore(
            jobs=[
                CronJob(
                    id="job-1",
                    name="Daily review",
                    enabled=True,
                    schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="Asia/Shanghai"),
                    payload=CronPayload(
                        kind="agent_turn",
                        message="Review HEARTBEAT",
                        assistant_id="default",
                        topic_session_id="web:default:topic-1",
                    ),
                    state=CronJobState(next_run_at_ms=1_800_000_000_000, last_status="ok"),
                    created_at_ms=1_700_000_000_000,
                    updated_at_ms=1_700_000_000_000,
                )
            ]
        )

    async def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def _load_store(self) -> CronStore:
        return self._store

    def _save_store(self) -> None:
        return None

    def remove_job(self, job_id: str) -> bool:
        before = len(self._store.jobs)
        self._store.jobs = [job for job in self._store.jobs if job.id != job_id]
        return len(self._store.jobs) < before

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        return self._store.jobs


def _create_test_app(config: Config, *, cron_service=_FakeCronService):
    with ExitStack() as stack:
        stack.enter_context(patch("nanobot.cli.commands._load_runtime_config", return_value=config))
        stack.enter_context(patch("nanobot.cli.commands._make_provider", return_value=object()))
        stack.enter_context(patch("nanobot.utils.helpers.sync_workspace_templates", side_effect=lambda path: path))
        stack.enter_context(patch("nanobot.bus.queue.MessageBus"))
        stack.enter_context(patch("nanobot.agent.loop.AgentLoop", _FakeAgentLoop))
        if cron_service is not None:
            stack.enter_context(patch("nanobot.cron.service.CronService", cron_service))
        return create_app()


def test_settings_endpoint_returns_workspace_templates_skills_and_runtime_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "skills" / "local-skill").mkdir(parents=True)
    (workspace / "skills" / "local-skill" / "SKILL.md").write_text("---\ndescription: local skill\n---", encoding="utf-8")

    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(workspace)}},
            "tools": {
                "mcpServers": {
                    "github": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "enabledTools": ["*"],
                    }
                }
            },
        }
    )

    app = _create_test_app(config)

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()

    assert data["workspace"] == str(workspace)
    pharmacogenomics = next(item for item in data["templates"] if item["id"] == "pharmacogenomics")
    assert pharmacogenomics["name"] == "Pharmacogenomics Analyst"
    assert pharmacogenomics["required_mcps"] == ["exa"]

    assert any(
        item["name"] == "local-skill"
        and item["source"] == "workspace"
        and item["description"] == "local skill"
        and item["always"] is False
        for item in data["skills"]
    )
    assert any(item["name"] == "memory" and item["always"] is True for item in data["skills"])
    assert data["cron_jobs"][0]["name"] == "Daily review"
    assert data["cron_jobs"][0]["topic_id"] == "web:default:topic-1"
    assert data["cron_jobs"][0]["cron_expr"] == "0 9 * * *"
    assert data["mcp_servers"][0]["name"] == "github"


def test_create_session_persists_template_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(workspace)}},
        }
    )

    app = _create_test_app(config)

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions",
            json={"session_id": "web:pgx", "template_id": "pharmacogenomics"},
        )
        assert response.status_code == 200

        session_response = client.get("/api/sessions/web:pgx")

    assert session_response.status_code == 200
    data = session_response.json()
    assert data["metadata"]["template_id"] == "pharmacogenomics"
    assert data["metadata"]["template"]["name"] == "Pharmacogenomics Analyst"


def test_agent_topic_flow_and_agent_updates_propagate(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(workspace), "model": "openai/gpt-4.1-mini"}},
        }
    )

    app = _create_test_app(config)

    with TestClient(app) as client:
        response = client.post(
            "/api/agents",
            json={"assistant_id": "pgx", "template_id": "pharmacogenomics"},
        )
        assert response.status_code == 200
        agent = response.json()
        assert agent["name"] == "Pharmacogenomics Analyst"
        assert agent["model"] == "openai/gpt-4.1-mini"
        assert "memory" not in agent["enabled_skills"]
        assert "weather" in agent["enabled_skills"]

        topic_response = client.post(
            "/api/agents/pgx/topics",
            json={"name": "Clopidogrel Topic"},
        )
        assert topic_response.status_code == 200
        topic = topic_response.json()
        assert topic["assistant_id"] == "pgx"
        assert topic["name"] == "Clopidogrel Topic"

        update_response = client.patch(
            "/api/agents/pgx",
            json={
                "enabled_skills": ["memory", "literature-review", "citation-check"],
                "enabled_mcps": ["exa"],
                "agent_identity": "You are a stricter pharmacogenomics reviewer.",
                "user_identity": "The user is a clinical pharmacologist.",
                "system_prompt": "Always produce a literature-backed summary.",
            },
        )
        assert update_response.status_code == 200

        session_response = client.get(f"/api/sessions/{topic['session_id']}")
        assert session_response.status_code == 200
        session = session_response.json()
        assert session["metadata"]["assistant_id"] == "pgx"
        assert session["metadata"]["assistant"]["enabled_skills"] == ["literature-review", "citation-check"]
        assert session["metadata"]["assistant"]["enabled_mcps"] == ["exa"]
        assert session["metadata"]["assistant"]["system_prompt"] == "Always produce a literature-backed summary."


def test_new_agents_default_to_builtin_non_always_skills_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "skills" / "local-skill").mkdir(parents=True)
    (workspace / "skills" / "local-skill" / "SKILL.md").write_text("---\ndescription: local skill\n---", encoding="utf-8")

    config = Config.model_validate({"agents": {"defaults": {"workspace": str(workspace), "model": "openai/gpt-4.1-mini"}}})

    app = _create_test_app(config)

    with TestClient(app) as client:
        response = client.post(
            "/api/agents",
            json={"assistant_id": "custom-agent", "template_id": None, "name": "Custom Agent"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "memory" not in data["enabled_skills"]
    assert "local-skill" not in data["enabled_skills"]
    assert "weather" in data["enabled_skills"]


def test_runtime_can_upsert_custom_preset(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config.model_validate({"agents": {"defaults": {"workspace": str(workspace)}}})

    app = _create_test_app(config)

    preset = {
        "id": "market-analyst",
        "name": "Market Analyst",
        "description": "Analyze markets and competitors.",
        "system_prompt": "You are a market analyst.",
        "user_identity": "The user is a startup operator.",
        "agent_identity": "You synthesize market signals into decisions.",
        "required_mcps": ["exa"],
        "required_tools": ["web_search"],
        "example_query": "Map the AI note-taking market.",
        "icon": "📈",
    }

    with TestClient(app) as client:
        response = client.put("/api/templates/market-analyst", json=preset)
        assert response.status_code == 200

        settings = client.get("/api/settings")
        assert settings.status_code == 200
        data = settings.json()

    saved = next(item for item in data["templates"] if item["id"] == "market-analyst")
    assert saved["name"] == "Market Analyst"


def test_default_agent_cannot_be_deleted(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config.model_validate({"agents": {"defaults": {"workspace": str(workspace)}}})

    app = _create_test_app(config)

    with TestClient(app) as client:
        delete_response = client.delete("/api/agents/default")
        assert delete_response.status_code == 403
        assert delete_response.json()["detail"] == 'Assistant "default" cannot be deleted'

        list_response = client.get("/api/agents")
        assert list_response.status_code == 200
        assert any(agent["id"] == "default" for agent in list_response.json())


def test_web_startup_migrates_topic_jobs_to_workspace_store_without_touching_global_jobs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    config_path = runtime_dir / "config.json"

    config = Config.model_validate({"agents": {"defaults": {"workspace": str(workspace)}}})
    session = Session(key="web:default:topic-1", metadata={"assistant_id": "default"})
    SessionManager(workspace).save(session)

    global_cron_path = runtime_dir / "cron" / "jobs.json"
    global_cron = CronService(global_cron_path)
    topic_job = global_cron.add_job(
        name="Topic review",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *"),
        message="Review topic",
        assistant_id="default",
        topic_session_id=session.key,
    )
    global_job = global_cron.add_job(
        name="Legacy heartbeat",
        schedule=CronSchedule(kind="cron", expr="0 * * * *"),
        message="Heartbeat",
    )

    with patch("nanobot.config.paths.get_config_path", return_value=config_path):
        app = _create_test_app(config, cron_service=None)
        with TestClient(app):
            pass

    migrated_jobs = CronService(workspace / "web" / "cron-jobs.json").list_jobs(include_disabled=True)
    remaining_global_jobs = CronService(global_cron_path).list_jobs(include_disabled=True)

    assert [job.id for job in migrated_jobs] == [topic_job.id]
    assert [job.id for job in remaining_global_jobs] == [global_job.id]


def test_web_startup_migrates_topic_jobs_when_session_is_only_in_legacy_store(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    config_path = runtime_dir / "config.json"
    legacy_sessions_dir = runtime_dir / "legacy-sessions"
    legacy_sessions_dir.mkdir()

    config = Config.model_validate({"agents": {"defaults": {"workspace": str(workspace)}}})
    session_key = "web:default:topic-legacy"

    with patch("nanobot.session.manager.get_legacy_sessions_dir", return_value=legacy_sessions_dir):
        legacy_manager = SessionManager(workspace)
        legacy_session_path = legacy_manager._get_legacy_session_path(session_key)
        workspace_session_path = legacy_manager._get_session_path(session_key)
        legacy_session_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_session_path.write_text(
            json.dumps(
                {
                    "_type": "metadata",
                    "key": session_key,
                    "created_at": "2026-03-17T00:00:00",
                    "updated_at": "2026-03-17T00:00:00",
                    "metadata": {"assistant_id": "default"},
                    "last_consolidated": 0,
                },
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

        global_cron_path = runtime_dir / "cron" / "jobs.json"
        global_cron = CronService(global_cron_path)
        topic_job = global_cron.add_job(
            name="Legacy topic review",
            schedule=CronSchedule(kind="cron", expr="0 9 * * *"),
            message="Review topic",
            assistant_id="default",
            topic_session_id=session_key,
        )

        with patch("nanobot.config.paths.get_config_path", return_value=config_path):
            app = _create_test_app(config, cron_service=None)
            with TestClient(app):
                pass

        migrated_jobs = CronService(workspace / "web" / "cron-jobs.json").list_jobs(include_disabled=True)
        assert [job.id for job in migrated_jobs] == [topic_job.id]
        assert workspace_session_path.exists()
        assert not legacy_session_path.exists()


def test_workspace_change_is_saved_but_not_hot_applied(tmp_path: Path) -> None:
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()

    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(workspace_a), "model": "openai/gpt-4.1-nano"}},
        }
    )
    app = _create_test_app(config)
    saved: dict[str, str] = {}

    def _capture_save(cfg: Config, path: Path) -> None:
        saved["workspace"] = cfg.agents.defaults.workspace
        saved["model"] = cfg.agents.defaults.model

    with patch("nanobot.web.server.save_config", side_effect=_capture_save), \
         patch("nanobot.web.server.get_config_path", return_value=tmp_path / "config.json"):
        with TestClient(app) as client:
            response = client.put(
                "/api/settings/model-config",
                json={
                    "workspace": str(workspace_b),
                    "model": "openai/gpt-4.1-mini",
                    "provider": "custom",
                    "custom": {"api_key": "", "api_base": ""},
                    "search": {"provider": "brave", "api_key": "", "max_results": 5},
                },
            )
            assert response.status_code == 200
            payload = response.json()
            settings = client.get("/api/settings")

    assert payload["restart_required"] is True
    assert payload["active_workspace"] == str(workspace_a)
    assert payload["model_config"]["workspace"] == str(workspace_b)
    assert payload["model_config"]["model"] == "openai/gpt-4.1-mini"
    assert settings.status_code == 200
    settings_payload = settings.json()
    assert settings_payload["workspace"] == str(workspace_a)
    assert settings_payload["model_config"]["workspace"] == str(workspace_a)
    assert settings_payload["model_config"]["model"] == "openai/gpt-4.1-mini"
    assert saved == {
        "workspace": str(workspace_b),
        "model": "openai/gpt-4.1-mini",
    }


def test_delete_agent_only_removes_workspace_scoped_jobs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    config_path = runtime_dir / "config.json"

    config = Config.model_validate({"agents": {"defaults": {"workspace": str(workspace)}}})

    workspace_cron_path = workspace / "web" / "cron-jobs.json"
    workspace_cron = CronService(workspace_cron_path)
    workspace_cron.add_job(
        name="Workspace topic job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *"),
        message="Workspace reminder",
        assistant_id="custom-agent",
        topic_session_id="web:custom-agent:topic-local",
    )

    global_cron_path = runtime_dir / "cron" / "jobs.json"
    global_cron = CronService(global_cron_path)
    global_job = global_cron.add_job(
        name="Global topic job",
        schedule=CronSchedule(kind="cron", expr="0 10 * * *"),
        message="Global reminder",
        assistant_id="custom-agent",
        topic_session_id="web:custom-agent:topic-global",
    )

    with patch("nanobot.config.paths.get_config_path", return_value=config_path):
        app = _create_test_app(config, cron_service=None)
        with TestClient(app) as client:
            create_response = client.post(
                "/api/assistants",
                json={"assistant_id": "custom-agent", "template_id": None, "name": "Custom Agent"},
            )
            assert create_response.status_code == 200

            delete_response = client.delete("/api/assistants/custom-agent")
            assert delete_response.status_code == 200

    remaining_workspace_jobs = CronService(workspace_cron_path).list_jobs(include_disabled=True)
    remaining_global_jobs = CronService(global_cron_path).list_jobs(include_disabled=True)

    assert remaining_workspace_jobs == []
    assert [job.id for job in remaining_global_jobs] == [global_job.id]
