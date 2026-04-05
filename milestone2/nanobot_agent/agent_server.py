"""Containerized Nanobot Agent - HTTP API for containerized agent interaction.

基于 AgentLoop 实现完整的 nanobot agent 功能：
- 维护一个 AgentLoop 实例（容器启动时初始化）
- 支持多轮对话（Session 管理）
- 支持 memory 和 history 读取
- 轨迹记录（通过 Hook）
"""

import json
import os
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from uvicorn.config import LOGGING_CONFIG

LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s [%(levelname)s] %(message)s"

app = FastAPI(title="Nanobot Containerized Agent")

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/app/workspace"))
CONVERSATION_ID = os.environ.get("CONVERSATION_ID", "unknown")
TASK = os.environ.get("TASK", "")


class ChatRequest(BaseModel):
    content: str
    model: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: str
    content: str
    usage: dict
    trajectory: list


class TrajectoryRecord(BaseModel):
    iteration: int
    s_t: dict
    a_t: dict
    o_t: dict
    r_t: float


# 全局变量：AgentLoop 实例和 Trace Hook
agent_loop: Any = None
trace_hook: Any = None


class MemoryResponse(BaseModel):
    conversation_id: str
    memory_content: str
    history_content: str


def get_workspace() -> Path:
    workspace = WORKSPACE_DIR / f"conv_{CONVERSATION_ID}"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def get_trajectory_file() -> Path:
    return get_workspace() / "trajectory.jsonl"


