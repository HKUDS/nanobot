"""FastAPI main application for Nanobot BFF."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agent_service import AgentService
from config import HOST, PORT, PROJECT_ROOT
from database import Database
from models import (
    ConversationCreate,
    ConversationResponse,
    HealthResponse,
    MessageResponse,
    MessageSend,
    TraceResponse,
    BranchResponse,
    ForkBranchRequest,
    ForkBranchResponse,
)


db: Database | None = None
agent_service: AgentService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, agent_service
    db = Database()
    await db.init()
    agent_service = AgentService(db)
    print(f"[Nanobot BFF] Database initialized at {db.db_path}")
    yield
    print("[Nanobot BFF] Shutting down...")


app = FastAPI(
    title="Nanobot BFF API",
    description="Backend-for-Frontend API for Nanobot Agent Trajectory Modeling",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/frontend", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    if agent_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    health = await agent_service.health_check()
    return HealthResponse(**health)


@app.post("/conversations", response_model=ConversationResponse)
async def create_conversation(conversation: ConversationCreate):
    if db is None or agent_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    conversation_id = await agent_service.create_conversation(
        title=conversation.title,
        model=conversation.model,
    )
    conv = await db.get_conversation(conversation_id)
    return ConversationResponse(
        id=conv["id"],
        title=conv["title"],
        model=conv["model"],
        created_at=conv["created_at"],
        updated_at=conv["updated_at"],
        turn_count=0,
    )


@app.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations():
    if db is None or agent_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    conversations = await agent_service.list_conversations()
    responses = []
    for conv in conversations:
        turn_count = await db.get_conversation_turn_count(conv["id"])
        responses.append(
            ConversationResponse(
                id=conv["id"],
                title=conv["title"],
                model=conv["model"],
                created_at=conv["created_at"],
                updated_at=conv["updated_at"],
                turn_count=turn_count,
            )
        )
    return responses


@app.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: int):
    if db is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    conversation = await db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    turn_count = await db.get_conversation_turn_count(conversation_id)
    return ConversationResponse(
        id=conversation["id"],
        title=conversation["title"],
        model=conversation["model"],
        created_at=conversation["created_at"],
        updated_at=conversation["updated_at"],
        turn_count=turn_count,
    )


@app.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(conversation_id: int, message: MessageSend):
    if db is None or agent_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    if message.conversation_id != conversation_id:
        raise HTTPException(status_code=400, detail="Conversation ID mismatch")

    conversation = await db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await agent_service.send_message(
        conversation_id=conversation_id,
        content=message.content,
    )

    from models import TrajectoryTuple
    import datetime

    trajectory = TrajectoryTuple(**result["trajectory"])
    trajectory.timestamp = datetime.datetime.now()

    return MessageResponse(
        conversation_id=result["conversation_id"],
        turn_id=result["turn_id"],
        content=result["content"],
        trajectory=trajectory,
        usage=result["usage"],
    )


@app.get("/conversations/{conversation_id}/history")
async def get_conversation_history(conversation_id: int):
    if db is None or agent_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    conversation = await db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    history = await agent_service.get_conversation_history(conversation_id)
    return {"conversation_id": conversation_id, "turns": history}


@app.get("/conversations/{conversation_id}/traces", response_model=list[TraceResponse])
async def get_conversation_traces(conversation_id: int, branch_id: str | None = None):
    if db is None or agent_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    conversation = await db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    traces = await agent_service.get_traces(conversation_id, branch_id)
    return traces


@app.get("/conversations/{conversation_id}/branches", response_model=list[BranchResponse])
async def get_conversation_branches(conversation_id: int):
    if db is None or agent_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    conversation = await db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    branches = await agent_service.get_branches(conversation_id)
    return branches


@app.post("/conversations/{conversation_id}/fork", response_model=ForkBranchResponse)
async def fork_branch(conversation_id: int, request: ForkBranchRequest):
    if db is None or agent_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    conversation = await db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await agent_service.fork_branch(
        conversation_id=conversation_id,
        parent_branch_id=request.parent_branch_id,
        new_branch_name=request.new_branch_name,
    )
    return ForkBranchResponse(**result)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
