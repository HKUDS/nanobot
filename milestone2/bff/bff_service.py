"""BFF AgentService - FastAPI backend for containerized Nanobot agents.

This module provides the REST API for:
- Conversation management
- Message routing to containerized agents
- Fork/Branch operations
- Merge operations
- Power mechanism with file monitoring
"""

import asyncio
import os
import sys
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import DEEPSEEK_API_KEY, DASHSCOPE_API_KEY
from bff.container_orchestrator import ContainerOrchestrator
from shared.file_monitor import ConversationFileMonitor
from bff.db import init_db, get_db
from bff.token_wallet import TokenWallet
from bff.bounty_hub import BountyHub
from bff.public_space import PublicSpace
from bff.reflex_engine import ReflexEngine
from bff.social_graph import SocialGraph
from bff.evaluator import SubmissionEvaluator

# 先定义全局字典
conversations: dict = {}
branches: dict = {}
container_ports: dict = {}

# 再初始化依赖字典的组件
token_wallet = TokenWallet()
bounty_hub = BountyHub(token_wallet)
public_space = PublicSpace()
reflex_engine = ReflexEngine()
social_graph = SocialGraph()

# 同步容器端口映射到 bounty_hub
bounty_hub.set_container_ports(container_ports)

# 再初始化容器编排器
orchestrator = ContainerOrchestrator(container_ports=container_ports)

# 设置 orchestrator 引用到 bounty_hub
bounty_hub.set_orchestrator(orchestrator)

# 初始化文件监控器（传入Docker客户端以访问容器内文件）
conv_file_monitor = ConversationFileMonitor(docker_client=orchestrator.docker_client)

# Power计算器
class PowerCalculator:
    def __init__(self, alpha=0.6, beta=0.4, gamma=0.9):
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma

    def calculate_delta(self, reward_norm: float, annotation_score: float = 0.0) -> float:
        return self.alpha * (reward_norm - 0.5) + self.beta * annotation_score

    def update_power(self, old_power: float, delta: float) -> float:
        new_power = old_power + delta
        # 应用指数移动平均（EMA）
        new_power = self.gamma * old_power + (1 - self.gamma) * new_power
        return max(0.0, min(100.0, new_power))

# 全局Power计算器实例
power_calc = PowerCalculator()

# 标签分数映射
LABEL_SCORES = {
    "Bug": -5,
    "Misleading": -3,
    "Creative": 2,
    "Helpful": 1,
    "Efficient": 2,
    "Good": 1,
    "Bad": -1,
}


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
            # Power机制相关字段
            "power": 50.0,                      # 当前Power值
            "power_history": [],                # Power历史记录
            "file_stats": {},                  # 文件统计信息
            "last_file_check": None,           # 最后文件检查时间
            "annotations": [],                # 标注记录
            "total_annotations": 0,           # 累计标注次数
        }

    async with branches_lock:
        branches[conversation_id] = {
            "branch_id": conversation_id,
            "conversation_id": conversation_id,
            "parent_branch_id": None,
            "status": "active",
        }

    await token_wallet.ensure_wallet(conversation_id)

    return ConversationResponse(
        conversation_id=conversation_id,
        title=req.title,
        model=req.model,
        status="active",
    )


