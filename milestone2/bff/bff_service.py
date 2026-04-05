"""BFF AgentService - FastAPI backend for containerized Nanobot agents.

This module provides the REST API for:
- Conversation management
- Message routing to containerized agents
- Fork/Branch operations
- Merge operations
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import DEEPSEEK_API_KEY, DASHSCOPE_API_KEY
from bff.container_orchestrator import orchestrator


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")


TZ_UTC8 = timezone(timedelta(hours=8))

app = FastAPI(title="Nanobot BFF - Containerized")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


@app.get("/")
async def root():
    return RedirectResponse(url="/frontend/index.html")

conversations: dict = {}
branches: dict = {}
container_ports: dict = {}


def get_container_url(conversation_id: str) -> str:
    port = container_ports.get(conversation_id)
    if not port:
        raise HTTPException(status_code=404, detail=f"Container not found for conversation {conversation_id}")
    return f"http://localhost:{port}"


class ConversationCreate(BaseModel):
    title: str
    model: str = "deepseek-chat"


class ConversationResponse(BaseModel):
    conversation_id: str
    title: str
    model: str
    status: str


class MessageSend(BaseModel):
    content: str
    model: Optional[str] = None


class MessageResponse(BaseModel):
    conversation_id: str
    content: str
    usage: dict
    trajectory: list


class ForkRequest(BaseModel):
    parent_conversation_id: str
    new_branch_name: str


class ForkResponse(BaseModel):
    new_conversation_id: str
    parent_conversation_id: str
    status: str


class MergeRequest(BaseModel):
    source_conversation_id: str
    target_conversation_id: str


class MergeResponse(BaseModel):
    status: str
    trajectory_count: int
    merge_result: dict


@app.post("/conversations", response_model=ConversationResponse)
async def create_conversation(req: ConversationCreate):
    conversation_id = str(uuid.uuid4())[:8]

    api_key = DEEPSEEK_API_KEY if "deepseek" in req.model.lower() else DASHSCOPE_API_KEY

    container_info = await orchestrator.create_container(
        conversation_id=conversation_id,
        task=req.title,
        model=req.model,
        api_key=api_key,
    )

    container_ports[conversation_id] = container_info["port"]

    conversations[conversation_id] = {
        "conversation_id": conversation_id,
        "title": req.title,
        "model": req.model,
        "status": "active",
        "container_info": container_info,
        "created_at": datetime.now(TZ_UTC8).isoformat(),
    }

    branches[conversation_id] = {
        "branch_id": conversation_id,
        "conversation_id": conversation_id,
        "parent_branch_id": None,
        "status": "active",
    }

    return ConversationResponse(
        conversation_id=conversation_id,
        title=req.title,
        model=req.model,
        status="active",
    )


@app.get("/conversations")
async def list_conversations():
    return {
        "conversations": [
            {**conv, "container_port": container_ports.get(cid)}
            for cid, conv in conversations.items()
        ]
    }


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        **conversations[conversation_id],
        "container_port": container_ports.get(conversation_id),
    }


@app.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(conversation_id: str, req: MessageSend):
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    url = f"{get_container_url(conversation_id)}/chat"
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(url, json={"content": req.content, "model": req.model})
            resp.raise_for_status()
            result = resp.json()
            return MessageResponse(**result)
        except httpx.HTTPStatusError as e:
            print(f"[BFF] Chat error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=f"Container error: {e.response.text}")
        except httpx.TimeoutException as e:
            print(f"[BFF] Chat timeout: {url}")
            raise HTTPException(status_code=504, detail="Container timeout")
        except Exception as e:
            print(f"[BFF] Chat error: {url} - {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}/trajectory")
async def get_trajectory(conversation_id: str):
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    url = f"{get_container_url(conversation_id)}/trajectory"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}/history")
async def get_history(conversation_id: str):
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    url = f"{get_container_url(conversation_id)}/history"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/conversations/{conversation_id}/fork", response_model=ForkResponse)
async def fork_conversation(conversation_id: str, req: ForkRequest):
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Parent conversation not found")

    new_conversation_id = str(uuid.uuid4())[:8]

    container_info = await orchestrator.fork_container(
        parent_conversation_id=conversation_id,
        child_conversation_id=new_conversation_id,
    )

    container_ports[new_conversation_id] = container_info["port"]

    conversations[new_conversation_id] = {
        "conversation_id": new_conversation_id,
        "title": f"{conversations[conversation_id]['title']} (fork)",
        "model": conversations[conversation_id]["model"],
        "status": "active",
        "parent_id": conversation_id,
        "container_info": container_info,
        "created_at": datetime.now(TZ_UTC8).isoformat(),
    }

    branches[new_conversation_id] = {
        "branch_id": new_conversation_id,
        "conversation_id": new_conversation_id,
        "parent_branch_id": conversation_id,
        "status": "active",
    }

    return ForkResponse(
        new_conversation_id=new_conversation_id,
        parent_conversation_id=conversation_id,
        status="active",
    )


@app.post("/merge", response_model=MergeResponse)
async def merge_conversations(req: MergeRequest):
    if req.source_conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Source conversation not found")
    if req.target_conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Target conversation not found")

    merge_result = await orchestrator.merge_and_destroy(
        source_conversation_id=req.source_conversation_id,
        target_conversation_id=req.target_conversation_id,
    )

    # 完全删除源分支
    if req.source_conversation_id in conversations:
        del conversations[req.source_conversation_id]

    if req.source_conversation_id in container_ports:
        del container_ports[req.source_conversation_id]

    if req.source_conversation_id in branches:
        del branches[req.source_conversation_id]

    return MergeResponse(
        status="completed",
        trajectory_count=merge_result["trajectory_count"],
        merge_result={
            "source": req.source_conversation_id,
            "target": req.target_conversation_id,
            "trajectory_count": merge_result["trajectory_count"],
        },
    )


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await orchestrator.destroy_container(conversation_id)

    if conversation_id in container_ports:
        del container_ports[conversation_id]

    del conversations[conversation_id]

    if conversation_id in branches:
        del branches[conversation_id]

    return {"status": "deleted", "conversation_id": conversation_id}


@app.get("/health")
async def health_check():
    active_containers = orchestrator.list_active_containers()
    return {
        "status": "ok",
        "active_containers": len(active_containers),
        "total_conversations": len(conversations),
        "total_branches": len(branches),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
