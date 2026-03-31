"""实验配置数据类"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ExperimentConfig:
    """单个实验的配置"""
    session_key: str
    memory_config: str
    tool_config: str
    task_name: str
    model: str = "deepseek-chat"
    repetition: int = 1

    def __post_init__(self):
        valid_memory = {"VR", "SW"}
        valid_tool = {"CG", "FG"}
        if self.memory_config not in valid_memory:
            raise ValueError(f"memory_config must be one of {valid_memory}")
        if self.tool_config not in valid_tool:
            raise ValueError(f"tool_config must be one of {valid_tool}")

    @property
    def full_key(self) -> str:
        return f"{self.memory_config}_{self.tool_config}_{self.task_name}_rep{self.repetition}"

    def to_dict(self) -> dict:
        return {
            "session_key": self.session_key,
            "memory_config": self.memory_config,
            "tool_config": self.tool_config,
            "task_name": self.task_name,
            "model": self.model,
            "repetition": self.repetition,
        }


@dataclass
class ExperimentResult:
    """单个实验的结果"""
    session_key: str
    memory_config: str
    tool_config: str
    task_name: str
    model: str
    success: bool
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    request_count: int
    execution_time: float
    estimated_tokens: int = 0  # 估算的 token 数
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "session_key": self.session_key,
            "memory_config": self.memory_config,
            "tool_config": self.tool_config,
            "task_name": self.task_name,
            "model": self.model,
            "success": self.success,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "request_count": self.request_count,
            "execution_time": self.execution_time,
            "estimated_tokens": self.estimated_tokens,
            "error_message": self.error_message,
        }
