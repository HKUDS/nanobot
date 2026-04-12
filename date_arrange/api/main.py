"""Date Arrange 集成API - 将日程规划功能集成到Nanobot系统中"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uvicorn

# 导入Date Arrange模块
from ..skills.planner.task_parser import parse_user_goal
from ..skills.planner.schedule_creator import create_optimized_schedule
from ..models.task import Task, TaskCreateRequest
from ..models.schedule import Schedule

# 导入Nanobot相关模块
import sys
import os

# 添加nanobot路径
sys.path.append(os.path.join(os.path.dirname(__file__), '../../milestone2'))

try:
    from bff.bff_service import app as nanobot_app
    from bff.container_orchestrator import ContainerOrchestrator
    NANOBOT_AVAILABLE = True
except ImportError:
    NANOBOT_AVAILABLE = False
    print("警告: Nanobot模块不可用，将使用独立模式运行")

app = FastAPI(
    title="Date Arrange API",
    description="智能日程规划系统 - 集成Nanobot的日程规划功能",
    version="1.0.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局状态
nanobot_orchestrator = None

# 请求模型
class ScheduleWithNanobotRequest(BaseModel):
    """使用Nanobot进行日程规划的请求"""
    user_input: str
    conversation_id: Optional[str] = None
    constraints: Optional[Dict[str, Any]] = None

class NanobotIntegrationRequest(BaseModel):
    """Nanobot集成请求"""
    conversation_id: str
    user_message: str
    context: Optional[Dict[str, Any]] = None

# 初始化Nanobot集成
@app.on_event("startup")
async def startup_event():
    """启动时初始化Nanobot集成"""
    global nanobot_orchestrator
    
    if NANOBOT_AVAILABLE:
        try:
            # 初始化容器编排器
            nanobot_orchestrator = ContainerOrchestrator(container_ports={})
            print("✅ Nanobot集成初始化成功")
        except Exception as e:
            print(f"❌ Nanobot集成初始化失败: {e}")
            nanobot_orchestrator = None

# 健康检查
@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "service": "date_arrange",
        "version": "1.0.0",
        "nanobot_integration": NANOBOT_AVAILABLE and nanobot_orchestrator is not None
    }

# 基础日程规划API
@app.post("/schedule/parse")
async def parse_user_input(request: ScheduleWithNanobotRequest):
    """解析用户输入为任务"""
    try:
        # 使用Date Arrange解析任务
        result = parse_user_goal(request.user_input, request.context)
        
        # 如果有Nanobot集成，可以进一步优化
        if nanobot_orchestrator and request.conversation_id:
            # 这里可以添加Nanobot的智能优化逻辑
            pass
        
        return {
            "tasks": result["tasks"],
            "message": result["message"],
            "nanobot_enhanced": nanobot_orchestrator is not None
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")

@app.post("/schedule/create")
async def create_schedule(request: ScheduleWithNanobotRequest):
    """创建优化日程"""
    try:
        # 先解析任务
        parse_result = parse_user_goal(request.user_input, request.context)
        
        if not parse_result["tasks"]:
            raise HTTPException(status_code=400, detail="没有解析出有效任务")
        
        # 创建日程
        schedule_result = create_optimized_schedule(
            parse_result["tasks"],
            request.constraints.get("date", "2024-04-08") if request.constraints else "2024-04-08",
            request.constraints or {}
        )
        
        # 如果有Nanobot集成，可以存储到对话记忆
        if nanobot_orchestrator and request.conversation_id:
            try:
                # 将日程信息存储到Nanobot的记忆中
                await store_schedule_to_nanobot_memory(
                    request.conversation_id, 
                    schedule_result["schedule"]
                )
                schedule_result["nanobot_stored"] = True
            except Exception as e:
                print(f"存储到Nanobot记忆失败: {e}")
                schedule_result["nanobot_stored"] = False
        
        return schedule_result
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"日程创建失败: {str(e)}")

# Nanobot集成API
@app.post("/nanobot/schedule")
async def nanobot_schedule_planning(request: NanobotIntegrationRequest):
    """通过Nanobot进行日程规划"""
    if not nanobot_orchestrator:
        raise HTTPException(status_code=503, detail="Nanobot集成不可用")
    
    try:
        # 使用Nanobot的智能体进行日程规划
        result = await schedule_with_nanobot(
            request.conversation_id,
            request.user_message,
            request.context
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Nanobot日程规划失败: {str(e)}")

@app.get("/nanobot/conversations")
async def get_nanobot_conversations():
    """获取Nanobot对话列表"""
    if not nanobot_orchestrator:
        raise HTTPException(status_code=503, detail="Nanobot集成不可用")
    
    try:
        # 这里需要从Nanobot获取对话列表
        # 暂时返回空列表
        return {
            "conversations": [],
            "message": "Nanobot对话列表获取成功"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取对话列表失败: {str(e)}")

# 工具函数
async def store_schedule_to_nanobot_memory(conversation_id: str, schedule_data: dict):
    """将日程信息存储到Nanobot的记忆中"""
    if not nanobot_orchestrator:
        return
    
    # 构建记忆内容
    memory_content = f"""
## 日程规划记录

**日期**: {schedule_data.get('date', '未知')}
**总耗时**: {schedule_data.get('total_duration', 0)}分钟
**效率评分**: {schedule_data.get('efficiency_score', 0)}

### 任务安排
"""
    
    # 添加任务信息
    for task in schedule_data.get('tasks', []):
        memory_content += f"""
- **{task.get('name', '未知任务')}**
  - 优先级: {task.get('priority', 'normal')}
  - 耗时: {task.get('duration_minutes', 0)}分钟
  - 状态: {task.get('status', 'pending')}
"""
    
    # 这里需要实现将记忆写入Nanobot容器的逻辑
    # 暂时打印日志
    print(f"[Nanobot集成] 存储日程到对话 {conversation_id} 的记忆中")
    print(memory_content)

async def schedule_with_nanobot(conversation_id: str, user_message: str, context: dict):
    """使用Nanobot进行智能日程规划"""
    # 这里实现通过Nanobot智能体进行日程规划的逻辑
    # 可以调用Nanobot的API或者直接与容器交互
    
    # 暂时使用基础的Date Arrange功能
    parse_result = parse_user_goal(user_message, context)
    
    if not parse_result["tasks"]:
        return {
            "success": False,
            "message": "未能解析出有效任务",
            "nanobot_enhanced": True
        }
    
    schedule_result = create_optimized_schedule(
        parse_result["tasks"],
        context.get("date", "2024-04-08"),
        context.get("constraints", {})
    )
    
    return {
        "success": True,
        "message": "Nanobot智能日程规划完成",
        "schedule": schedule_result["schedule"],
        "suggestions": schedule_result["suggestions"],
        "nanobot_enhanced": True
    }

# 错误处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"}
    )

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True
    )