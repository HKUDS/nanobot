from __future__ import annotations

from pathlib import Path

import pytest

try:
    from nanobot.kosmos import database

    HAS_KOSMOS_DEPS = True
except Exception:
    database = None
    HAS_KOSMOS_DEPS = False

try:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


@pytest.fixture
def aiohttp_client_factory(tmp_path: Path):
    async def _factory():
        from nanobot.kosmos.api import add_routes

        db = await database.init_db(tmp_path / "kosmos.db")
        app = web.Application()
        app["kosmos_db"] = db
        app["db_ops"] = database
        app["broadcaster"] = None
        app["agents"] = {}
        add_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        return client, db

    return _factory


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.skipif(not HAS_KOSMOS_DEPS, reason="Kosmos deps not installed")
def test_transition_and_release_approval_flow(aiohttp_client_factory):
    async def _run() -> None:
        client, db = await aiohttp_client_factory()
        try:
            project = await database.create_project(
                db, name="proj", path="/tmp/proj", project_id="proj"
            )
            task = await database.create_task(
                db,
                project_id=project["id"],
                title="Implement feature",
                status="todo",
            )

            resp = await client.post(
                f"/api/tasks/{task['id']}/transition",
                json={
                    "to_status": "progress",
                    "agent_id": "Vicks",
                    "agent_name": "Vicks",
                    "assigned_to": "Vicks",
                    "comment_text": "Claimed for work",
                },
            )
            assert resp.status == 200
            updated = await resp.json()
            assert updated["status"] == "progress"
            assert updated["assigned_to"] == "Vicks"

            release_resp = await client.post(
                f"/api/tasks/{task['id']}/transition",
                json={"to_status": "release", "agent_id": "Wedge", "agent_name": "Wedge"},
            )
            assert release_resp.status == 409

            to_qa = await client.post(
                f"/api/tasks/{task['id']}/transition",
                json={"to_status": "qa", "agent_id": "Vicks", "agent_name": "Vicks"},
            )
            assert to_qa.status == 200

            to_release = await client.post(
                f"/api/tasks/{task['id']}/transition",
                json={"to_status": "release", "agent_id": "Wedge", "agent_name": "Wedge"},
            )
            assert to_release.status == 200

            done_before_approval = await client.post(
                f"/api/tasks/{task['id']}/transition",
                json={"to_status": "done", "agent_id": "Rydia", "agent_name": "Rydia"},
            )
            assert done_before_approval.status == 409

            approval = await client.post(
                f"/api/tasks/{task['id']}/approve_release",
                json={"approved_by": "human", "branch": "main", "push": False},
            )
            assert approval.status == 200
            approved = await approval.json()
            assert bool(approved.get("release_approved")) is True
            assert approved.get("approved_by") == "human"
            assert approved.get("approved_branch") == "main"

            done_after_approval = await client.post(
                f"/api/tasks/{task['id']}/transition",
                json={"to_status": "done", "agent_id": "Rydia", "agent_name": "Rydia"},
            )
            assert done_after_approval.status == 200
        finally:
            await client.close()
            await db.close()

    import asyncio

    asyncio.run(_run())


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.skipif(not HAS_KOSMOS_DEPS, reason="Kosmos deps not installed")
def test_comment_accepts_comment_text_and_enforces_owner(aiohttp_client_factory):
    async def _run() -> None:
        client, db = await aiohttp_client_factory()
        try:
            project = await database.create_project(
                db, name="proj", path="/tmp/proj", project_id="proj2"
            )
            task = await database.create_task(
                db,
                project_id=project["id"],
                title="Owner comment",
                status="progress",
                assigned_to="Vicks",
            )

            denied = await client.post(
                f"/api/tasks/{task['id']}/comments",
                json={"agent_id": "Other", "comment_text": "not allowed"},
            )
            assert denied.status == 409

            allowed = await client.post(
                f"/api/tasks/{task['id']}/comments",
                json={"agent_id": "Vicks", "comment_text": "allowed"},
            )
            assert allowed.status == 201
            body = await allowed.json()
            assert body["comment"] == "allowed"
        finally:
            await client.close()
            await db.close()

    import asyncio

    asyncio.run(_run())


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.skipif(not HAS_KOSMOS_DEPS, reason="Kosmos deps not installed")
def test_publish_activity_endpoint_accepts_payload(aiohttp_client_factory):
    async def _run() -> None:
        client, db = await aiohttp_client_factory()
        try:
            resp = await client.post(
                "/api/events/activity",
                json={
                    "id": "evt-1",
                    "type": "status",
                    "message": "front ping",
                },
            )
            assert resp.status == 202
            body = await resp.json()
            assert body["status"] == "ok"
        finally:
            await client.close()
            await db.close()

    import asyncio

    asyncio.run(_run())


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.skipif(not HAS_KOSMOS_DEPS, reason="Kosmos deps not installed")
def test_project_path_validation_on_create_and_update(aiohttp_client_factory, tmp_path: Path):
    async def _run() -> None:
        client, db = await aiohttp_client_factory()
        try:
            invalid_create = await client.post(
                "/api/projects",
                json={"name": "bad", "path": "/tmp/definitely-missing-kosmos-path-xyz"},
            )
            assert invalid_create.status == 400

            valid_dir = tmp_path / "valid-project"
            valid_dir.mkdir(parents=True, exist_ok=True)

            created_resp = await client.post(
                "/api/projects",
                json={"name": "ok", "path": str(valid_dir)},
            )
            assert created_resp.status == 201
            created = await created_resp.json()

            invalid_update = await client.patch(
                f"/api/projects/{created['id']}",
                json={"path": "/tmp/another-missing-kosmos-path-xyz"},
            )
            assert invalid_update.status == 400
        finally:
            await client.close()
            await db.close()

    import asyncio

    asyncio.run(_run())
