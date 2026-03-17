"""FastAPI web server for nanobot web interface."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nanobot.agent.tools.web import SEARCH_PROVIDERS, WebSearchTool
from nanobot.config.loader import get_config_path, save_config
from nanobot.config.schema import ProviderConfig
from nanobot.web.assistant_store import AssistantConfig, AssistantStore, AssistantUpdate, serialize_assistant_prompt
from nanobot.web.template_store import TemplateConfig, TemplateStore


_STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str
    session_id: str = "web:default"


class RenameSessionRequest(BaseModel):
    new_session_id: str


class CreateSessionRequest(BaseModel):
    session_id: str
    template_id: str | None = None


class CreateAssistantRequest(BaseModel):
    assistant_id: str
    template_id: str | None = None
    name: str | None = None


class CreateTopicRequest(BaseModel):
    name: str | None = None


class RenameTopicRequest(BaseModel):
    name: str


class UpsertTemplateRequest(TemplateConfig):
    pass


class ModelProviderConfigRequest(BaseModel):
    api_key: str = ""
    api_base: str = ""


class SearchConfigRequest(BaseModel):
    provider: str
    api_key: str = ""
    max_results: int = 5


class ModelConfigRequest(BaseModel):
    workspace: str
    model: str
    provider: str
    custom: ModelProviderConfigRequest
    search: SearchConfigRequest


class PromptConfigRequest(BaseModel):
    name: str = ""
    timezone: str = ""
    language: str = ""
    communication_style: str = ""
    response_length: str = ""
    technical_level: str = ""
    primary_role: str = ""
    main_projects: str = ""
    tools_you_use: str = ""
    topics_of_interest: list[str] = []
    special_instructions: str = ""


def _serialize_template(template: TemplateConfig, *, is_bundled: bool = False) -> dict[str, Any]:
    """Convert a template model into API-friendly JSON."""
    payload = template.model_dump()
    payload["is_bundled"] = is_bundled
    return payload


def _serialize_assistant(assistant: AssistantConfig) -> dict[str, Any]:
    """Convert an agent model into API-friendly JSON."""
    payload = assistant.model_dump()
    payload["agent_settings"] = {
        "skills": assistant.enabled_skills,
        "mcps": assistant.enabled_mcps,
        "cron_jobs": assistant.enabled_cron_jobs,
    }
    payload["prompt_settings"] = {
        "user_identity": assistant.user_identity,
        "agent_identity": assistant.agent_identity,
        "system_prompt": assistant.system_prompt,
    }
    return payload


def _serialize_model_config(cfg: Any) -> dict[str, Any]:
    return {
        "workspace": cfg.agents.defaults.workspace,
        "model": cfg.agents.defaults.model,
        "provider": cfg.agents.defaults.provider,
        "custom": {
            "api_key": cfg.providers.custom.api_key,
            "api_base": cfg.providers.custom.api_base or "",
        },
        "search": {
            "provider": cfg.tools.web.search.provider,
            "api_key": cfg.tools.web.search.api_key,
            "max_results": cfg.tools.web.search.max_results,
        },
    }


def _extract_field(content: str, label: str) -> str:
    pattern = rf"- \*\*{re.escape(label)}\*\*: ?(.*)"
    match = re.search(pattern, content)
    return (match.group(1) if match else "").strip()


def _extract_checked_option(content: str, heading: str, options: list[str]) -> str:
    section_match = re.search(
        rf"### {re.escape(heading)}\n\n(?P<body>.*?)(?:\n## |\n### |\n---)",
        content,
        flags=re.S,
    )
    body = section_match.group("body") if section_match else ""
    for option in options:
        if re.search(rf"- \[x\] {re.escape(option)}", body):
            return option
    return ""


def _extract_topics(content: str) -> list[str]:
    section_match = re.search(
        r"## Topics of Interest\n\n(?P<body>.*?)(?:\n## |\n---)",
        content,
        flags=re.S,
    )
    body = section_match.group("body") if section_match else ""
    topics = []
    for line in body.splitlines():
        if line.startswith("- "):
            value = line[2:].strip()
            if value:
                topics.append(value)
    return topics


def _extract_special_instructions(content: str) -> str:
    match = re.search(
        r"## Special Instructions\n\n(?P<body>.*?)(?:\n---)",
        content,
        flags=re.S,
    )
    return (match.group("body") if match else "").strip()


def _prompt_config_path(cfg: Any) -> Path:
    return cfg.workspace_path / "USER.md"


def _serialize_prompt_config(cfg: Any) -> dict[str, Any]:
    path = _prompt_config_path(cfg)
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    return {
        "name": _extract_field(content, "Name"),
        "timezone": _extract_field(content, "Timezone"),
        "language": _extract_field(content, "Language"),
        "communication_style": _extract_checked_option(content, "Communication Style", ["Casual", "Professional", "Technical"]),
        "response_length": _extract_checked_option(content, "Response Length", ["Brief and concise", "Detailed explanations", "Adaptive based on question"]),
        "technical_level": _extract_checked_option(content, "Technical Level", ["Beginner", "Intermediate", "Expert"]),
        "primary_role": _extract_field(content, "Primary Role"),
        "main_projects": _extract_field(content, "Main Projects"),
        "tools_you_use": _extract_field(content, "Tools You Use"),
        "topics_of_interest": _extract_topics(content),
        "special_instructions": _extract_special_instructions(content),
    }


def _render_checked(option: str, selected: str) -> str:
    return f"- [{'x' if option == selected else ' '}] {option}"


def _render_prompt_config(payload: PromptConfigRequest) -> str:
    topics = [item.strip() for item in payload.topics_of_interest if item.strip()]
    while len(topics) < 3:
        topics.append("")
    topics = topics[:3]
    special_instructions = (payload.special_instructions or "").strip() or "(Any specific instructions for how the assistant should behave)"
    return f"""# User Profile