@app.get("/conversations")
async def list_conversations():
    async with conversations_lock:
        conv_list = []
        for cid, conv in conversations.items():
            # 获取钱包余额
            try:
                balance = await token_wallet.get_balance(cid)
            except:
                balance = 0
            
            conv_list.append({
                **conv,
                "container_port": container_ports.get(cid),
                "balance": balance  # 新增：包含钱包余额
            })
        return {"conversations": conv_list}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        **conversations[conversation_id],
        "container_port": container_ports.get(conversation_id),
    }





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
                # 添加 Power 机制字段
                "power": 50.0,
                "power_history": [],
                "file_stats": {},
                "last_file_check": None,
                "annotations": [],
                "total_annotations": 0,
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

        # 自动建立父子节点的邻居关系
        try:
            await bounty_hub.relation_manager.add_relation(conversation_id, new_conversation_id, 1)
            print(f"[BFF] 自动建立邻居关系: {conversation_id} <-> {new_conversation_id}")
        except Exception as e:
            print(f"[BFF] 建立邻居关系失败: {e}")

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
    """启动时初始化数据库和清理无效对话"""
    print("[BFF] 初始化数据库...")
    init_db()
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
    
    # 迁移：为所有对话补充 Power 相关字段
    print("[BFF] 开始迁移对话数据，补充 Power 机制字段...")
    for conv_id, conv in conversations.items():
        if "power" not in conv:
            conv["power"] = 50.0
            conv["power_history"] = []
            conv["annotations"] = []
            conv["total_annotations"] = 0
            print(f"[BFF] 迁移对话 {conv_id} 的 Power 字段")
        if "file_stats" not in conv:
            conv["file_stats"] = {}
        if "last_file_check" not in conv:
            conv["last_file_check"] = None
    print(f"[BFF] 迁移完成，共处理 {len(conversations)} 个对话")

    # 启动定时邻居发现任务
    asyncio.create_task(_periodic_neighbor_discovery())
    print("[BFF] 启动定时邻居发现任务")

    # 启动容器健康监控任务
    asyncio.create_task(_periodic_health_check())
    print("[BFF] 启动容器健康监控任务")


async def _periodic_health_check():
    """定期检查容器健康状态"""
    while True:
        try:
            await _check_container_health()
        except Exception as e:
            print(f"[BFF] 容器健康检查失败: {e}")
        await asyncio.sleep(60)


async def _check_container_health():
    """检查所有容器的健康状态"""
    async with conversations_lock:
        conv_ids = list(conversations.keys())

    unhealthy_count = 0
    for conv_id in conv_ids:
        try:
            container_name = f"nanobot_conv_{conv_id}"
            container = orchestrator.docker_client.containers.get(container_name)
            if container.status != "running":
                print(f"[BFF] 容器不健康 {conv_id}: {container.status}")
                unhealthy_count += 1
        except Exception as e:
            # 容器不存在
            print(f"[BFF] 容器不存在 {conv_id}: {e}")
            unhealthy_count += 1

    if unhealthy_count > 0:
        print(f"[BFF] 健康检查: {len(conv_ids)} 个容器中 {unhealthy_count} 个不健康")
    else:
        print(f"[BFF] 健康检查: 所有 {len(conv_ids)} 个容器运行正常")


async def _periodic_neighbor_discovery():
    """定时发现新节点并建立邻居关系"""
    while True:
        try:
            await _discover_and_connect_neighbors()
        except Exception as e:
            print(f"[BFF] 邻居发现失败: {e}")
        await asyncio.sleep(60)  # 每60秒检查一次


async def _discover_and_connect_neighbors():
    """发现并连接新节点 - 仅补充缺失的父子关系

    当前逻辑：只建立父子节点的邻居关系（fork 时创建）
    不做全连接，发现新节点只补充与父节点的连接
    """
    async with conversations_lock:
        all_nodes = list(conversations.keys())

    if len(all_nodes) < 2:
        print(f"[BFF] 邻居发现: 节点数量不足 ({len(all_nodes)})，跳过")
        return

    # 只补充缺失的父子关系，不做全连接
    new_connections = 0
    for node_id in all_nodes:
        parent_id = conversations[node_id].get("parent_id")
        if parent_id and parent_id in all_nodes:
            # 检查是否已存在父子关系
            existing = await bounty_hub.relation_manager.get_relation(node_id, parent_id)
            if not existing:
                try:
                    await bounty_hub.relation_manager.add_relation(node_id, parent_id, 1)
                    print(f"[BFF] 补充父子邻居关系: {node_id} <-> {parent_id}")
                    new_connections += 1
                except Exception as e:
                    print(f"[BFF] 建立邻居关系失败 ({node_id} <-> {parent_id}): {e}")

    if new_connections > 0:
        print(f"[BFF] 邻居发现完成，新增 {new_connections} 个连接")
    else:
        print(f"[BFF] 邻居发现: 所有父子关系已建立")


