"""任务数据模型"""

from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field
import uuid


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress" 
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """任务优先级枚举"""
    URGENT_IMPORTANT = "urgent_important"  # 紧急且重要
    IMPORTANT = "important"                # 重要不紧急
    URGENT = "urgent"                      # 紧急不重要
    NORMAL = "normal"                      # 普通
    LOW = "low"                            # 低优先级


class Task(BaseModel):
    """任务数据模型"""
    
    id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    name: str = Field(..., description="任务名称", min_length=1, max_length=200)
    description: str = Field("", description="任务详细描述", max_length=1000)
    duration_minutes: int = Field(..., description="预计耗时（分钟）", ge=1, le=480)
    priority: TaskPriority = Field(default=TaskPriority.NORMAL, description="任务优先级")
    
    deadline: Optional[str] = Field(None, description="截止时间（ISO格式）")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    tags: List[str] = Field(default_factory=list, description="标签分类")
    
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    
    def update_timestamp(self):
        """更新时间戳"""
        self.updated_at = datetime.now().isoformat()
    
    def mark_completed(self):
        """标记任务为已完成"""
        self.status = TaskStatus.COMPLETED
        self.update_timestamp()
    
    def mark_in_progress(self):
        """标记任务为进行中"""
        self.status = TaskStatus.IN_PROGRESS
        self.update_timestamp()
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """从字典创建任务实例"""
        return cls(**data)


class TaskCreateRequest(BaseModel):
    """创建任务请求模型"""
    
    name: str = Field(..., description="任务名称")
    description: str = Field("", description="任务描述")
    duration_minutes: int = Field(..., description="预计耗时")
    priority: TaskPriority = Field(default=TaskPriority.NORMAL)
    deadline: Optional[str] = Field(None, description="截止时间")
    tags: List[str] = Field(default_factory=list)
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "TaskCreateRequest":
        """从字典创建任务实例"""
        return cls(**data)


class TaskUpdateRequest(BaseModel):
    """更新任务请求模型"""
    
    name: Optional[str] = Field(None, description="任务名称")
    description: Optional[str] = Field(None, description="任务描述")
    duration_minutes: Optional[int] = Field(None, description="预计耗时")
    priority: Optional[TaskPriority] = Field(None, description="优先级")
    deadline: Optional[str] = Field(None, description="截止时间")
    status: Optional[TaskStatus] = Field(None, description="任务状态")
    tags: Optional[List[str]] = Field(None, description="标签")


class TaskListResponse(BaseModel):
    """任务列表响应模型"""
    
    tasks: List[Task] = Field(..., description="任务列表")
    total_count: int = Field(..., description="总任务数")
    completed_count: int = Field(..., description="已完成任务数")
    total_duration: int = Field(..., description="总耗时（分钟）")