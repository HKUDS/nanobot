"""内置插件管理器"""

from loguru import logger
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config


class PluginManager:
    """管理订阅系统事件的内置插件"""

    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self._plugins: list[Any] = []

    async def initialize(self) -> None:
        """初始化已启用的插件"""
        # 启动问候插件
        if self.config.plugins.startup_greeting.enabled:
            from nanobot.plugins.startup_greeting import StartupGreetingPlugin

            plugin = StartupGreetingPlugin(
                config=self.config.plugins.startup_greeting,
                bus=self.bus,
                full_config=self.config,
            )
            self.bus.subscribe_system(plugin.on_gateway_ready)
            self._plugins.append(plugin)
            logger.info("启动问候插件已启用")