# Power机制相关函数
async def update_power_with_file_monitoring(conversation_id: str, reward: float, file_changes: dict):
    """带文件监控的Power更新"""
    async with conversations_lock:
        conv = conversations.get(conversation_id)
        if not conv:
            return
        
        # 兼容旧数据：如果缺少 power 字段，初始化
        if "power" not in conv:
            conv["power"] = 50.0
            conv["power_history"] = []
            conv["annotations"] = []
            conv["total_annotations"] = 0
        
        old_power = conv["power"]
        delta = power_calc.calculate_delta(reward_norm=reward)
        new_power = power_calc.update_power(old_power, delta)
        
        # 构建更新原因（包含文件变化信息）
        reason = f"auto_reward_{reward}"
        if file_changes:
            file_info = ", ".join([f"{k}:{v['status']}" for k, v in file_changes.items()])
            reason = f"{reason} (files: {file_info})"
        
        conv["power"] = new_power
        conv["power_history"].append({
            "timestamp": datetime.now(TZ_UTC8).isoformat(),
            "value": new_power,
            "reason": reason,
            "file_changes": file_changes  # 新增：记录文件变化
        })
        
        # 记录到文件监控日志
        conv_file_monitor.log_conversation_changes(
            conversation_id,
            "power_update",
            f"Power updated: {old_power:.1f} -> {new_power:.1f} (Δ{delta:+.1f})"
        )


# Power机制API接口
class AnnotationCreate(BaseModel):
    conversation_id: str
    step: Union[int, str] = 0
    target_type: str = "action"
    label: str


@app.post("/annotations")
async def add_annotation(req: AnnotationCreate):
    logger.info(f"[annotations] Received: conversation_id={req.conversation_id}, step={req.step}, label={req.label}")
    step = int(req.step) if req.step else 0
    conv = conversations.get(req.conversation_id)
    if not conv:
        raise HTTPException(404, detail="Conversation not found")
    
    score = LABEL_SCORES.get(req.label, 0)
    
    async with conversations_lock:
        # 存储标注
        annotation = {
            "id": str(uuid.uuid4()),
            "step": req.step,
            "target_type": req.target_type,
            "label": req.label,
            "score": score,
            "created_at": datetime.now(TZ_UTC8).isoformat(),
        }
        conv["annotations"].append(annotation)
        conv["total_annotations"] += 1
        
        # 更新Power
        old_power = conv["power"]
        delta = power_calc.calculate_delta(reward_norm=0.5, annotation_score=score)
        new_power = power_calc.update_power(old_power, delta)
        
        print(f"[Power] Reward: {score}, Delta: {delta}")
        
        conv["power"] = new_power
        conv["power_history"].append({
            "timestamp": datetime.now(TZ_UTC8).isoformat(),
            "value": new_power,
            "reason": f"annotation_{req.label}"
        })
    
    return {"status": "ok", "power": new_power, "power_delta": delta}


@app.get("/conversations/{conversation_id}/power")
async def get_power(conversation_id: str):
    """获取对话Power信息"""
    conv = conversations.get(conversation_id)
    if not conv:
        raise HTTPException(404, detail="Conversation not found")
    
    # 兼容旧数据：如果缺少 power 字段，初始化
    if "power" not in conv:
        conv["power"] = 50.0
        conv["power_history"] = []
        conv["annotations"] = []
        conv["total_annotations"] = 0
    
    return {
        "power": conv["power"],
        "history": conv.get("power_history", []),
        "total_annotations": conv.get("total_annotations", 0)
    }