def save_trajectory(record: dict):
    with open(get_trajectory_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_trajectory() -> list:
    traj_file = get_trajectory_file()
    if not traj_file.exists():
        return []

    records = []
    with open(traj_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


async def initialize_agent():
    """初始化 AgentLoop 实例"""
    global agent_loop, trace_hook
    
    try:
        # 确保代理环境变量被正确设置（大小写都设置，供不同库使用）
        http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
        https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        no_proxy = os.environ.get('NO_PROXY') or os.environ.get('no_proxy')

        if http_proxy:
            os.environ['HTTP_PROXY'] = http_proxy
            os.environ['http_proxy'] = http_proxy
        if https_proxy:
            os.environ['HTTPS_PROXY'] = https_proxy
            os.environ['https_proxy'] = https_proxy
        if no_proxy:
            os.environ['NO_PROXY'] = no_proxy
            os.environ['no_proxy'] = no_proxy

        # 设置 DeepSeek 的 base URL（通过环境变量）
        os.environ['OPENAI_BASE_URL'] = 'https://api.deepseek.com/v1'

        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        from nanobot.agent.hook import AgentHook, AgentHookContext

        api_key = os.environ.get("API_KEY", "")
        model = os.environ.get("MODEL", "deepseek-chat")

        # 创建基础组件
        bus = MessageBus()
        provider = OpenAICompatProvider(api_key=api_key)

        # 创建 AgentLoop 实例
        agent_loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=WORKSPACE_DIR,
            model=model,
            max_iterations=10,
        )

        # 创建 Trace Hook（用于记录轨迹）
        class TraceHook(AgentHook):
            def __init__(self):
                self.s_t = {}
                self.a_t = {}
                self.o_t = {}
                self.r_t = 0.0
                self.iteration = 0

            async def before_iteration(self, context: AgentHookContext):
                messages = context.messages or []
                history_text = self._build_history(messages)
                
                # 构建更丰富的 state 信息
                self.s_t = {
                    "task": TASK,
                    "history_summary": history_text,
                    "iteration": context.iteration,
                    "message_count": len(messages),
                    "last_user_msg": self._get_last_user_message(messages),
                }
                self.iteration = context.iteration

            async def after_iteration(self, context: AgentHookContext):
                # 构建更详细的 observation
                response_content = str(context.response.content) if context.response else ""
                self.o_t = {
                    "content": response_content,
                    "response_length": len(response_content),
                }
                self.r_t = 1.0

                # 构建更详细的 action 信息
                if context.tool_calls:
                    self.a_t = {
                        "type": "tool_call",
                        "tools": [
                            {"name": tc.get("name", "unknown"), "args": tc.get("arguments", {})}
                            for tc in context.tool_calls
                        ],
                    }
                else:
                    self.a_t = {
                        "type": "direct",
                        "content": response_content[:200],  # 简要记录回复内容
                    }

                record = {
                    "iteration": self.iteration,
                    "s_t": self.s_t,
                    "a_t": self.a_t,
                    "o_t": self.o_t,
                    "r_t": self.r_t,
                }
                save_trajectory(record)

            def _build_history(self, messages: list) -> str:
                """构建最近 5 条消息的摘要"""
                return "\n".join([
                    f"{m.get('role', 'user')}: {m.get('content', '')[:100]}"
                    for m in messages[-5:]
                ])

            def _get_last_user_message(self, messages: list) -> str:
                """获取最后一条用户消息"""
                for m in reversed(messages):
                    if m.get('role') == 'user':
                        return m.get('content', '')[:200]
                return ""

        trace_hook = TraceHook()

        print(f"[AgentLoop] 初始化成功 for conversation={CONVERSATION_ID}, model={model}")
        print(f"[AgentLoop] Workspace: {WORKSPACE_DIR.absolute()}")
        print(f"[AgentLoop] Proxy settings: HTTP_PROXY={os.environ.get('HTTP_PROXY')}, HTTPS_PROXY={os.environ.get('HTTPS_PROXY')}")
    except Exception as e:
        print(f"[AgentLoop] 初始化失败：{e}")
        import traceback
        traceback.print_exc()
        raise


@app.on_event("startup")
async def startup():
    await initialize_agent()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "conversation_id": CONVERSATION_ID,
        "task": TASK,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """处理聊天请求，使用 AgentLoop 的 _process_message 方法"""
    global agent_loop, trace_hook

    if agent_loop is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        from nanobot.bus.events import InboundMessage, OutboundMessage

        # 构造 InboundMessage
        inbound_msg = InboundMessage(
            channel="container",
            chat_id=CONVERSATION_ID,
            sender_id="user",
            content=req.content,
            metadata={}
        )

        # 获取调用前的消息数量
        session_key = f"container:{CONVERSATION_ID}"
        session = agent_loop.sessions.get_or_create(session_key)
        messages_before = list(session.messages) if hasattr(session, 'messages') else []
        iteration = len(messages_before) // 2 + 1

        # 直接调用 AgentLoop 的 _process_message 方法
        response = await agent_loop._process_message(inbound_msg)

        # 提取响应内容
        assistant_content = response.content if response else ""

        # 获取调用后的消息（确保使用 get_or_create 获取最新会话状态）
        session = agent_loop.sessions.get_or_create(session_key)
        messages_after = list(session.messages) if hasattr(session, 'messages') else []
        
        # 手动构建并保存轨迹记录
        history_text = "\n".join([
            f"{m.get('role', 'user')}: {m.get('content', '')[:100]}"
            for m in messages_after[-5:]
        ])
        
        last_user_msg = ""
        for m in reversed(messages_after):
            if m.get('role') == 'user':
                last_user_msg = m.get('content', '')[:200]
                break
        
        # 构建 state
        s_t = {
            "task": TASK,
            "history_summary": history_text,
            "iteration": iteration,
            "message_count": len(messages_after),
            "last_user_msg": last_user_msg,
        }
        
        # 构建 action
        tool_calls = getattr(response, 'tool_calls', [])
        if tool_calls:
            a_t = {
                "type": "tool_call",
                "tools": [
                    {"name": tc.get("name", "unknown"), "args": tc.get("arguments", {})}
                    for tc in tool_calls
                ],
            }
        else:
            a_t = {
                "type": "direct",
                "content": assistant_content[:200],
            }
        
        # 构建 observation
        o_t = {
            "content": assistant_content,
            "response_length": len(assistant_content),
        }
        
        # 保存轨迹
        record = {
            "iteration": iteration,
            "s_t": s_t,
            "a_t": a_t,
            "o_t": o_t,
            "r_t": 1.0,
        }
        save_trajectory(record)

        # 加载轨迹
        trajectory = load_trajectory()

        return ChatResponse(
            conversation_id=CONVERSATION_ID,
            content=assistant_content,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},  # AgentLoop 暂不返回 usage
            trajectory=trajectory,
        )

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        print(f"[Chat] Error: {error_msg}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/trajectory")
async def get_trajectory():
    return {"conversation_id": CONVERSATION_ID, "trajectory": load_trajectory()}


@app.get("/history")
async def get_history():
    """获取当前会话的历史消息"""
    global agent_loop
    
    if agent_loop is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        # 从 SessionManager 获取会话历史
        session_key = f"container:{CONVERSATION_ID}"
        session = agent_loop.sessions.get_or_create(session_key)
        history = session.get_history(max_messages=100)
        
        return {
            "conversation_id": CONVERSATION_ID,
            "history": history,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading history: {str(e)}")


@app.get("/memory")
async def get_memory():
    """获取长期记忆（MEMORY.md）和会话历史"""
    global agent_loop
    
    if agent_loop is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        # 读取长期记忆文件
        memory_file = WORKSPACE_DIR / "memory" / "MEMORY.md"
        memory_content = ""
        if memory_file.exists():
            memory_content = memory_file.read_text(encoding="utf-8")
        
        # 读取会话历史
        session_key = f"container:{CONVERSATION_ID}"
        session = agent_loop.sessions.get_or_create(session_key)
        history = session.get_history(max_messages=100)
        
        return MemoryResponse(
            conversation_id=CONVERSATION_ID,
            memory_content=memory_content,
            history_content="\n".join([f"{m['role']}: {m['content']}" for m in history]),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading memory: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")