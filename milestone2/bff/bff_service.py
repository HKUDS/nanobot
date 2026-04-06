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
from bff.container_orchestrator import ContainerOrchestrator

# 先定义全局字典
conversations: dict = {}
branches: dict = {}
container_ports: dict = {}

# 再初始化容器编排器
orchestrator = ContainerOrchestrator(container_ports=container_ports)


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

# 并发安全锁（全局字典已在文件顶部定义）
conversations_lock = asyncio.Lock()
container_ports_lock = asyncio.Lock()
branches_lock = asyncio.Lock()


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
    trajectory: Optional[list] = None  # 添加轨迹数据字段


class ForkRequest(BaseModel):
    new_branch_name: str   # 只保留分支名称


class ForkResponse(BaseModel):
    new_conversation_id: str
    parent_conversation_id: str
    status: str


class MergeRequest(BaseModel):
    source_conversation_id: str
    target_conversation_id: str
    auto_merge: bool = True  # 若为False，则返回冲突信息等待用户手动解决
    conflict_resolutions: Optional[dict] = None  # 用户选择的冲突解决方案


class MemoryMergeRequest(BaseModel):
    source_conversation_id: str
    target_conversation_id: str


class MergeResponse(BaseModel):
    status: str  # "merged", "conflict", "error"
    message: str
    trajectory_count: Optional[int] = None
    merge_result: Optional[dict] = None
    conflicts: Optional[list] = None  # 冲突详情


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

    # 使用锁保护全局字典写入
    async with container_ports_lock:
        container_ports[conversation_id] = container_info["port"]

    async with conversations_lock:
        conversations[conversation_id] = {
            "conversation_id": conversation_id,
            "title": req.title,
            "model": req.model,
            "status": "active",
            "container_info": container_info,
            "created_at": datetime.now(TZ_UTC8).isoformat(),
        }

    async with branches_lock:
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
    async with conversations_lock:
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
    async with httpx.AsyncClient(timeout=120.0) as client:  # 延长到120秒
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
    async with httpx.AsyncClient(timeout=60.0) as client:  # 延长到60秒
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
    async with httpx.AsyncClient(timeout=60.0) as client:  # 延长到60秒
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

    try:
        container_info = await orchestrator.fork_container(
            parent_conversation_id=conversation_id,
            new_branch_name=req.new_branch_name,
        )

        new_conversation_id = container_info["new_conversation_id"]
        
        async with container_ports_lock:
            container_ports[new_conversation_id] = container_info["port"]

        async with conversations_lock:
            conversations[new_conversation_id] = {
                "conversation_id": new_conversation_id,
                "title": container_info.get("branch_name", f"{conversations[conversation_id]['title']} (fork)"),
                "model": conversations[conversation_id]["model"],
                "status": "active",
                "parent_id": conversation_id,
                "container_info": container_info,
                "created_at": datetime.now(TZ_UTC8).isoformat(),
            }

        async with branches_lock:
            branches[new_conversation_id] = {
                "branch_id": new_conversation_id,
                "conversation_id": new_conversation_id,
                "parent_branch_id": conversation_id,
                "status": "active",
                "name": container_info.get("branch_name", ""),
                "created_at": datetime.now(TZ_UTC8).isoformat(),
            }

        return ForkResponse(
            new_conversation_id=new_conversation_id,
            parent_conversation_id=conversation_id,
            status="active"
        )

    except Exception as e:
        print(f"[BFF] Fork error: {e}")
        raise HTTPException(status_code=500, detail=f"Fork failed: {str(e)}")


@app.post("/conversations/merge", response_model=MergeResponse)
async def merge_conversations(req: MergeRequest):
    """智能合并分支：支持LCA定位、冲突检测、LLM融合"""
    if req.source_conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Source conversation not found")
    if req.target_conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Target conversation not found")

    try:
        # 使用新的智能合并功能
        merge_result = await orchestrator.merge_branches(
            source_conversation_id=req.source_conversation_id,
            target_conversation_id=req.target_conversation_id,
            conversations=conversations,
            auto_merge=req.auto_merge,
            conflict_resolutions=req.conflict_resolutions
        )

        status = merge_result.get("status", "error")
        
        if status == "merged":
            # 合并成功，清理源分支元数据（使用锁保护）
            async with conversations_lock:
                if req.source_conversation_id in conversations:
                    del conversations[req.source_conversation_id]
            
            async with container_ports_lock:
                if req.source_conversation_id in container_ports:
                    del container_ports[req.source_conversation_id]
            
            async with branches_lock:
                if req.source_conversation_id in branches:
                    del branches[req.source_conversation_id]
            
            return MergeResponse(
                status="merged",
                message=f"成功合并 {req.source_conversation_id} -> {req.target_conversation_id}",
                trajectory_count=merge_result.get("merged_data", {}).get("trajectory_count", 0),
                merge_result=merge_result.get("merged_data", {})
            )
            
        elif status == "conflict":
            # 存在冲突，返回冲突信息
            return MergeResponse(
                status="conflict",
                message="检测到合并冲突，需要用户手动解决",
                conflicts=merge_result.get("conflicts", [])
            )
            
        else:
            # 合并失败
            return MergeResponse(
                status="error",
                message=merge_result.get("message", "合并失败")
            )
            
    except Exception as e:
        print(f"[BFF] Merge error: {e}")
        return MergeResponse(
            status="error",
            message=f"合并失败: {str(e)}"
        )