Information about the user to help personalize interactions.

## Basic Information

- **Name**: {payload.name.strip()}
- **Timezone**: {payload.timezone.strip()}
- **Language**: {payload.language.strip()}

## Preferences

### Communication Style

{_render_checked("Casual", payload.communication_style)}
{_render_checked("Professional", payload.communication_style)}
{_render_checked("Technical", payload.communication_style)}

### Response Length

{_render_checked("Brief and concise", payload.response_length)}
{_render_checked("Detailed explanations", payload.response_length)}
{_render_checked("Adaptive based on question", payload.response_length)}

### Technical Level

{_render_checked("Beginner", payload.technical_level)}
{_render_checked("Intermediate", payload.technical_level)}
{_render_checked("Expert", payload.technical_level)}

## Work Context

- **Primary Role**: {payload.primary_role.strip()}
- **Main Projects**: {payload.main_projects.strip()}
- **Tools You Use**: {payload.tools_you_use.strip()}

## Topics of Interest

- {topics[0]}
- {topics[1]}
- {topics[2]}

## Special Instructions

{special_instructions}

---

*Edit this file to customize nanobot's behavior for your needs.*
"""


def _iso_from_ms(timestamp_ms: int | None) -> str | None:
    """Convert epoch milliseconds to ISO-8601 string."""
    if not timestamp_ms:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000).isoformat()


def create_app(config_path: str | None = None, workspace: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cli.commands import _load_runtime_config, _make_provider
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager
    from nanobot.utils.helpers import sync_workspace_templates

    cfg = _load_runtime_config(config_path, workspace)
    sync_workspace_templates(cfg.workspace_path)

    bus = MessageBus()
    provider = _make_provider(cfg)

    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    session_manager = SessionManager(cfg.workspace_path)
    assistant_store = AssistantStore(cfg.workspace_path, default_model=cfg.agents.defaults.model)
    assistant_store.ensure_default()
    template_store = TemplateStore(cfg.workspace_path)

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=cfg.workspace_path,
        model=cfg.agents.defaults.model,
        max_iterations=cfg.agents.defaults.max_tool_iterations,
        context_window_tokens=cfg.agents.defaults.context_window_tokens,
        web_search_config=cfg.tools.web.search,
        web_proxy=cfg.tools.web.proxy or None,
        exec_config=cfg.tools.exec,
        cron_service=cron,
        restrict_to_workspace=cfg.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=cfg.tools.mcp_servers,
        channels_config=cfg.channels,
    )

    app = FastAPI(title="nanobot web", docs_url=None, redoc_url=None)

    def _apply_runtime_config(payload: ModelConfigRequest) -> tuple[dict[str, Any], bool]:
        workspace_value = payload.workspace.strip()
        model_value = payload.model.strip()
        provider_name = payload.provider.strip()
        search_provider = payload.search.provider.strip().lower()

        if not workspace_value:
            raise HTTPException(status_code=400, detail="Workspace cannot be empty")
        if not model_value:
            raise HTTPException(status_code=400, detail="Model cannot be empty")
        if not provider_name:
            raise HTTPException(status_code=400, detail="Provider cannot be empty")
        if search_provider not in SEARCH_PROVIDERS:
            allowed = ", ".join(SEARCH_PROVIDERS)
            raise HTTPException(status_code=400, detail=f"Invalid search provider. Allowed: {allowed}")

        if not hasattr(cfg.providers, provider_name):
            raise HTTPException(status_code=400, detail=f"Unknown provider '{provider_name}'")

        restart_required = cfg.agents.defaults.workspace != workspace_value

        cfg.agents.defaults.workspace = workspace_value
        cfg.agents.defaults.model = model_value
        cfg.agents.defaults.provider = provider_name
        cfg.providers.custom = ProviderConfig(
            api_key=payload.custom.api_key.strip(),
            api_base=payload.custom.api_base.strip() or None,
        )
        cfg.tools.web.search.provider = search_provider
        cfg.tools.web.search.api_key = payload.search.api_key.strip()
        cfg.tools.web.search.max_results = min(max(payload.search.max_results, 1), 10)

        save_config(cfg, get_config_path())

        new_provider = _make_provider(cfg)
        agent.provider = new_provider
        agent.model = cfg.agents.defaults.model
        agent.web_search_config = cfg.tools.web.search
        agent.subagents.provider = new_provider
        agent.subagents.model = cfg.agents.defaults.model
        agent.subagents.web_search_config = cfg.tools.web.search
        agent.memory_consolidator.provider = new_provider
        agent.memory_consolidator.model = cfg.agents.defaults.model
        agent.memory_consolidator.context_window_tokens = cfg.agents.defaults.context_window_tokens
        assistant_store.default_model = cfg.agents.defaults.model

        web_search_tool = agent.tools.get("web_search")
        if isinstance(web_search_tool, WebSearchTool):
            web_search_tool.config = cfg.tools.web.search

        return _serialize_model_config(cfg), restart_required

    def _apply_prompt_config(payload: PromptConfigRequest) -> dict[str, Any]:
        path = _prompt_config_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_prompt_config(payload), encoding="utf-8")
        return _serialize_prompt_config(cfg)

    @app.on_event("startup")
    async def _startup() -> None:
        await agent._connect_mcp()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await agent.close_mcp()

    # ------------------------------------------------------------------
    # Chat endpoint — SSE streaming
    # ------------------------------------------------------------------

    @app.post("/api/chat")
    async def chat(request: ChatRequest) -> StreamingResponse:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            await queue.put({"type": "progress", "content": content, "tool_hint": tool_hint})

        async def _run_agent() -> None:
            try:
                response = await agent.process_direct(
                    request.message,
                    session_key=request.session_id,
                    channel="web",
                    chat_id="browser",
                    on_progress=on_progress,
                )
                await queue.put({"type": "done", "content": response or ""})
            except Exception as exc:  # noqa: BLE001
                await queue.put({"type": "error", "content": str(exc)})
            finally:
                await queue.put(None)  # sentinel

        async def stream() -> Any:
            task = asyncio.create_task(_run_agent())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # Session endpoints
    # ------------------------------------------------------------------

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return session_manager.list_sessions()

    def _topic_payload(session: Any) -> dict[str, Any]:
        topic_name = session.metadata.get("topic_name") or session.key.replace("web:", "")
        assistant_id = session.metadata.get("assistant_id") or "default"
        return {
            "id": session.key,
            "session_id": session.key,
            "assistant_id": assistant_id,
            "name": topic_name,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "message_count": len(session.messages),
        }

    def _topics_for_assistant(assistant_id: str) -> list[dict[str, Any]]:
        topics: list[dict[str, Any]] = []
        for item in session_manager.list_sessions():
            session = session_manager.get_or_create(item["key"])
            if session.metadata.get("assistant_id", "default") != assistant_id:
                continue
            topics.append(_topic_payload(session))
        return sorted(topics, key=lambda item: item["updated_at"], reverse=True)

    def _sync_assistant_topics(assistant: AssistantConfig) -> None:
        snapshot = serialize_assistant_prompt(assistant)
        for item in session_manager.list_sessions():
            session = session_manager.get_or_create(item["key"])
            if session.metadata.get("assistant_id", "default") != assistant.id:
                continue
            session.metadata["assistant_id"] = assistant.id
            session.metadata["assistant"] = snapshot
            session.metadata["template_id"] = assistant.source_template_id
            session.metadata["template"] = {
                "id": assistant.source_template_id,
                "name": assistant.name,
                "description": assistant.description,
                "icon": assistant.icon,
                "model": assistant.model,
                "enabled_skills": assistant.enabled_skills,
                "enabled_mcps": assistant.enabled_mcps,
                "enabled_cron_jobs": assistant.enabled_cron_jobs,
                "system_prompt": assistant.system_prompt,
                "user_identity": assistant.user_identity,
                "agent_identity": assistant.agent_identity,
                "required_mcps": assistant.required_mcps,
                "required_tools": assistant.required_tools,
                "example_query": assistant.example_query,
            }
            session_manager.save(session)

    def _new_topic_session_key(assistant_id: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        return f"web:{assistant_id}:{stamp}"

    def _list_agents_payload() -> list[dict[str, Any]]:
        agents = []
        for assistant in assistant_store.list_assistants():
            payload = _serialize_assistant(assistant)
            payload["topics"] = _topics_for_assistant(assistant.id)
            payload["topic_count"] = len(payload["topics"])
            agents.append(payload)
        return agents

    @app.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        return _list_agents_payload()

    @app.get("/api/assistants")
    async def list_assistants() -> list[dict[str, Any]]:
        return _list_agents_payload()

    @app.post("/api/agents")
    async def create_agent(request: CreateAssistantRequest) -> dict[str, Any]:
        assistant_id = request.assistant_id.strip()
        if not assistant_id:
            raise HTTPException(status_code=400, detail="Agent id cannot be empty")
        template = template_store.get_template(request.template_id)
        if request.template_id and template is None:
            raise HTTPException(status_code=404, detail=f'Preset "{request.template_id}" not found')
        try:
            assistant = assistant_store.create_from_template(template, assistant_id, request.name)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=f'Agent "{exc.args[0]}" already exists') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        payload = _serialize_assistant(assistant)
        payload["topics"] = []
        payload["topic_count"] = 0
        return payload

    @app.post("/api/assistants")
    async def create_assistant(request: CreateAssistantRequest) -> dict[str, Any]:
        return await create_agent(request)

    @app.get("/api/agents/{assistant_id}")
    async def get_agent(assistant_id: str) -> dict[str, Any]:
        assistant = assistant_store.get_assistant(assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        payload = _serialize_assistant(assistant)
        payload["topics"] = _topics_for_assistant(assistant.id)
        payload["topic_count"] = len(payload["topics"])
        return payload

    @app.get("/api/assistants/{assistant_id}")
    async def get_assistant(assistant_id: str) -> dict[str, Any]:
        return await get_agent(assistant_id)

    @app.patch("/api/agents/{assistant_id}")
    async def update_agent(assistant_id: str, request: AssistantUpdate) -> dict[str, Any]:
        try:
            assistant = assistant_store.update_assistant(assistant_id, request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Agent not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _sync_assistant_topics(assistant)
        payload = _serialize_assistant(assistant)
        payload["topics"] = _topics_for_assistant(assistant.id)
        payload["topic_count"] = len(payload["topics"])
        return payload

    @app.patch("/api/assistants/{assistant_id}")
    async def update_assistant(assistant_id: str, request: AssistantUpdate) -> dict[str, Any]:
        return await update_agent(assistant_id, request)

    @app.delete("/api/agents/{assistant_id}")
    async def delete_agent(assistant_id: str) -> dict[str, str]:
        try:
            assistant_store.delete_assistant(assistant_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Agent not found") from exc
        return {"status": "deleted"}

    @app.delete("/api/assistants/{assistant_id}")
    async def delete_assistant(assistant_id: str) -> dict[str, str]:
        return await delete_agent(assistant_id)

    @app.get("/api/agents/{assistant_id}/topics")
    async def list_topics(assistant_id: str) -> list[dict[str, Any]]:
        assistant = assistant_store.get_assistant(assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _topics_for_assistant(assistant.id)

    @app.get("/api/assistants/{assistant_id}/topics")
    async def list_assistant_topics(assistant_id: str) -> list[dict[str, Any]]:
        return await list_topics(assistant_id)

    @app.post("/api/agents/{assistant_id}/topics")
    async def create_topic(assistant_id: str, request: CreateTopicRequest) -> dict[str, Any]:
        assistant = assistant_store.get_assistant(assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        session_id = _new_topic_session_key(assistant_id)
        session = session_manager.get_or_create(session_id)
        session.metadata["assistant_id"] = assistant.id
        session.metadata["assistant"] = serialize_assistant_prompt(assistant)
        session.metadata["template_id"] = assistant.source_template_id
        session.metadata["topic_name"] = (request.name or "New Topic").strip() or "New Topic"
        session_manager.save(session)
        return _topic_payload(session)

    @app.post("/api/assistants/{assistant_id}/topics")
    async def create_assistant_topic(assistant_id: str, request: CreateTopicRequest) -> dict[str, Any]:
        return await create_topic(assistant_id, request)

    @app.post("/api/sessions")
    async def create_session(request: CreateSessionRequest) -> dict[str, Any]:
        session_id = request.session_id.strip()
        if not session_id:
            raise HTTPException(status_code=400, detail="Session key cannot be empty")

        template = template_store.get_template(request.template_id)
        if request.template_id and template is None:
            raise HTTPException(status_code=404, detail=f'Template "{request.template_id}" not found')

        path = session_manager._get_session_path(session_id)
        if path.exists():
            raise HTTPException(status_code=409, detail=f'Session "{session_id}" already exists')

        session = session_manager.get_or_create(session_id)
        if template:
            session.metadata["template"] = _serialize_template(template)
            session.metadata["template_id"] = template.id
            session.metadata["assistant"] = {
                **_serialize_template(template),
                "model": cfg.agents.defaults.model,
            }
        else:
            session.metadata.pop("template", None)
            session.metadata.pop("template_id", None)
            session.metadata.pop("assistant", None)
        session_manager.save(session)
        return {
            "status": "created",
            "key": session.key,
            "metadata": session.metadata,
        }

    @app.get("/api/sessions/{session_id:path}")
    async def get_session(session_id: str) -> dict[str, Any]:
        session = session_manager.get_or_create(session_id)
        return {
            "key": session.key,
            "messages": session.get_history(max_messages=0),
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
        }

    @app.delete("/api/sessions/{session_id:path}")
    async def delete_session(session_id: str) -> dict[str, str]:
        path = session_manager._get_session_path(session_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Session not found")
        path.unlink()
        session_manager.invalidate(session_id)
        return {"status": "deleted"}

    @app.patch("/api/topics/{session_id:path}")
    async def rename_topic(session_id: str, request: RenameTopicRequest) -> dict[str, Any]:
        session = session_manager.get_or_create(session_id)
        path = session_manager._get_session_path(session_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Topic not found")
        topic_name = request.name.strip()
        if not topic_name:
            raise HTTPException(status_code=400, detail="Topic name cannot be empty")
        session.metadata["topic_name"] = topic_name
        session_manager.save(session)
        return _topic_payload(session)

    @app.patch("/api/sessions/{session_id:path}")
    async def rename_session(session_id: str, request: RenameSessionRequest) -> dict[str, str]:
        try:
            session = session_manager.rename_session(session_id, request.new_session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=f'Session "{exc.args[0]}" already exists') from exc

        return {"status": "renamed", "key": session.key}

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        bundled_ids = {t.id for t in template_store._bundled_templates()}
        templates = [
            _serialize_template(template, is_bundled=template.id in bundled_ids)
            for template in template_store.list_templates()
        ]

        skills_loader = agent.context.skills
        skills = [
            {
                "name": item["name"],
                "source": item["source"],
                "path": item["path"],
            }
            for item in skills_loader.list_skills(filter_unavailable=False)
        ]

        cron_jobs = []
        for job in cron.list_jobs(include_disabled=True):
            schedule = job.schedule
            if schedule.kind == "cron":
                schedule_label = schedule.expr or "cron"
            elif schedule.kind == "every":
                schedule_label = f"every {schedule.every_ms or 0} ms"
            else:
                schedule_label = _iso_from_ms(schedule.at_ms) or "one-shot"

            cron_jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "enabled": job.enabled,
                    "schedule": schedule_label,
                    "message": job.payload.message,
                    "next_run_at": _iso_from_ms(job.state.next_run_at_ms),
                    "last_run_at": _iso_from_ms(job.state.last_run_at_ms),
                    "last_status": job.state.last_status,
                    "last_error": job.state.last_error,
                }
            )

        mcp_servers = []
        for name, server_cfg in cfg.tools.mcp_servers.items():
            target = server_cfg.url or " ".join(part for part in [server_cfg.command, *server_cfg.args] if part)
            mcp_servers.append(
                {
                    "name": name,
                    "type": server_cfg.type or "auto",
                    "target": target,
                    "enabled_tools": server_cfg.enabled_tools,
                }
            )

        return {
            "workspace": str(agent.workspace),
            "theme": "dark",
            "model_config": _serialize_model_config(cfg),
            "prompt_config": _serialize_prompt_config(cfg),
            "search_provider_options": list(SEARCH_PROVIDERS),
            "templates": templates,
            "preset_library_editable": True,
            "cron_jobs": cron_jobs,
            "skills": skills,
            "mcp_servers": mcp_servers,
        }

    @app.put("/api/settings/model-config")
    async def update_model_config(request: ModelConfigRequest) -> dict[str, Any]:
        updated, restart_required = _apply_runtime_config(request)
        return {
            "status": "ok",
            "model_config": updated,
            "restart_required": restart_required,
            "active_workspace": str(agent.workspace),
        }

    @app.put("/api/settings/prompt-config")
    async def update_prompt_config(request: PromptConfigRequest) -> dict[str, Any]:
        updated = _apply_prompt_config(request)
        return {
            "status": "ok",
            "prompt_config": updated,
            "path": str(_prompt_config_path(cfg)),
        }

    @app.put("/api/templates/{template_id}")
    async def upsert_template(template_id: str, request: UpsertTemplateRequest) -> dict[str, Any]:
        if template_id != request.id:
            raise HTTPException(status_code=400, detail="Preset id mismatch")
        template = template_store.upsert_template(TemplateConfig.model_validate(request.model_dump()))
        bundled_ids = {t.id for t in template_store._bundled_templates()}
        return _serialize_template(template, is_bundled=template.id in bundled_ids)

    @app.delete("/api/templates/{template_id}")
    async def delete_template(template_id: str) -> dict[str, str]:
        try:
            template_store.delete_template(template_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Preset not found") from exc
        return {"status": "deleted"}

    # ------------------------------------------------------------------
    # Static files / SPA
    # ------------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    return app
