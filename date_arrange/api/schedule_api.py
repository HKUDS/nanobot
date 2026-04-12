"""日程规划API接口"""

from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel

from ..models.task import Task, TaskCreateRequest, TaskUpdateRequest, TaskListResponse
from ..models.schedule import Schedule, ScheduleCreateRequest, ScheduleUpdateRequest, ScheduleResponse, ScheduleListResponse
from ..skills.planner.task_parser import parse_user_goal
from ..skills.planner.schedule_creator import create_optimized_schedule

router = APIRouter(prefix="/schedule", tags=["schedule"])


class ParseRequest(BaseModel):
    """解析请求模型"""
    user_input: str = Field(..., description="用户自然语言输入")
    context: Optional[dict] = Field(None, description="上下文信息")


class ParseResponse(BaseModel):
    """解析响应模型"""
    tasks: List[Task] = Field(..., description="解析出的任务列表")
    message: str = Field(..., description="响应消息")


class CreateScheduleRequest(BaseModel):
    """创建日程请求模型"""
    tasks: List[Task] = Field(..., description="任务列表")
    date: str = Field(..., description="日程日期")
    constraints: Optional[dict] = Field(None, description="约束条件")


class CreateScheduleResponse(BaseModel):
    """创建日程响应模型"""
    schedule: Schedule = Field(..., description="创建的日程")
    suggestions: List[str] = Field(..., description="改进建议")
    message: str = Field(..., description="响应消息")


# 内存存储（实际项目中应使用数据库）
_tasks_storage = {}
_schedules_storage = {}


@router.post("/parse", response_model=ParseResponse)
async def parse_user_input(request: ParseRequest):
    """
    解析用户自然语言输入为结构化任务
    
    Args:
        request: 包含用户输入和上下文
        
    Returns:
        解析出的任务列表
    """
    try:
        result = parse_user_goal(request.user_input, request.context)
        
        # 转换任务数据
        tasks = [Task.from_dict(task_data) for task_data in result["tasks"]]
        
        return ParseResponse(
            tasks=tasks,
            message=result["message"]
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")


@router.post("/create", response_model=CreateScheduleResponse)
async def create_schedule(request: CreateScheduleRequest):
    """
    创建优化日程
    
    Args:
        request: 包含任务列表、日期和约束条件
        
    Returns:
        创建的日程和改进建议
    """
    try:
        # 转换任务数据
        task_dicts = [task.to_dict() for task in request.tasks]
        
        # 创建日程
        result = create_optimized_schedule(task_dicts, request.date, request.constraints)
        
        # 转换日程数据
        schedule = Schedule.from_dict(result["schedule"])
        
        # 存储日程（实际项目中应使用数据库）
        schedule_id = f"schedule_{schedule.date}"
        _schedules_storage[schedule_id] = schedule
        
        return CreateScheduleResponse(
            schedule=schedule,
            suggestions=result["suggestions"],
            message=result["message"]
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"日程创建失败: {str(e)}")


@router.get("/tasks", response_model=TaskListResponse)
async def get_all_tasks():
    """
    获取所有任务
    
    Returns:
        任务列表和统计信息
    """
    tasks = list(_tasks_storage.values())
    
    completed_count = sum(1 for task in tasks if task.status == "completed")
    total_duration = sum(task.duration_minutes for task in tasks)
    
    return TaskListResponse(
        tasks=tasks,
        total_count=len(tasks),
        completed_count=completed_count,
        total_duration=total_duration
    )


@router.get("/schedules", response_model=ScheduleListResponse)
async def get_all_schedules():
    """
    获取所有日程
    
    Returns:
        日程列表和统计信息
    """
    schedules = list(_schedules_storage.values())
    
    total_duration = sum(schedule.total_duration for schedule in schedules)
    average_efficiency = sum(schedule.efficiency_score for schedule in schedules) / max(len(schedules), 1)
    
    return ScheduleListResponse(
        schedules=schedules,
        total_count=len(schedules),
        total_duration=total_duration,
        average_efficiency=round(average_efficiency, 2)
    )


@router.get("/schedules/{date}", response_model=ScheduleResponse)
async def get_schedule_by_date(date: str):
    """
    根据日期获取日程
    
    Args:
        date: 日期（YYYY-MM-DD格式）
        
    Returns:
        指定日期的日程
    """
    schedule_id = f"schedule_{date}"
    
    if schedule_id not in _schedules_storage:
        raise HTTPException(status_code=404, detail=f"日期 {date} 的日程不存在")
    
    schedule = _schedules_storage[schedule_id]
    
    return ScheduleResponse(
        schedule=schedule,
        message=f"成功获取 {date} 的日程"
    )


@router.put("/schedules/{date}", response_model=ScheduleResponse)
async def update_schedule(date: str, request: ScheduleUpdateRequest):
    """
    更新日程
    
    Args:
        date: 日期
        request: 更新数据
        
    Returns:
        更新后的日程
    """
    schedule_id = f"schedule_{date}"
    
    if schedule_id not in _schedules_storage:
        raise HTTPException(status_code=404, detail=f"日期 {date} 的日程不存在")
    
    schedule = _schedules_storage[schedule_id]
    
    # 更新可用时间
    if request.available_time is not None:
        schedule.available_time = request.available_time
        schedule.calculate_efficiency_score()
    
    schedule.update_timestamp()
    
    return ScheduleResponse(
        schedule=schedule,
        message=f"成功更新 {date} 的日程"
    )


@router.delete("/schedules/{date}")
async def delete_schedule(date: str):
    """
    删除日程
    
    Args:
        date: 日期
        
    Returns:
        删除结果
    """
    schedule_id = f"schedule_{date}"
    
    if schedule_id not in _schedules_storage:
        raise HTTPException(status_code=404, detail=f"日期 {date} 的日程不存在")
    
    del _schedules_storage[schedule_id]
    
    return {"message": f"成功删除 {date} 的日程"}


# 健康检查接口
@router.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "date_arrange",
        "version": "0.1.0",
        "tasks_count": len(_tasks_storage),
        "schedules_count": len(_schedules_storage)
    }