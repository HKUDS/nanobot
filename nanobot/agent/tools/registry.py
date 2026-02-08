"""Tool registry for dynamic tool management."""

from typing import Any

from nanobot.agent.tools.base import Tool


class ToolRegistry:
    """
    Registry for agent tools.
    
    Allows dynamic registration and execution of tools.
    """
    # 工具注册表：智能体工具的动态管理组件
    # 作用：集中管理所有可用工具，支持工具的注册、查找和执行
    # 设计目的：实现工具的松耦合管理，支持运行时动态扩展
    # 好处：易于添加新工具，支持工具的统一验证和错误处理，提高系统可维护性
    
    def __init__(self):
        # 初始化工具注册表
        # 作用：创建空的工具字典，准备接收工具注册
        # 设计目的：提供轻量级启动，支持按需添加工具
        # 好处：降低初始化开销，支持动态工具管理，便于资源优化
    
    def register(self, tool: Tool) -> None:
        """Register a tool."""
        # 注册工具
        # 作用：将工具实例添加到注册表中，供智能体调用
        # 设计目的：支持集中式工具管理，便于工具查找和访问控制
        # 好处：确保工具的唯一性，支持工具状态管理，便于权限控制
        self._tools[tool.name] = tool
    
    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        # 注销工具
        # 作用：从注册表中移除指定名称的工具
        # 设计目的：支持动态工具管理，便于运行时调整可用工具集
        # 好处：提高系统灵活性，支持安全策略调整，便于资源回收
        self._tools.pop(name, None)
    
    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        # 获取工具
        # 作用：根据工具名称查找并返回工具实例
        # 设计目的：提供安全的工具访问接口，支持工具存在性检查
        # 好处：避免直接访问内部数据结构，提高代码健壮性，便于调试
        return self._tools.get(name)
    
    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        # 检查工具是否已注册
        # 作用：判断指定名称的工具是否存在于注册表中
        # 设计目的：支持条件性工具调用，避免运行时错误
        # 好处：提高代码安全性，便于错误预防，支持优雅降级
        return name in self._tools
    
    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        # 获取所有工具定义（OpenAI格式）
        # 作用：生成符合OpenAI工具调用API的工具定义列表
        # 设计目的：标准化工具接口，支持与不同LLM提供商兼容
        # 好处：简化工具调用逻辑，提高系统互操作性，便于集成
        return [tool.to_schema() for tool in self._tools.values()]
    
    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """
        Execute a tool by name with given parameters.
        
        Args:
            name: Tool name.
            params: Tool parameters.
        
        Returns:
            Tool execution result as string.
        
        Raises:
            KeyError: If tool not found.
        """
        # 执行工具
        # 作用：根据名称查找工具，并使用给定参数执行工具逻辑
        # 设计目的：提供统一的工具执行接口，支持参数验证和错误处理
        # 好处：提高代码可靠性，便于调试和监控，支持安全执行环境
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"

        try:
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors)
            return await tool.execute(**params)
        except Exception as e:
            return f"Error executing {name}: {str(e)}"
    
    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools
