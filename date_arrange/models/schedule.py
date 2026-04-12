"""日程数据模型"""

from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field, validator
from .task import Task


class TimeSlot(BaseModel):
    """时间段模型"""
    
    start_time: str = Field(..., description="开始时间（HH:MM）")
    end_time: str = Field(..., description="结束时间（HH:MM）")
    task_id: Optional[str] = Field(None, description="分配的任务ID")
    
    @validator('start_time', 'end_time')
    def validate_time_format(cls, v):
        """验证时间格式"""
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError('时间格式必须为 HH:MM')
    
    def duration_minutes(self) -> int:
        """计算时间段时长（分钟）"""
        start = datetime.strptime(self.start_time, '%H:%M')
        end = datetime.strptime(self.end_time, '%H:%M')
        return int((end - start).total_seconds() / 60)


class Schedule(BaseModel):
    """日程数据模型"""
    
    date: str = Field(..., description="日期（YYYY-MM-DD）")
    tasks: List[Task] = Field(default_factory=list, description="当日任务列表")
    time_slots: List[TimeSlot] = Field(default_factory=list, description="时间段安排")
    
    total_duration: int = Field(default=0, description="总任务耗时（分钟）")
    available_time: int = Field(default=480, description="可用时间（分钟，默认8小时）")
    efficiency_score: float = Field(default=0.0, description="日程效率评分（0-1）")
    
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    @validator('date')
    def validate_date_format(cls, v):
        """验证日期格式"""
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError('日期格式必须为 YYYY-MM-DD')
    
    def update_timestamp(self):
        """更新时间戳"""
        self.updated_at = datetime.now().isoformat()
    
    def calculate_total_duration(self):
        """计算总任务耗时"""
        self.total_duration = sum(task.duration_minutes for task in self.tasks)
    
    def calculate_efficiency_score(self):
        """计算日程效率评分"""
        if self.available_time == 0:
            self.efficiency_score = 0.0
            return
        
        # 基础效率：任务时间占可用时间的比例
        time_utilization = min(self.total_duration / self.available_time, 1.0)
        
        # 优先级权重：高优先级任务占比
        high_priority_tasks = [t for t in self.tasks if t.priority in ['urgent_important', 'important']]
        priority_weight = len(high_priority_tasks) / max(len(self.tasks), 1)
        
        # 综合评分
        self.efficiency_score = round(time_utilization * 0.7 + priority_weight * 0.3, 2)
    
    def add_task(self, task: Task):
        """添加任务到日程"""
        self.tasks.append(task)
        self.calculate_total_duration()
        self.calculate_efficiency_score()
        self.update_timestamp()
    
    def remove_task(self, task_id: str):
        """从日程中移除任务"""
        self.tasks = [t for t in self.tasks if t.id != task_id]
        self.calculate_total_duration()
        self.calculate_efficiency_score()
        self.update_timestamp()
    
    def assign_time_slot(self, task_id: str, time_slot: TimeSlot):
        """为任务分配时间段"""
        time_slot.task_id = task_id
        self.time_slots.append(time_slot)
        self.update_timestamp()
    
    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """根据ID获取任务"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        """从字典创建日程实例"""
        return cls(**data)


class ScheduleCreateRequest(BaseModel):
    """创建日程请求模型"""
    
    date: str = Field(..., description="日期")
    available_time: int = Field(default=480, description="可用时间")


class ScheduleUpdateRequest(BaseModel):
    """更新日程请求模型"""
    
    available_time: Optional[int] = Field(None, description="可用时间")


class ScheduleResponse(BaseModel):
    """日程响应模型"""
    
    schedule: Schedule = Field(..., description="日程数据")
    message: str = Field("", description="响应消息")


class ScheduleListResponse(BaseModel):
    """日程列表响应模型"""
    
    schedules: List[Schedule] = Field(..., description="日程列表")
    total_count: int = Field(..., description="总日程数")
    total_duration: int = Field(..., description="总耗时")
    average_efficiency: float = Field(..., description="平均效率评分")