@app.get("/conversations/{conversation_id}/annotations")
async def get_annotations(conversation_id: str):
    """获取对话的所有标注"""
    conv = conversations.get(conversation_id)
    if not conv:
        raise HTTPException(404, detail="Conversation not found")

    return {
        "annotations": conv.get("annotations", []),
        "total_annotations": conv.get("total_annotations", 0)
    }


@app.get("/conversations/{conversation_id}/files")
async def get_conversation_files(conversation_id: str):
    """获取对话文件状态"""
    conv = conversations.get(conversation_id)
    if not conv:
        raise HTTPException(404, detail="Conversation not found")
    
    try:
        # 更新文件状态
        file_stats = conv_file_monitor.get_conversation_stats(conversation_id)
        conv["file_stats"] = file_stats
        conv["last_file_check"] = datetime.now(TZ_UTC8).isoformat()
        
        return {
            "file_stats": file_stats,
            "last_file_check": conv["last_file_check"],
            "monitored_files": conv_file_monitor.key_files
        }
    except Exception as e:
        # 文件监控失败时返回友好提示
        print(f"[BFF] 文件监控失败: {e}")
        return {
            "file_stats": {},
            "message": "container_not_ready",
            "last_file_check": datetime.now(TZ_UTC8).isoformat(),
            "monitored_files": conv_file_monitor.key_files
        }


@app.get("/conversations/{conversation_id}/file-changes")
async def get_file_changes(conversation_id: str, limit: int = 20):
    """获取文件变化历史"""
    # 从文件监控器获取变化历史
    files = conv_file_monitor.get_conversation_files(conversation_id)
    
    changes_history = {}
    for file_path in files:
        history = conv_file_monitor.monitor.get_change_history(file_path, limit)
        filename = Path(file_path).name
        changes_history[filename] = history
    
    return {"file_changes": changes_history}


@app.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(conversation_id: str, req: MessageSend):
    """发送消息并自动更新Power（增强版本）"""
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv = conversations[conversation_id]
    if "file_stats" not in conv:
        conv["file_stats"] = {}
    if "last_file_check" not in conv:
        conv["last_file_check"] = None
    if "power" not in conv:
        conv["power"] = 50.0
        conv["power_history"] = []
        conv["annotations"] = []
        conv["total_annotations"] = 0

    current_state = {
        "goal": conv.get("title", ""),
        "history_summary": "",
        "available_skills": [],
        "environment": {"type": "workspace"}
    }

    reflex = None
    # reflex = await reflex_engine.match(current_state)
    # if reflex and reflex.get("confidence", 0) >= 0.85:
    #     return MessageResponse(
    #         conversation_id=conversation_id,
    #         content=f"[反射匹配] {reflex['action_sequence']}",
    #         usage={"type": "reflex", "confidence": reflex.get("confidence", 0)},
    #         trajectory=[{"action": "reflex_match", "confidence": reflex.get("confidence", 0)}]
    #     )

    url = f"{get_container_url(conversation_id)}/chat"
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.post(url, json={"content": req.content, "model": req.model})
            resp.raise_for_status()
            result = resp.json()

            changes = conv_file_monitor.monitor_conversation(conversation_id)
            file_stats = conv_file_monitor.get_conversation_stats(conversation_id)

            file_changes_summary = {}
            for filename, change in changes.items():
                if change.get("status") != "present":
                    file_changes_summary[filename] = {
                        "status": change.get("status"),
                        "size_delta": change.get("size_delta", 0),
                        "lines_delta": change.get("lines_delta", 0)
                    }

            trajectory = result.get("trajectory", [])
            last_r = 0.5
            if trajectory:
                last_r = trajectory[-1].get("r_t", 0.5)

            async with conversations_lock:
                conversations[conversation_id]["file_stats"] = file_stats
                conversations[conversation_id]["last_file_check"] = datetime.now(TZ_UTC8).isoformat()

            if trajectory:
                await update_power_with_file_monitoring(
                    conversation_id,
                    last_r,
                    file_changes_summary
                )

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


