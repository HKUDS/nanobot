from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from nanobot.agent.context import ContextBuilder
from nanobot.config.schema import Config
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore
from nanobot.web.server import create_app


class _FakeAgentLoop:
    def __init__(self, *args, **kwargs) -> None:
        self.context = ContextBuilder(kwargs["workspace"])

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
                    payload=CronPayload(kind="agent_turn", message="Review HEARTBEAT"),
                    state=CronJobState(next_run_at_ms=1_800_000_000_000, last_status="ok"),
                    created_at_ms=1_700_000_000_000,
                    updated_at_ms=1_700_000_000_000,
                )
            ]
        )

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        return self._store.jobs


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

    with patch("nanobot.cli.commands._load_runtime_config", return_value=config), \
         patch("nanobot.cli.commands._make_provider", return_value=object()), \
         patch("nanobot.utils.helpers.sync_workspace_templates", side_effect=lambda path: path), \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.agent.loop.AgentLoop", _FakeAgentLoop), \
         patch("nanobot.cron.service.CronService", _FakeCronService):
        app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()

    assert data["workspace"] == str(workspace)
    pharmacogenomics = next(item for item in data["templates"] if item["id"] == "pharmacogenomics")
    assert pharmacogenomics["name"] == "Pharmacogenomics Analyst"
    assert pharmacogenomics["required_mcps"] == ["exa"]

    assert any(item["name"] == "local-skill" and item["source"] == "workspace" for item in data["skills"])
    assert data["cron_jobs"][0]["name"] == "Daily review"
    assert data["cron_jobs"][0]["schedule"] == "0 9 * * *"
    assert data["mcp_servers"][0]["name"] == "github"


def test_create_session_persists_template_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(workspace)}},
        }
    )

    with patch("nanobot.cli.commands._load_runtime_config", return_value=config), \
         patch("nanobot.cli.commands._make_provider", return_value=object()), \
         patch("nanobot.utils.helpers.sync_workspace_templates", side_effect=lambda path: path), \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.agent.loop.AgentLoop", _FakeAgentLoop), \
         patch("nanobot.cron.service.CronService", _FakeCronService):
        app = create_app()

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

    with patch("nanobot.cli.commands._load_runtime_config", return_value=config), \
         patch("nanobot.cli.commands._make_provider", return_value=object()), \
         patch("nanobot.utils.helpers.sync_workspace_templates", side_effect=lambda path: path), \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.agent.loop.AgentLoop", _FakeAgentLoop), \
         patch("nanobot.cron.service.CronService", _FakeCronService):
        app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/agents",
            json={"assistant_id": "pgx", "template_id": "pharmacogenomics"},
        )
        assert response.status_code == 200
        agent = response.json()
        assert agent["name"] == "Pharmacogenomics Analyst"
        assert agent["model"] == "openai/gpt-4.1-mini"

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
                "enabled_skills": ["literature-review", "citation-check"],
                "enabled_mcps": ["exa"],
                "enabled_cron_jobs": ["daily-review"],
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


def test_runtime_can_upsert_custom_preset(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config.model_validate({"agents": {"defaults": {"workspace": str(workspace)}}})

    with patch("nanobot.cli.commands._load_runtime_config", return_value=config), \
         patch("nanobot.cli.commands._make_provider", return_value=object()), \
         patch("nanobot.utils.helpers.sync_workspace_templates", side_effect=lambda path: path), \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.agent.loop.AgentLoop", _FakeAgentLoop), \
         patch("nanobot.cron.service.CronService", _FakeCronService):
        app = create_app()

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

    with patch("nanobot.cli.commands._load_runtime_config", return_value=config), \
         patch("nanobot.cli.commands._make_provider", return_value=object()), \
         patch("nanobot.utils.helpers.sync_workspace_templates", side_effect=lambda path: path), \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.agent.loop.AgentLoop", _FakeAgentLoop), \
         patch("nanobot.cron.service.CronService", _FakeCronService):
        app = create_app()

    with TestClient(app) as client:
        delete_response = client.delete("/api/agents/default")
        assert delete_response.status_code == 403
        assert delete_response.json()["detail"] == 'Assistant "default" cannot be deleted'

        list_response = client.get("/api/agents")
        assert list_response.status_code == 200
        assert any(agent["id"] == "default" for agent in list_response.json())