@app.post("/conversations/memory-merge", response_model=MergeResponse)
async def memory_merge_conversations(req: MemoryMergeRequest):
    """仅合并长期记忆，不处理对话历史和轨迹"""
    if req.source_conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Source conversation not found")
    if req.target_conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Target conversation not found")

    result = await orchestrator.merge_memory_only(
        source_conversation_id=req.source_conversation_id,
        target_conversation_id=req.target_conversation_id,
    )
    
    if result.get("status") == "merged":
        # 清理源分支元数据
        async with conversations_lock:
            if req.source_conversation_id in conversations:
                del conversations[req.source_conversation_id]
        async with container_ports_lock:
            if req.source_conversation_id in container_ports:
                del container_ports[req.source_conversation_id]
        async with branches_lock:
            if req.source_conversation_id in branches:
                del branches[req.source_conversation_id]
        
        return MergeResponse(
            status="merged",
            message=f"成功合并记忆 {req.source_conversation_id} -> {req.target_conversation_id}",
            merge_result={"merged_memory_length": result.get("merged_memory_length", 0)}
        )
    elif result.get("status") == "no_change":
        return MergeResponse(
            status="no_change",
            message="两个分支的记忆都为空，无需合并"
        )
    else:
        return MergeResponse(status="error", message=result.get("message", "合并失败"))


# 保留旧接口用于兼容
@app.post("/merge", response_model=MergeResponse)
async def legacy_merge_conversations(req: MergeRequest):
    """旧版简单合并接口（兼容性）"""
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
        message="简单合并完成",
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


@app.get("/conversations/status")
async def get_conversations_status():
    """获取所有对话的真实状态（包括容器状态）"""
    status_list = []
    for conv_id, conv in conversations.items():
        try:
            container_name = f"nanobot_conv_{conv_id}"
            container = orchestrator.docker_client.containers.get(container_name)
            status_list.append({
                "conversation_id": conv_id,
                "status": container.status,
                "healthy": container.status == "running",
                "title": conv["title"],
                "model": conv["model"],
                "parent_id": conv.get("parent_id"),
                "created_at": conv.get("created_at")
            })
        except Exception:
            status_list.append({
                "conversation_id": conv_id,
                "status": "not_found",
                "healthy": False,
                "title": conv["title"],
                "model": conv["model"],
                "parent_id": conv.get("parent_id"),
                "created_at": conv.get("created_at")
            })
    
    return {"conversations": status_list}


@app.on_event("startup")
async def startup():
    """启动时清理无效对话"""
    print("[BFF] 启动时清理无效对话...")
    
    # 获取所有对话ID的副本，避免在迭代时修改字典
    conv_ids = list(conversations.keys())
    
    for conv_id in conv_ids:
        try:
            # 检查容器是否存在且健康
            container_name = f"nanobot_conv_{conv_id}"
            container = orchestrator.docker_client.containers.get(container_name)
            
            if container.status != "running":
                print(f"[BFF] 删除无效对话 {conv_id}，容器状态: {container.status}")
                # 删除无效对话
                if conv_id in conversations:
                    del conversations[conv_id]
                if conv_id in container_ports:
                    del container_ports[conv_id]
                if conv_id in branches:
                    del branches[conv_id]
        except Exception as e:
            print(f"[BFF] 删除无效对话 {conv_id}，容器不存在: {e}")
            # 容器不存在，删除对话
            if conv_id in conversations:
                del conversations[conv_id]
            if conv_id in container_ports:
                del container_ports[conv_id]
            if conv_id in branches:
                del branches[conv_id]
    
    print(f"[BFF] 清理完成，剩余对话: {len(conversations)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