class BountyCreate(BaseModel):
    title: str
    description: str
    reward_pool: int
    docker_reward: int = 0
    deadline: datetime
    issuer_id: str

class SubmissionCreate(BaseModel):
    content: str
    skill_code: Optional[str] = None
    cost_tokens: int = 0
    agent_id: str

@app.post("/bounties")
async def api_create_bounty(req: BountyCreate):
    try:
        if req.issuer_id not in conversations:
            raise HTTPException(status_code=404, detail="Conversation not found")
        bounty_id = await bounty_hub.create_bounty(req.issuer_id, req.title, req.description, req.reward_pool, req.deadline, req.docker_reward)
        return {"bounty_id": bounty_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create bounty: {str(e)}")

@app.get("/bounties")
async def api_list_bounties():
    try:
        bounties = await bounty_hub.list_open_bounties()
        logger.info(f"[bounties] 返回 {len(bounties)} 个开放悬赏")
        return {"bounties": bounties}
    except Exception as e:
        logger.error(f"[bounties] 列出悬赏失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list bounties: {str(e)}")

@app.get("/bounties/{bounty_id}")
async def api_get_bounty(bounty_id: str):
    try:
        bounty = await bounty_hub.get_bounty(bounty_id)
        if not bounty:
            raise HTTPException(status_code=404, detail="Bounty not found")
        return bounty
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get bounty: {str(e)}")

@app.post("/bounties/{bounty_id}/submit")
async def api_submit_solution(bounty_id: str, req: SubmissionCreate):
    try:
        if req.agent_id not in conversations:
            raise HTTPException(status_code=404, detail="Conversation not found")
        sub_id = await bounty_hub.submit_solution(bounty_id, req.agent_id, req.content, req.skill_code, req.cost_tokens)
        return {"submission_id": sub_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit solution: {str(e)}")

@app.get("/bounties/{bounty_id}/submissions")
async def api_get_submissions(bounty_id: str):
    try:
        submissions = await bounty_hub.get_submissions(bounty_id)
        return {"submissions": submissions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get submissions: {str(e)}")

@app.post("/bounties/{bounty_id}/evaluate")
async def api_evaluate_bounty(bounty_id: str, winner_ids: List[str], scores: List[float]):
    try:
        await bounty_hub.evaluate_and_reward(bounty_id, winner_ids, scores)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to evaluate bounty: {str(e)}")


class AIAssistRequest(BaseModel):
    user_input: str
    conversation_history: Optional[List[Dict[str, str]]] = []


class CurateSkillRequest(BaseModel):
    issuer_id: str
    submission_id: str
    name: str
    capability: str
    usage: Optional[str] = None


class CloseBountyRequest(BaseModel):
    issuer_id: str


class RelationCreate(BaseModel):
    source_node_id: str
    target_node_id: str
    weight: int = 1


class NotificationResponse(BaseModel):
    id: str
    node_id: str
    bounty_id: str
    type: str
    status: str
    created_at: str


@app.post("/node-relations")
async def api_add_relation(req: RelationCreate):
    try:
        print(f"[NodeRelation] 添加关系: {req.source_node_id} -> {req.target_node_id}, weight={req.weight}")
        await bounty_hub.relation_manager.add_relation(req.source_node_id, req.target_node_id, req.weight)
        return {"status": "ok"}
    except Exception as e:
        print(f"[NodeRelation] 添加关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add relation: {str(e)}")


@app.get("/node-relations/{node_id}/neighbors")
async def api_get_neighbors(node_id: str):
    try:
        print(f"[NodeRelation] 获取邻居: node_id={node_id}")
        neighbors = await bounty_hub.relation_manager.get_neighbors(node_id)
        return {"neighbors": neighbors}
    except Exception as e:
        print(f"[NodeRelation] 获取邻居失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get neighbors: {str(e)}")


@app.get("/node-relations/all")
async def api_get_all_relations():
    """获取所有节点关系（用于前端显示边权）"""
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM node_relations").fetchall()
        relations = []
        for row in rows:
            relations.append({
                "source": row["source_node_id"],
                "target": row["target_node_id"],
                "weight": row["weight"]
            })
        return {"relations": relations}
    except Exception as e:
        print(f"[NodeRelation] 获取所有关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get relations: {str(e)}")


@app.get("/notifications/{node_id}")
async def api_get_notifications(node_id: str):
    try:
        with get_db() as conn:
            rows = conn.execute("""
                SELECT * FROM notifications
                WHERE node_id = ?
                ORDER BY created_at DESC
            """, (node_id,)).fetchall()
        notifications = []
        for row in rows:
            notifications.append({
                "id": row["id"],
                "node_id": row["node_id"],
                "bounty_id": row["bounty_id"],
                "type": row["type"],
                "status": row["status"],
                "created_at": row["created_at"]
            })
        return {"notifications": notifications}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get notifications: {str(e)}")


@app.post("/notifications/{notification_id}/process")
async def api_process_notification(notification_id: str):
    """将通知状态更新为 processing，避免重复处理"""
    try:
        print(f"[Notification] 更新状态为 processing: {notification_id}")
        with get_db() as conn:
            conn.execute("""
                UPDATE notifications SET status = 'processing' WHERE id = ?
            """, (notification_id,))
        return {"status": "ok"}
    except Exception as e:
        print(f"[Notification] 更新状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process notification: {str(e)}")


@app.post("/notifications/{notification_id}/complete")
async def api_complete_notification(notification_id: str):
    """将通知状态更新为 completed"""
    try:
        print(f"[Notification] 更新状态为 completed: {notification_id}")
        with get_db() as conn:
            conn.execute("""
                UPDATE notifications SET status = 'completed' WHERE id = ?
            """, (notification_id,))
        return {"status": "ok"}
    except Exception as e:
        print(f"[Notification] 更新状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to complete notification: {str(e)}")


@app.post("/bounties/{bounty_id}/close")
async def api_close_bounty(bounty_id: str, req: CloseBountyRequest):
    """关闭悬赏任务，只有发布者可以操作"""
    try:
        print(f"[BFF] 关闭悬赏任务: bounty_id={bounty_id}, issuer={req.issuer_id}")
        result = await bounty_hub.close_bounty(bounty_id, req.issuer_id)
        print(f"[BFF] 悬赏任务关闭成功: {result}")
        return result
    except ValueError as e:
        print(f"[BFF] 关闭悬赏任务失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[BFF] 关闭悬赏任务异常: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to close bounty: {str(e)}")


@app.post("/bounties/{bounty_id}/ai-assist")
async def api_ai_assist(bounty_id: str, req: AIAssistRequest):
    """大模型辅助填充方案字段"""
    try:
        # 获取任务信息
        bounty = await bounty_hub.get_bounty(bounty_id)
        if not bounty:
            raise HTTPException(status_code=404, detail="Bounty not found")
        
        # 构建提示词
        prompt = f"""你是一个 AI 助手，帮助用户为以下悬赏任务生成解决方案：

任务标题：{bounty['title']}
任务描述：{bounty['description']}
奖励：{bounty['reward_pool']} Token
Docker 奖励：{bounty.get('docker_reward', 0)}

用户输入：{req.user_input}

请生成一个详细的解决方案，包括：
1. 解决方案内容
2. 相关的 Skill 代码（如果适用）
3. 预计消耗的 Token 数量

输出格式：
解决方案内容：[详细内容]
Skill 代码：[代码]
消耗 Token：[数字]
"""
        
        # 调用 DeepSeek API
        import httpx
        deepseek_api_key = DEEPSEEK_API_KEY
        if not deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
        headers = {
            "Authorization": f"Bearer {deepseek_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你是一个专业的 AI 助手，帮助用户解决技术问题。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0
            )
            
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"DeepSeek API error: {response.text}")
        
        data = response.json()
        assistant_response = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # 解析响应
        content = ""
        skill_code = ""
        cost_tokens = 0
        
        # 尝试不同的解析方式，增强健壮性
        lines = assistant_response.split('\n')
        for line in lines:
            line = line.strip()
            # 支持多种格式
            if line.startswith('解决方案内容：') or line.startswith('解决方案：') or line.startswith('内容：'):
                content = line.split('：', 1)[1].strip() if '：' in line else line
            elif line.startswith('Skill 代码：') or line.startswith('代码：') or line.startswith('skill：'):
                skill_code = line.split('：', 1)[1].strip() if '：' in line else line
            elif line.startswith('消耗 Token：') or line.startswith('消耗：') or line.startswith('token：'):
                try:
                    token_part = line.split('：', 1)[1].strip() if '：' in line else line
                    cost_tokens = int(''.join(filter(str.isdigit, token_part)))
                except:
                    cost_tokens = 0
        
        # 如果解析失败，使用完整响应作为内容
        if not content:
            content = assistant_response
        
        return {
            "content": content,
            "skill_code": skill_code,
            "cost_tokens": cost_tokens,
            "assistant_response": assistant_response
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI assist failed: {str(e)}")


@app.post("/bounties/{bounty_id}/curate-skill")
async def api_curate_skill(bounty_id: str, req: CurateSkillRequest):
    """将邻居节点的反馈整理为 skill（基于邻居节点的反馈）"""
    try:
        print(f"[Bounty] 手动整理 skill: bounty_id={bounty_id}")
        print(f"[Bounty]   name: {req.name}")
        print(f"[Bounty]   capability: {req.capability}")
        print(f"[Bounty]   usage: {req.usage}")
        print(f"[Bounty]   submission_id (邻居节点): {req.submission_id}")

        # 验证发布者身份
        with get_db() as conn:
            row = conn.execute("SELECT issuer_id FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
            if not row or row["issuer_id"] != req.issuer_id:
                raise HTTPException(status_code=403, detail="Only issuer can curate skill")

        # 保存到公共知识库
        public_space = PublicSpace()
        doc_id = await public_space.add_skill(
            name=req.name,
            capability=req.capability,
            usage=req.usage,
            source_submission_id=req.submission_id,
            author_id=req.issuer_id
        )

        # 导出到宿主机
        from shared.config import SKILL_EXPORT_DIR
        try:
            export_path = await public_space.export_skill_as_markdown(doc_id, SKILL_EXPORT_DIR)
            print(f"[Bounty] Skill 导出成功：{export_path}")
        except Exception as e:
            print(f"[Bounty] Skill 导出失败：{e}")

        print(f"[Bounty] Skill 保存成功：doc_id={doc_id}")
        return {"doc_id": doc_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Bounty] Skill 保存失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to curate skill: {str(e)}")


@app.post("/bounties/{bounty_id}/evaluate-submissions")
async def api_evaluate_submissions(bounty_id: str):
    """对指定悬赏的所有未评分提交进行自动评分"""
    try:
        print(f"[Evaluator API] 开始评分: bounty_id={bounty_id}")

        with get_db() as conn:
            bounty = conn.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
            if not bounty:
                raise HTTPException(status_code=404, detail="Bounty not found")

            submissions = conn.execute(
                "SELECT * FROM submissions WHERE bounty_id = ? AND (score IS NULL OR score = 0)",
                (bounty_id,)
            ).fetchall()

        print(f"[Evaluator API] 找到 {len(submissions)} 个未评分的提交")

        if len(submissions) == 0:
            print(f"[Evaluator API] 没有需要评分的提交")
            return {"evaluated": 0, "message": "No submissions to evaluate"}

        evaluator = SubmissionEvaluator()
        bounty_dict = dict(bounty)

        for sub in submissions:
            sub_dict = dict(sub)
            score, reason = await evaluator.evaluate(bounty_dict, sub_dict)

            with get_db() as conn:
                conn.execute(
                    "UPDATE submissions SET score = ?, score_reason = ? WHERE id = ?",
                    (score, reason, sub["id"])
                )
            print(f"[Evaluator API] 提交 {sub['id']} 评分完成: score={score}, reason={reason}")

        print(f"[Evaluator API] 评分完成，共 {len(submissions)} 个提交")
        return {"evaluated": len(submissions)}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Evaluator API] 评分失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to evaluate submissions: {str(e)}")


class TransferRequest(BaseModel):
    from_id: str
    to_id: str
    amount: int
    reason: str

@app.get("/wallet/{conv_id}/balance")
async def api_get_balance(conv_id: str):
    try:
        balance = await token_wallet.get_balance(conv_id)
        return {"conversation_id": conv_id, "balance": balance}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get balance: {str(e)}")

@app.post("/wallet/transfer")
async def api_transfer(req: TransferRequest):
    try:
        await token_wallet.transfer(req.from_id, req.to_id, req.amount, req.reason)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to transfer: {str(e)}")

@app.post("/public-space/search")
async def api_search_knowledge(query: str, top_k: int = 5):
    results = await public_space.search(query, top_k)
    return {"results": results}

@app.post("/public-space/upload")
async def api_upload_knowledge(
    title: str,
    content: str,
    skill_code: str,
    tags: List[str],
    author_id: str,
    knowledge_type: str = "skill"
):
    doc_id = await public_space.upload(title, content, skill_code, tags, author_id, knowledge_type)
    return {"doc_id": doc_id}


@app.get("/public-skills")
async def api_list_skills():
    """获取所有 skill"""
    print(f"[BFF] 获取所有 skill")
    try:
        skills = await public_space.list_skills()
        print(f"[BFF] 返回 {len(skills)} 个 skill")
        return {"skills": skills}
    except Exception as e:
        print(f"[BFF] 获取 skill 列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list skills: {str(e)}")

@app.get("/public-skills/{skill_id}")
async def api_get_skill(skill_id: str):
    """获取单个 skill 详情"""
    print(f"[BFF] 获取 skill: skill_id={skill_id}")
    try:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM public_knowledge WHERE id = ?", (skill_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        skill = dict(row)
        if isinstance(skill.get("tags"), str):
            skill["tags"] = json.loads(skill["tags"])
        return skill
    except HTTPException:
        raise
    except Exception as e:
        print(f"[BFF] 获取 skill 失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get skill: {str(e)}")

@app.post("/reflex/match")
async def api_match_reflex(state: dict, threshold: float = 0.85):
    reflex = await reflex_engine.match(state, threshold)
    return {"reflex": reflex}

@app.post("/reflex/learn")
async def api_learn_reflex(state: dict, action_sequence: List[dict], agent_id: str, success: bool = True):
    await reflex_engine.learn(state, action_sequence, agent_id, success)
    return {"status": "ok"}

@app.get("/reflex/list")
async def api_list_reflexes():
    reflexes = await reflex_engine.get_all_reflexes()
    return {"reflexes": reflexes}

@app.post("/social/friend")
async def api_add_friend(agent_a: str, agent_b: str):
    await social_graph.add_friend(agent_a, agent_b)
    return {"status": "ok"}

@app.get("/social/friends/{agent_id}")
async def api_get_friends(agent_id: str):
    friends = await social_graph.get_friends(agent_id)
    return {"friends": friends}

@app.get("/social/friends/{agent_id}/with-trust")
async def api_get_friends_with_trust(agent_id: str):
    friends = await social_graph.get_friends_with_trust(agent_id)
    return {"friends": friends}

@app.post("/social/trust")
async def api_update_trust(agent_a: str, agent_b: str, delta: float):
    await social_graph.update_trust(agent_a, agent_b, delta)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
